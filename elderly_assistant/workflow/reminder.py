# -*- coding: utf-8 -*-
"""用药提醒工作流：提醒状态机、计划轮询线程、心跳线程、触发检测（纯逻辑，无硬件依赖）。"""
import logging
import threading
from datetime import datetime, timedelta

logger = logging.getLogger("ElderlyAssistant")


def _normalize_hhmm(t):
    """归一化 HH:MM 时间格式，非法输入返回 None，确保后续时间比较使用统一格式。"""
    if not t:
        return None
    try:
        return datetime.strptime(str(t).strip()[:5], "%H:%M").strftime("%H:%M")
    except Exception:
        return None


class MedicationPoller:
    """
    用药计划轮询线程
    每隔 poll_interval 秒向服务器请求用药计划，缓存到 self.schedules
    使用 threading.Lock 保护 schedules 的读写，防止跨线程迭代时被替换
    注意：心跳上报已拆分到独立的 HeartbeatThread，避免业务请求失败导致心跳丢失
    """

    def __init__(self, http_client, poll_interval=60):
        self.http_client = http_client
        self.poll_interval = poll_interval
        self._schedules = []
        self._lock = threading.Lock()
        self.last_success = False
        self._stop_flag = threading.Event()
        self._thread = None

    @property
    def schedules(self):
        """读取时返回列表快照，避免主线程遍历时被轮询线程替换。"""
        with self._lock:
            return list(self._schedules)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag.set()

    def _run(self):
        # 启动后立即拉取一次
        while not self._stop_flag.is_set():
            try:
                if self.http_client:
                    schedules = self.http_client.get_medication_schedule()
                    with self._lock:
                        self._schedules = schedules or []
                    self.last_success = True
                else:
                    with self._lock:
                        self._schedules = []
                    self.last_success = False
            except Exception as e:
                logger.warning(f"拉取用药计划失败: {e}")
                self.last_success = False
            # 等待下一次轮询（可被停止中断）
            self._stop_flag.wait(self.poll_interval)

    def get_next_reminder(self, now=None):
        """
        返回今天尚未到来的下一个提醒（dict 或 None）
        :param now: datetime，默认当前时间
        """
        # 通过 property 获取快照，避免迭代中被修改
        schedules = self.schedules
        if not schedules:
            return None
        if now is None:
            now = datetime.now()
        now_hm = now.strftime("%H:%M")
        upcoming = []
        for s in schedules:
            t = _normalize_hhmm(s.get('time'))
            if not t:
                continue
            # 仅返回当前时间之后（>now）的提醒
            if t > now_hm:
                upcoming.append((t, s))
        if not upcoming:
            return None
        # 按时间升序，取最早一个
        upcoming.sort(key=lambda x: x[0])
        return upcoming[0][1]


class ReminderState:
    """
    当前激活的提醒状态
    - active: 是否有提醒正在响
    - drug_name / dosage: 当前提醒内容
    - snooze_until: 暂缓提醒的复活时间（按B后5分钟）
    - fired_key: 已触发过的 "HH:MM|drug" 集合，避免同一分钟重复触发
    """

    def __init__(self):
        self.active = False
        self.drug_name = ""
        self.dosage = ""
        self.snooze_until = None  # datetime
        self.fired_keys = set()
        self.current_key = ""     # 当前响铃中的提醒 key
        self.items = []

    def trigger(self, drug_name, dosage, key, items=None):
        self.active = True
        self.drug_name = drug_name
        self.dosage = dosage
        self.current_key = key
        self.fired_keys.add(key)
        self.snooze_until = None
        self.items = items or []

    def confirm(self):
        self.active = False
        self.drug_name = ""
        self.dosage = ""
        self.current_key = ""
        self.snooze_until = None

    def snooze(self, snooze_minutes):
        if self.active:
            self.snooze_until = datetime.now() + timedelta(minutes=snooze_minutes)
        # active 保持 True，但蜂鸣器停止；到 snooze_until 后再次响铃


class HeartbeatThread:
    """
    独立心跳线程
    每隔 interval 秒向服务器发送一次心跳，与 MedicationPoller 业务轮询解耦。
    这样业务请求（拉取用药计划）失败时不会导致心跳丢失，
    服务器端能更稳定地判断设备在线状态。
    """

    def __init__(self, http_client, interval=30):
        self.http_client = http_client
        self.interval = interval
        self._stop_flag = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag.set()

    def join(self, timeout=None):
        """等待线程退出。"""
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self):
        # 启动后立即发送一次心跳，让服务器尽快感知设备上线
        while not self._stop_flag.is_set():
            try:
                if self.http_client:
                    self.http_client.send_heartbeat()
            except Exception as e:
                logger.warning(f"心跳发送失败: {e}")
            # 等待下一次心跳（可被停止中断）
            self._stop_flag.wait(self.interval)


def check_medication_trigger(now, poller, reminder_state, buzzer, display, snooze_minutes, logger, speech=None):
    """
    检查是否到达用药提醒时间，触发提醒
    - 到达提醒时间（匹配当前 HH:MM）且未触发过，触发提醒
    - 若处于 snooze 状态且到达 snooze_until，重新响铃
    """
    try:
        now_hm = now.strftime("%H:%M")

        # 处于暂缓状态：检查是否到达复活时间
        if reminder_state.active and reminder_state.snooze_until is not None:
            if now >= reminder_state.snooze_until:
                # 重新响铃
                reminder_state.snooze_until = None
                if not buzzer.is_reminding():
                    buzzer.play_reminder()
                display.show_reminder(reminder_state.drug_name, reminder_state.dosage)
            return

        # 已经在响铃中，不重复触发
        if reminder_state.active:
            return

        # 检查 schedules 是否有匹配当前时间的提醒
        # fired_keys 以日期为前缀，跨日时清空昨日记录，避免集合无限增长
        today = now.strftime("%Y-%m-%d")
        if getattr(reminder_state, "_fired_day", None) != today:
            reminder_state.fired_keys.clear()
            reminder_state._fired_day = today

        # 同一时间可能存在多个用药提醒，需收集全部匹配项并合并为一条复合提醒，
        # 而非命中第一个就退出，否则会遗漏其余提醒。
        matched_reminders = []
        for s in poller.schedules:
            t = _normalize_hhmm(s.get('time'))
            if not t or t != now_hm:
                continue
            drug_name = s.get('drug_name', '药品')
            dosage = s.get('dosage', '')
            key = f"{today}|{t}|{drug_name}"
            # 同一分钟内同一药品只触发一次
            if key in reminder_state.fired_keys:
                continue
            matched_reminders.append({
                "drug_name": drug_name,
                "dosage": dosage,
                "key": key,
                "plan_id": s.get('plan_id'),
                "scheduled_time": s.get('time'),
            })

        if matched_reminders:
            # 合并所有同一时间的提醒为一条复合消息
            if len(matched_reminders) == 1:
                m = matched_reminders[0]
                drug_name, dosage, key = m["drug_name"], m["dosage"], m["key"]
            else:
                # 多个药品合并显示，例如 "阿司匹林 1片、降压药 2片"
                parts = [f"{m['drug_name']} {m['dosage']}" for m in matched_reminders]
                drug_name = "、".join(parts)
                dosage = ""
                # 使用合并后的 key，包含所有药品名
                key = f"{today}|{now_hm}|" + "|".join(m["drug_name"] for m in matched_reminders)
            # 收集本批提醒对应的计划项，供确认时精确回传服务端落库
            items = [{
                "plan_id": m["plan_id"],
                "drug_name": m["drug_name"],
                "dosage": m["dosage"],
                "scheduled_time": m["scheduled_time"],
            } for m in matched_reminders]
            # 触发提醒
            reminder_state.trigger(drug_name, dosage, key, items=items)
            buzzer.play_reminder()
            display.show_reminder(drug_name, dosage)
            # 语音播报提醒（TTS，缺失时静默降级）
            if speech:
                try:
                    speech.speak(f"该吃药了，{drug_name}")
                except Exception:
                    pass
            logger.info(f"触发用药提醒: {drug_name} {dosage} @ {now_hm} (共 {len(matched_reminders)} 个)")
    except Exception as e:
        logger.error(f"检查触发异常: {e}")
