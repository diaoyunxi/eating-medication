#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
老人端主程序（行空板 M10）
- 使用 pinpong 库控制硬件（蜂鸣器、按钮、光线传感器、LED）
- 使用 unihiker GUI 显示界面
- 后台热点 + 配网 Web 服务 + 用药计划轮询
- 主循环：更新时间显示、检查按钮、检查用药提醒

本文件仅负责「装配」与「主循环骨架」：
- 硬件板级访问集中于 hardware.board（Board 初始化幂等、按钮/LED 句柄获取）
- 用药提醒工作流（状态机/轮询/触发/确认/暂缓/AI问答/按钮输入）集中于 workflow
这样业务逻辑与具体硬件解耦，便于在无 M10 硬件环境下进行单元测试。
"""

import os
import sys
import signal
import argparse
import threading
import time
import json
import logging
import importlib
import subprocess
from datetime import datetime
from pathlib import Path

# 模块级 logger，供 signal_handler 等非 main() 函数使用
# main() 内部会通过 global logger 覆盖为 setup_logger() 返回的实例
logger = logging.getLogger(__name__)

# 确保以本文件所在目录为工作目录（便于读取 config.yaml / data/）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.getcwd() != BASE_DIR:
    os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 仓库根目录（含统一迁移的 updater.py）
PROJECT_ROOT = os.path.dirname(BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 工作流与硬件访问层（依赖 elderly_assistant 已在 sys.path 中）
from workflow.reminder import (
    ReminderState,
    MedicationPoller,
    HeartbeatThread,
    check_medication_trigger,
)
from workflow.actions import (
    handle_confirm,
    handle_snooze,
    _ask_ai_and_speak,
    _capture_and_upload,
)
from workflow.button_input import ButtonController
from hardware.board import init_pinpong_board, get_buttons, get_led

DEBUG_MODE = False


def parse_arguments():
    parser = argparse.ArgumentParser(description='老人用药助手 (M10)')
    parser.add_argument('--debug', '-d', action='store_true',
                        help='启用调试模式：允许Ctrl+C退出，详细日志输出')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='输出详细日志到终端')
    return parser.parse_args()


def signal_handler(sig, frame):
    logger.info("收到退出信号，正在清理...")
    sys.exit(0)


def check_and_install_dependencies():
    """检查关键依赖是否已安装，若缺失则调用公共安装脚本 common/install.py（含 huskylens）。"""
    required_modules = [
        ('dotenv', 'python-dotenv'),
        ('requests', 'requests'),
        ('pyttsx3', 'pyttsx3'),
    ]
    missing = []
    for module_name, pip_name in required_modules:
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print(f"检测到缺失依赖: {missing}")
        print("正在调用common/install.py 安装依赖（含 huskylens）...")
        project_root = str(Path(__file__).resolve().parent.parent)
        root_install = os.path.join(project_root, "common", "install.py")
        req_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
        if os.path.exists(root_install):
            try:
                result = subprocess.run(
                    [sys.executable, root_install, req_path, "--huskylens"],
                    capture_output=False, text=True, cwd=project_root,
                )
                if result.returncode != 0:
                    print("依赖安装可能未完全成功，尝试继续运行...")
                else:
                    print("依赖安装完成，正在重新启动老人端...")
                    os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception as e:
                print(f"自动安装失败: {e}")
                print(f"请手动运行: python {root_install} {req_path} --huskylens")
        else:
            print("未找到common/install.py，请手动安装依赖:")
            print(f"pip install {' '.join(missing)}")


def create_data_files():
    """创建必要的 data 目录与空文件。"""
    data_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    schedules_path = os.path.join(data_dir, "schedules.json")
    if not os.path.exists(schedules_path):
        with open(schedules_path, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=2, ensure_ascii=False)


def main():
    global DEBUG_MODE
    global logger
    args = parse_arguments()
    DEBUG_MODE = args.debug or args.verbose

    # 启动前检查依赖，缺失则调用 common/install.py 安装（含 huskylens）
    check_and_install_dependencies()

    # 启动时检查更新（自动更新功能）
    try:
        from updater import check_for_update
        check_for_update()
    except Exception as e:
        logger.warning(f"自动更新检查失败: {e}")

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
    # log_dir 固定使用 logs/（原 paths.log_dir 为幽灵字段，已删除）
    log_dir = 'logs'
    logger = setup_logger(log_dir)
    logger.info("=" * 50)
    logger.info("老人端启动（M10 GUI 模式）")

    # 1. 初始化 pinpong Board（幂等，集中由 hardware.board 管理）
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

    # 3.1 初始化语音播报（TTS，缺失环境静默降级）
    speech = None
    try:
        from services.speech import Speech
        speech = Speech()
    except Exception as e:
        logger.warning(f"语音播报初始化失败，已降级: {e}")

    # 4. 初始化 HTTP 客户端
    http_client = None
    try:
        http_client = HTTPClient(config)
    except Exception as e:
        logger.error(f"HTTP 客户端初始化失败: {e}")

    # 5. 获取按钮句柄
    button_a, button_b = get_buttons()
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

    # 8.1 启动独立心跳线程（与业务轮询解耦，避免业务失败导致心跳丢失）
    heartbeat_interval = config.get('server', {}).get('heartbeat_interval', 30)
    heartbeat_thread = HeartbeatThread(http_client, interval=heartbeat_interval)
    heartbeat_thread.start()
    logger.info(f"独立心跳线程已启动，间隔 {heartbeat_interval} 秒")

    # 9. 显示主界面
    display.show_main_screen(fcc_id=fcc_id, server_url=server_url, connected=False)

    # 提醒状态
    reminder_state = ReminderState()

    # LED 心跳与服务器状态检查
    last_status_check = 0
    last_button_check = 0
    last_time_update = 0
    server_connected = False
    # 按钮 A 长按阈值（秒），超过则触发 AI 问答；可由配置 long_press_sec 覆盖
    long_press_sec = float(reminder_cfg.get('long_press_sec', 1.5))
    # 按钮控制器：封装按钮 A/B 边沿与长按检测（行为与原内联逻辑一致）
    button_controller = ButtonController(long_press_sec=long_press_sec)

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
                now, poller, reminder_state, buzzer, display, snooze_minutes, logger, speech
            )

            # ---- 检查按钮（约每 200ms 一次，非阻塞）----
            # 非阻塞防抖：防抖屏蔽期内跳过按钮检测，避免 sleep 阻塞主循环
            if (now.timestamp() - last_button_check) >= 0.2 and now.timestamp() >= button_controller.button_block_until:
                last_button_check = now.timestamp()
                # 按钮 A：短按=确认服药；长按(>阈值)=问 AI 该药注意事项并语音播报
                # 按钮 B：暂不提醒（5分钟后再提醒）
                # 具体动作通过回调注入，保持工作流与硬件解耦、可单测
                def _on_confirm():
                    handle_confirm(reminder_state, buzzer, display, http_client, logger, speech, config)

                def _on_ai():
                    import threading as _th
                    _th.Thread(
                        target=_ask_ai_and_speak,
                        args=(reminder_state, http_client, speech, logger, config),
                        daemon=True,
                    ).start()

                def _on_snooze():
                    handle_snooze(reminder_state, buzzer, display, snooze_minutes, logger)

                button_controller.process(
                    now.timestamp(), button_a, button_b, reminder_state,
                    _on_confirm, _on_ai, _on_snooze,
                )

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
        # 清理资源：依次停止并等待各后台线程退出，释放硬件句柄
        logger.info("正在清理资源...")
        # 优先停止心跳线程，避免下线通知被后续心跳覆盖导致设备重新变为在线
        try:
            heartbeat_thread.stop()
            heartbeat_thread.join(timeout=2)
        except Exception as e:
            logger.warning(f"停止心跳线程失败: {e}")
        # 主动通知服务器下线，避免子女端在心跳超时窗口内看到虚假的"在线"状态
        try:
            if http_client:
                http_client.unregister_device()
        except Exception as e:
            logger.warning(f"发送下线通知失败: {e}")
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


if __name__ == "__main__":
    main()
