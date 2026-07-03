#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
老人端主程序（行空板 M10）
- 使用 pinpong 库控制硬件（蜂鸣器、按钮、光线传感器、LED）
- 使用 unihiker GUI 显示界面
- 后台热点 + 配网 Web 服务 + 用药计划轮询
- 主循环：更新时间显示、检查按钮、检查用药提醒
"""

import os
import sys
import signal
import argparse
import threading
import time
import json
import logging
from datetime import datetime, timedelta

# 确保以本文件所在目录为工作目录（便于读取 config.yaml / data/）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.getcwd() != BASE_DIR:
    os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DEBUG_MODE = False


def parse_arguments():
    parser = argparse.ArgumentParser(description='老人用药助手 (M10)')
    parser.add_argument('--debug', '-d', action='store_true',
                        help='启用调试模式：允许Ctrl+C退出，详细日志输出')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='输出详细日志到终端')
    return parser.parse_args()


def signal_handler(sig, frame):
    logging.info("收到退出信号，正在清理...")
    sys.exit(0)


def init_pinpong_board():
    """初始化 pinpong Board（行空板M10协处理器）"""
    try:
        from pinpong.board import Board
        Board().begin()
        print("[主程序] pinpong Board 初始化成功")
        return True
    except ImportError:
        print("[警告] pinpong 库未安装（非 M10 环境降级）")
        return False
    except Exception as e:
        print(f"[错误] pinpong Board 初始化失败: {e}")
        return False


def get_buttons():
    """获取按钮 A/B 句柄（查询式），非 M10 环境返回 None"""
    try:
        from pinpong.extension.unihiker import button_a, button_b
        return button_a, button_b
    except ImportError:
        print("[警告] pinpong 按钮不可用（非 M10 环境降级）")
        return None, None
    except Exception as e:
        print(f"[错误] 按钮初始化失败: {e}")
        return None, None


def get_light_sensor():
    """获取光线传感器句柄，非 M10 环境返回 None"""
    try:
        from pinpong.extension.unihiker import light
        return light
    except ImportError:
        return None
    except Exception:
        return None


def get_led():
    """获取 LED 句柄（P25），非 M10 环境返回 None"""
    try:
        from pinpong.board import Pin
        led = Pin(Pin.P25, Pin.OUT)
        return led
    except ImportError:
        return None
    except Exception:
        return None


def create_data_files():
    """创建必要的 data 目录与空文件"""
    data_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    schedules_path = os.path.join(data_dir, "schedules.json")
    if not os.path.exists(schedules_path):
        with open(schedules_path, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=2, ensure_ascii=False)


class MedicationPoller:
    """
    用药计划轮询线程
    每隔 poll_interval 秒向服务器请求用药计划，缓存到 self.schedules
    G14 修复：使用 threading.Lock 保护 schedules 的读写，防止跨线程迭代时被替换
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
        """G14 修复：读取时返回快照，避免主线程遍历时被轮询线程替换"""
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
                logging.warning(f"拉取用药计划失败: {e}")
                self.last_success = False
            # 等待下一次轮询（可被停止中断）
            self._stop_flag.wait(self.poll_interval)

    def get_next_reminder(self, now=None):
        """
        返回今天尚未到来的下一个提醒（dict 或 None）
        :param now: datetime，默认当前时间
        """
        # G14：通过 property 获取快照，避免迭代中被修改
        schedules = self.schedules
        if not schedules:
            return None
        if now is None:
            now = datetime.now()
        now_hm = now.strftime("%H:%M")
        upcoming = []
        for s in schedules:
            t = s.get('time', '')
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

    def trigger(self, drug_name, dosage, key):
        self.active = True
        self.drug_name = drug_name
        self.dosage = dosage
        self.current_key = key
        self.fired_keys.add(key)
        self.snooze_until = None

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


def main():
    global DEBUG_MODE
    args = parse_arguments()
    DEBUG_MODE = args.debug or args.verbose

    # 启动时检查更新（自动更新功能）
    try:
        from updater import check_for_update
        check_for_update()
    except Exception as e:
        logging.warning(f"自动更新检查失败: {e}")

    if DEBUG_MODE:
        print("=" * 60)
        print("老人用药助手 - M10 GUI 模式")
        print("=" * 60)

    signal.signal(signal.SIGINT, signal_handler)
    create_data_files()

    from utils.config_loader import load_config
    from utils.logger import setup_logger
    from services.buzzer import Buzzer
    from services.http_client import HTTPClient
    from services.hotspot_manager import HotspotManager
    from services.wifi_config import WiFiConfigServer
    from services.device_id import get_device_id
    from core.display import Display

    config = load_config()
    log_dir = config.get('paths', {}).get('log_dir', 'logs') if 'paths' in config else 'logs'
    logger = setup_logger(log_dir)
    logger.info("=" * 50)
    logger.info("老人端启动（M10 GUI 模式）")

    # 1. 初始化 pinpong Board
    init_pinpong_board()

    # 2. 创建 GUI 显示界面
    display = Display()

    # 获取设备 FCC ID
    fcc_id = get_device_id()
    server_url = config.get('server', {}).get('base_url', '')
    logger.info(f"设备 FCC ID: {fcc_id}")
    logger.info(f"服务器地址: {server_url}")

    # 3. 初始化蜂鸣器
    buzzer = Buzzer(config)

    # 4. 初始化 HTTP 客户端
    http_client = None
    try:
        http_client = HTTPClient(config)
    except Exception as e:
        logger.error(f"HTTP 客户端初始化失败: {e}")

    # 5. 获取按钮句柄
    button_a, button_b = get_buttons()
    # light_sensor 暂未使用，预留 get_light_sensor() 接口供后续扩展
    led = get_led()

    # 6. 启动后台热点（线程）
    hotspot_cfg = config.get('hotspot', {})
    hotspot = HotspotManager(
        ssid=hotspot_cfg.get('ssid', 'M10-Config'),
        ip=hotspot_cfg.get('ip', '10.0.0.1'),
        web_port=hotspot_cfg.get('web_port', 8088)
    )
    try:
        if hotspot.start_hotspot():
            logger.info("后台热点已启动")
        else:
            logger.error("后台热点启动失败")
    except Exception as e:
        logger.error(f"启动热点异常: {e}")

    # 7. 启动配网 Web 服务（线程）
    web_port = hotspot_cfg.get('web_port', 8088)
    wifi_config_server = WiFiConfigServer(port=web_port)
    try:
        if wifi_config_server.start():
            logger.info(f"配网 Web 服务已启动，端口 {web_port}")
        else:
            logger.error("配网 Web 服务启动失败")
    except Exception as e:
        logger.error(f"启动配网 Web 服务异常: {e}")

    # 8. 启动用药计划轮询线程
    reminder_cfg = config.get('reminder', {})
    poll_interval = reminder_cfg.get('poll_interval', 60)
    snooze_minutes = reminder_cfg.get('snooze_minutes', 5)
    poller = MedicationPoller(http_client, poll_interval=poll_interval)
    poller.start()
    logger.info(f"用药计划轮询线程已启动，间隔 {poll_interval} 秒")

    # 9. 显示主界面
    display.show_main_screen(fcc_id=fcc_id, server_url=server_url, connected=False)

    # 提醒状态
    reminder_state = ReminderState()

    # LED 心跳与服务器状态检查
    last_status_check = 0
    last_button_check = 0
    last_time_update = 0
    server_connected = False
    button_block_until = 0  # G10：非阻塞防抖屏蔽截止时间戳

    # 10. 主循环
    logger.info("进入主循环")
    try:
        while True:
            now = datetime.now()

            # ---- 每秒更新时间显示 ----
            if (now.timestamp() - last_time_update) >= 1.0:
                last_time_update = now.timestamp()
                # 仅当不在提醒响铃界面时更新时间
                if not reminder_state.active:
                    display.show_time(now)

            # ---- 每 10 秒检查一次服务器连接状态 ----
            if (now.timestamp() - last_status_check) >= 10.0:
                last_status_check = now.timestamp()
                try:
                    if http_client:
                        server_connected = http_client.check_connection()
                    else:
                        server_connected = False
                except Exception:
                    server_connected = False
                display.show_status(server_url, server_connected)
                display.show_fcc_id(fcc_id)
                # 更新下一个用药提醒
                if not reminder_state.active:
                    nxt = poller.get_next_reminder(now)
                    display.show_next_reminder(nxt)

            # ---- 检查用药提醒触发 ----
            check_medication_trigger(
                now, poller, reminder_state, buzzer, display, snooze_minutes, logger
            )

            # ---- 检查按钮（约每 200ms 一次）----
            # G10 修复：非阻塞防抖，防抖屏蔽期内跳过按钮检测
            if (now.timestamp() - last_button_check) >= 0.2 and now.timestamp() >= button_block_until:
                last_button_check = now.timestamp()
                # 按钮 A：确认服药
                if button_a and button_a.is_pressed():
                    if reminder_state.active:
                        handle_confirm(reminder_state, buzzer, display, http_client, logger)
                        # 防抖：设置屏蔽期而非 sleep 阻塞主循环
                        button_block_until = now.timestamp() + 0.3
                # 按钮 B：暂不提醒（5分钟后再提醒）
                if button_b and button_b.is_pressed():
                    if reminder_state.active:
                        handle_snooze(reminder_state, buzzer, display, snooze_minutes, logger)
                        button_block_until = now.timestamp() + 0.3

            # ---- LED 心跳：连接时亮，断开时灭 ----
            if led:
                try:
                    led.write_digital(1 if server_connected else 0)
                except Exception:
                    pass

            # 主循环休眠，降低 CPU 占用
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        # 清理资源（S7 修复：更完整地释放资源并等待线程退出）
        logger.info("正在清理资源...")
        try:
            poller.stop()
            # 等待轮询线程退出，避免阻塞在 HTTP 请求中导致僵尸线程
            if hasattr(poller, '_thread') and poller._thread.is_alive():
                poller._thread.join(timeout=2)
        except Exception as e:
            logger.warning(f"停止轮询线程失败: {e}")
        try:
            buzzer.stop()
        except Exception as e:
            logger.warning(f"停止蜂鸣器失败: {e}")
        try:
            wifi_config_server.stop()
        except Exception as e:
            logger.warning(f"停止配网服务失败: {e}")
        try:
            hotspot.stop_hotspot()
        except Exception as e:
            logger.warning(f"停止热点失败: {e}")
        # 关闭 LED（亮着则熄灭）
        try:
            if led:
                led.write_digital(0)
        except Exception:
            pass
        logger.info("老人端已退出")


def check_medication_trigger(now, poller, reminder_state, buzzer, display, snooze_minutes, logger):
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
        # S6 修复：key 含日期，并在跨日时清理昨日 fired_keys，防止内存无限增长
        today = now.strftime("%Y-%m-%d")
        if getattr(reminder_state, "_fired_day", None) != today:
            reminder_state.fired_keys.clear()
            reminder_state._fired_day = today

        for s in poller.schedules:
            t = s.get('time', '')
            if not t or t != now_hm:
                continue
            drug_name = s.get('drug_name', '药品')
            dosage = s.get('dosage', '')
            key = f"{today}|{t}|{drug_name}"
            # 同一分钟内同一药品只触发一次
            if key in reminder_state.fired_keys:
                continue
            # 触发提醒
            reminder_state.trigger(drug_name, dosage, key)
            buzzer.play_reminder()
            display.show_reminder(drug_name, dosage)
            logger.info(f"触发用药提醒: {drug_name} {dosage} @ {t}")
            break
    except Exception as e:
        logger.error(f"检查触发异常: {e}")


def handle_confirm(reminder_state, buzzer, display, http_client, logger):
    """按钮 A：确认服药"""
    try:
        drug = reminder_state.drug_name
        dosage = reminder_state.dosage
        logger.info(f"用户确认服药: {drug} {dosage}")
        buzzer.stop()
        # 上报服药确认（可选，失败不影响）
        if http_client:
            try:
                http_client.confirm_medication(drug, dosage)
            except Exception as e:
                logger.error(f"上报服药确认失败: {e}")
        reminder_state.confirm()
        display.clear_reminder()
        # 播放成功提示音
        try:
            buzzer.play_success()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"处理确认服药异常: {e}")


def handle_snooze(reminder_state, buzzer, display, snooze_minutes, logger):
    """按钮 B：暂不提醒（5分钟后再提醒）"""
    try:
        logger.info(f"用户暂缓提醒，{snooze_minutes} 分钟后再提醒")
        buzzer.stop()
        reminder_state.snooze(snooze_minutes)
        # 返回主界面，等待 snooze_until 到期再响铃
        display.clear_reminder()
    except Exception as e:
        logger.error(f"处理暂缓提醒异常: {e}")


if __name__ == "__main__":
    main()
