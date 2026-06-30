# -*- coding: utf-8 -*-
import schedule
import time
import threading
from datetime import datetime, timedelta
import traceback

from utils.logger import setup_logger
from core.camera import capture_image
from core.uploader import upload_medication_image


class ReminderManager:
    """
    用药提醒管理器
    负责定时检测提醒计划、触发提醒、升级告警、确认处理、自动拨打电话
    """

    def __init__(self, config, schedules, medication_manager,
                 speech, buzzer, http_client, network_online,
                 error_callback=None):
        """
        :param config: 全局配置字典
        :param schedules: 提醒计划列表，每项包含 name, medication, time, dosage, days, enabled 等
        :param medication_manager: MedicationManager 实例
        :param speech: Speech 实例
        :param buzzer: Buzzer 实例
        :param http_client: HTTPClient 实例
        :param network_online: 函数，返回当前网络是否在线
        :param error_callback: 可调用对象，用于向UI报告错误
        """
        self.config = config
        self.schedules = schedules
        self.speech = speech
        self.buzzer = buzzer
        self.med_manager = medication_manager
        self.http_client = http_client
        self.network_online = network_online if callable(network_online) else lambda: False
        self.error_callback = error_callback
        self.logger = setup_logger()
        self.active_reminders = {}
        self.running = True
        self._start_scheduler()

    def _error(self, msg):
        if self.error_callback:
            self.error_callback(msg)

    def _start_scheduler(self):
        self.thread = threading.Thread(target=self._safe_run_scheduler, daemon=True)
        self.thread.start()

    def _safe_run_scheduler(self):
        try:
            self._run_scheduler()
        except Exception as e:
            self.logger.error(f"提醒调度器崩溃: {traceback.format_exc()}")
            self._error("提醒系统故障，请重启")

    def _run_scheduler(self):
        interval = self.config.get('reminders', {}).get('check_interval', 30)
        schedule.every(interval).seconds.do(self.check_due_reminders)
        while self.running:
            try:
                schedule.run_pending()
            except Exception as e:
                self.logger.error(f"调度执行错误: {traceback.format_exc()}")
            time.sleep(1)

    def check_due_reminders(self):
        """检查是否有到期的提醒"""
        try:
            now = datetime.now().strftime("%H:%M")
            weekday = datetime.now().weekday() + 1
            for item in self.schedules:
                days = item.get('days', [])
                if isinstance(days, list):
                    days_str = [str(d) for d in days]
                else:
                    days_str = []
                if (item.get('time') == now and
                    str(weekday) in days_str and
                    item.get('enabled', True)):
                    self.trigger_reminder(item)
        except Exception as e:
            self.logger.error(f"检查提醒错误: {traceback.format_exc()}")

    def trigger_reminder(self, reminder_item):
        """触发一次提醒（语音+蜂鸣器，并启动升级线程）"""
        try:
            rid = f"{reminder_item.get('name', 'unknown')}_{reminder_item.get('time', '')}"
            if rid in self.active_reminders and self.active_reminders[rid].get('confirmed', False):
                return

            name = reminder_item.get('name', '您')
            med_name = reminder_item.get('medication', '')
            dosage = reminder_item.get('dosage', '')
            msg = f"{name}，该服用 {med_name} 了，用量 {dosage}"

            if self.speech:
                try:
                    vol = self.config.get('buzzer', {}).get('base_volume', 0.5)
                    self.speech.speak(msg, vol)
                except Exception as e:
                    self.logger.error(f"语音播报失败: {e}")
            if self.buzzer:
                try:
                    self.buzzer.beep()
                except Exception as e:
                    self.logger.error(f"蜂鸣器失败: {e}")

            self.logger.info(f"提醒触发: {msg}")

            escalation_interval = self.config.get('reminders', {}).get('escalation_interval', 60)
            if rid not in self.active_reminders:
                self.active_reminders[rid] = {
                    'next_escalation': datetime.now() + timedelta(seconds=escalation_interval),
                    'volume': self.config.get('buzzer', {}).get('base_volume', 0.5),
                    'confirmed': False,
                    'thread': None
                }
            else:
                self.active_reminders[rid]['confirmed'] = False
                self.active_reminders[rid]['volume'] = self.config.get('buzzer', {}).get('base_volume', 0.5)
                self.active_reminders[rid]['next_escalation'] = datetime.now() + timedelta(seconds=escalation_interval)

            esc_thread = threading.Thread(
                target=self._safe_escalation,
                args=(rid, reminder_item),
                daemon=True
            )
            self.active_reminders[rid]['thread'] = esc_thread
            esc_thread.start()
        except Exception as e:
            self.logger.error(f"触发提醒失败: {traceback.format_exc()}")
            self._error(f"提醒出错: {e}")

    def _safe_escalation(self, rid, item):
        try:
            self._escalation_check(rid, item)
        except Exception as e:
            self.logger.error(f"升级线程异常: {traceback.format_exc()}")

    def _escalation_check(self, rid, item):
        """未确认时的升级循环，音量递增，达到阈值后自动拨打电话"""
        escalation_count = 0
        max_volume = self.config.get('reminders', {}).get('max_volume', 1.0)
        escalation_interval = self.config.get('reminders', {}).get('escalation_interval', 60)

        while self.running and not self.active_reminders.get(rid, {}).get('confirmed', True):
            now = datetime.now()
            next_escalation = self.active_reminders.get(rid, {}).get('next_escalation')
            if next_escalation and now >= next_escalation:
                escalation_count += 1
                current_vol = self.active_reminders[rid].get('volume', 0.5)
                new_vol = min(current_vol + 0.1, max_volume)
                self.active_reminders[rid]['volume'] = new_vol

                name = item.get('name', '您')
                med_name = item.get('medication', '')
                dosage = item.get('dosage', '')

                if self.speech:
                    try:
                        self.speech.speak(
                            f"{name}，请尽快服药 {med_name}，用量 {dosage}",
                            new_vol
                        )
                    except Exception as e:
                        self.logger.error(f"升级语音播报失败: {e}")
                if self.buzzer:
                    try:
                        self.buzzer.beep(volume=new_vol)
                    except Exception as e:
                        self.logger.error(f"升级蜂鸣器失败: {e}")

                self.logger.warning(
                    f"提醒升级: {name} 未确认，当前音量 {new_vol}，升级次数 {escalation_count}"
                )

                self.active_reminders[rid]['next_escalation'] = now + timedelta(seconds=escalation_interval)

            time.sleep(5)

    def confirm_taken(self, name, time_str):
        """确认服药，结束提醒、拍照上传、更新库存"""
        try:
            rid = f"{name}_{time_str}"
            if rid in self.active_reminders:
                self.active_reminders[rid]['confirmed'] = True

            if self.network_online():
                try:
                    img_path = capture_image(self.config)
                    if img_path and self.http_client:
                        try:
                            upload_medication_image(img_path, self.http_client)
                            self.logger.info(f"已上传服药照片: {img_path}")
                        except Exception as upload_err:
                            self.logger.error(f"上传照片失败: {upload_err}")
                except Exception as img_err:
                    self.logger.error(f"拍照失败: {img_err}")

            if self.med_manager:
                try:
                    for schedule_item in self.schedules:
                        if schedule_item.get('name') == name and schedule_item.get('time') == time_str:
                            med_name = schedule_item.get('medication', '')
                            dosage = schedule_item.get('dosage', '')
                            if med_name:
                                self.med_manager.consume(med_name, dosage)
                            break
                except Exception as med_err:
                    self.logger.error(f"更新药品库存失败: {med_err}")

            self.logger.info(f"确认服药成功: {name} {time_str}")
            if rid in self.active_reminders:
                self.active_reminders.pop(rid, None)
        except Exception as e:
            self.logger.error(f"确认服药处理错误: {traceback.format_exc()}")
            self._error(f"确认服药失败: {e}")

    def add_schedule(self, schedule_item):
        """添加一个提醒计划"""
        self.schedules.append(schedule_item)
        self.logger.info(f"添加提醒: {schedule_item}")

    def remove_schedule(self, name, time_str):
        """删除指定姓名和时间的提醒计划"""
        self.schedules = [
            s for s in self.schedules
            if not (s.get('name') == name and s.get('time') == time_str)
        ]
        self.logger.info(f"删除提醒: {name} {time_str}")

    def stop(self):
        self.running = False