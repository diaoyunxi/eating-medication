#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
老人端主程序（行空板 M10）
- 使用 pinpong 库控制硬件（蜂鸣器、光线传感器、LED 指示灯）
- 使用 unihiker GUI 显示界面
- 用药操作（确认服药 / 问AI / 暂缓）全部通过屏幕触摸按钮完成（不再使用物理按键）
- 后台热点 + 配网 Web 服务 + 用药计划轮询
- 主循环：更新时间显示、检查用药提醒

本文件仅负责「装配」与「主循环骨架」：
- 硬件板级访问集中于 hardware.board（Board 初始化幂等、LED 句柄获取）
- 用药提醒工作流（状态机/轮询/触发/确认/暂缓/AI问答）集中于 workflow
- 屏幕触摸按钮由 core.display.Display 提供，动作通过回调注入，业务逻辑与硬件解耦
这样便于在无 M10 硬件环境下进行单元测试。
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
import shutil
from datetime import datetime
from pathlib import Path

# 模块级 logger，供 signal_handler 等非 main() 函数使用
# main() 内部会通过 global logger 覆盖为 setup_logger() 返回的实例
logger = logging.getLogger(__name__)

# 确保以本文件所在目录为工作目录（便于读取 .env / data/）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _in_venv():
    """判断当前解释器是否运行在虚拟环境中（venv/virtualenv 通用判据）"""
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _venv_python():
    """返回应优先使用的 Python 解释器路径。

    与根 main.py 的 _python_executable() 保持一致：
    若项目根目录下存在 .venv 虚拟环境，则优先使用其中的解释器，
    保证「自动安装依赖」与「运行主程序」使用同一环境，避免把依赖
    装进 .venv 却用系统 python 运行导致 ModuleNotFoundError（如 dotenv）。
    """
    project_root = str(Path(BASE_DIR).resolve().parent)
    venv_bin = os.path.join(project_root, ".venv", "bin", "python")
    if os.path.exists(venv_bin):
        return venv_bin
    venv_scripts = os.path.join(project_root, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_scripts):
        return venv_scripts
    return sys.executable


def _ensure_running_in_venv():
    """若仓库根 .venv 已存在但当前未在 venv 中运行，则用 venv 解释器重启自身。

    必须在依赖检测之前执行：否则检测发生在系统 Python 内，看不到已装进
    .venv 的依赖（含 dfrobot_huskylensv2），每次启动都会误报缺失并重复安装。
    """
    py = _venv_python()
    if py != sys.executable and not _in_venv():
        try:
            os.execv(py, [py] + sys.argv)
        except Exception as e:
            print(f"切换到虚拟环境失败，继续以当前解释器运行: {e}")


if os.getcwd() != BASE_DIR:
    os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 仓库根目录（含统一迁移的 updater.py 与 common/ 包）
# 注意：必须 append 而非 insert(0)。仓库根目录下存在统一启动入口 main.py，
# 若把根目录排在 BASE_DIR 之前，本目录的同名模块会被根目录的 main.py 遮蔽。
# 追加到末尾可保证同名模块优先解析到本目录，同时不影响 updater/common 的导入。
PROJECT_ROOT = os.path.dirname(BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

# 工作流与硬件访问层（依赖 elderly_assistant 已在 sys.path 中）
from workflow.reminder import (
    ReminderState,
    MedicationPoller,
    HeartbeatThread,
    check_medication_trigger,
)
from workflow.actions import (
    handle_confirm,
    handle_scan_medication,
    _ask_ai_and_speak,
    _capture_and_upload,
)
# 注：原物理按钮 A/B 已移除，全部改用屏幕触摸按钮（见 display.set_action_handlers）
from hardware.board import init_pinpong_board, get_led

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


def _install_linux_system_deps():
    """最佳努力安装 M10 所需的系统级原生依赖（pip 无法提供的库）。

    - espeak   : pyttsx3 离线 TTS 引擎的后端（缺则语音播报降级）
    - libzbar0 : pyzbar 条码解码所需原生库（缺则 USB 扫码通路降级）
    仅在 Linux 且存在 apt-get 时尝试；失败不影响主流程（对应功能已优雅降级）。
    """
    if os.name != "posix" or shutil.which("apt-get") is None:
        return
    deps = ["espeak", "libzbar0", "mbrola", "mbrola-cn1", "mpg123"]
    try:
        print(f"正在尝试安装系统依赖（需 root/网络）: {', '.join(deps)}")
        subprocess.run(["apt-get", "update"], capture_output=True, text=True, timeout=300)
        subprocess.run(["apt-get", "install", "-y"] + deps,
                       capture_output=True, text=True, timeout=600)
        logger.info("已尝试安装系统依赖: " + ", ".join(deps))
    except Exception as e:
        logger.warning(f"系统依赖安装失败（已忽略，相关功能降级）: {e}")


def check_and_install_dependencies():
    """检查关键依赖是否已安装，若缺失则调用公共安装脚本 common/install.py（含 huskylens）。"""
    required_modules = [
        ('dotenv', 'python-dotenv'),
        ('requests', 'requests'),
        ('pyttsx3', 'pyttsx3'),
        ('pyzbar', 'pyzbar'),
        ('edge_tts', 'edge-tts'),
        # HuskyLens 驱动为 PyPI 未发布模块，缺失时同样触发 common/install.py --huskylens
        # 安装，保证默认（auto 优先 HuskyLens）扫码通路可用
        ('dfrobot_huskylensv2', 'dfrobot-huskylensv2'),
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
                # pyzbar / pyttsx3 依赖系统原生库（libzbar0 / espeak），pip 安装后
                # 再最佳努力补装系统级依赖，避免运行时 ImportError / TTS 初始化失败
                _install_linux_system_deps()
                # --target 显式指定为本目录（BASE_DIR）：dfrobot_huskylensv2 是
                # PyPI 未发布的单文件模块，安装脚本默认落地目录虽同为
                # elderly_assistant/，但显式传参可避免安装进程与主程序
                # 导入路径不一致导致「装了却仍报缺失」
                result = subprocess.run(
                    [_venv_python(), root_install, req_path,
                     "--huskylens", "--target", BASE_DIR],
                    capture_output=False, text=True, cwd=project_root,
                )
                if result.returncode != 0:
                    print("依赖安装可能未完全成功，尝试继续运行...")
                else:
                    print("依赖安装完成，正在重新启动老人端...")
                    py = _venv_python()
                    os.execv(py, [py] + sys.argv)
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

    # 依赖检测必须在虚拟环境内进行：先确保当前进程已运行于 .venv，
    # 否则系统 Python 看不到 .venv 内已装依赖，每次启动都会误报缺失
    _ensure_running_in_venv()

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

    # 1.1 M10 屏幕依赖 unihiker → tkinter 底层，启动前补全 DISPLAY 环境变量；
    #     SSH / systemd 等无交互会话可能导致该变量缺失，tk.Tk() 在线程内抛出
    #     "no display name and no $DISPLAY environment variable" 异常。
    if os.name == 'posix' and 'DISPLAY' not in os.environ:
        os.environ['DISPLAY'] = ':0'
        logger.info("自动设置环境变量 DISPLAY=:0（M10 默认屏幕）")

    # 2. 创建 GUI 显示界面
    display = Display()

    # 获取设备 ID（网卡 MAC 整数值）
    device_uuid = get_device_id()
    server_url = config.get('server', {}).get('base_url', '')
    logger.info(f"设备 ID: {device_uuid}")
    logger.info(f"服务器地址: {server_url}")

    # 3. 初始化蜂鸣器
    buzzer = Buzzer(config)

    # 3.1 初始化语音播报（TTS，缺失环境静默降级）
    #     传入 config：启用 edge-tts 本地缓存（data/tts_cache + index.json），
    #     并在检测不到播放器时自动安装 mpg123（Linux/M10）。
    speech = None
    try:
        from services.speech import Speech
        speech = Speech(config)
    except Exception as e:
        logger.warning(f"语音播报初始化失败，已降级: {e}")

    # 4. 初始化 HTTP 客户端
    http_client = None
    try:
        http_client = HTTPClient(config)
    except Exception as e:
        logger.error(f"HTTP 客户端初始化失败: {e}")

    # 5. 获取 LED 句柄（屏幕按钮无需物理按键）
    led = get_led()

    # 5.1 初始化药品条码扫描器（HuskyLens 板载解码优先，回退 USB 摄像头本地解码）
    scanner = None
    try:
        from core.barcode import BarcodeScanner
        scanner = BarcodeScanner(config)
        logger.info(f"条码扫描器已就绪，扫码源: {scanner.source}")
    except Exception as e:
        logger.warning(f"条码扫描器初始化失败，扫码功能降级不可用: {e}")

    # 6.x 初始化人脸识别器（二哈 HuskyLens 人脸算法），用于拍照确认前身份核验
    face_recognizer = None
    try:
        from core.face import FaceRecognizer
        face_recognizer = FaceRecognizer(config)
        logger.info("人脸识别器（二哈 HuskyLens）已就绪")
    except Exception as e:
        logger.warning(f"人脸识别器初始化失败，身份核验将降级放行: {e}")

    # 6. 联网检测：已联网则无需启动热点配网（配网仅在离线/首启时通过热点进行）
    # hotspot 尚未实例化, 调用 HotspotManager.is_online() 类方法探测联网状态;
    # 在线则 hotspot 保持 None(不启动 AP), 离线时下方才会实例化 HotspotManager 并开热点
    hotspot = None
    wifi_config_server = None
    online = False
    try:
        online = HotspotManager.is_online()
    except Exception as e:
        logger.warning(f"联网状态检测失败，按离线处理并启动热点: {e}")

    if online:
        logger.info("检测到已联网，跳过热点配网（如需重新配网请离线启动设备）")
    else:
        # 6.1 启动后台热点（线程）
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

    # 8. 启动用药计划轮询线程（默认 20 分钟一次；断网时沿用本地缓存）
    reminder_cfg = config.get('reminder', {})
    poll_interval = reminder_cfg.get('poll_interval', 1200)
    from services.schedule_cache import load_schedules
    poller = MedicationPoller(
        http_client, poll_interval=poll_interval, cache_loader=load_schedules
    )
    poller.start()
    logger.info(f"用药计划轮询线程已启动，间隔 {poll_interval} 秒")

    # 8.1 启动独立心跳线程（与业务轮询解耦，避免业务失败导致心跳丢失）
    heartbeat_interval = config.get('server', {}).get('heartbeat_interval', 30)
    heartbeat_thread = HeartbeatThread(http_client, interval=heartbeat_interval)
    heartbeat_thread.start()
    logger.info(f"独立心跳线程已启动，间隔 {heartbeat_interval} 秒")

    # 8.2 注册屏幕「扫码查药」按钮回调（点击后在后台线程扫码，避免阻塞 GUI）
    scan_timeout = float(config.get('scan', {}).get('timeout_sec', 8.0))

    # 扫码进行中锁：屏蔽重复点击，避免多个扫码线程并发导致误报「未识别」或重复 TTS
    _scan_task_lock = threading.Lock()

    def _on_scan_button():
        if not _scan_task_lock.acquire(False):
            logger.info("已有扫码任务进行中，忽略本次扫码请求")
            return

        def _run_scan():
            try:
                handle_scan_medication(
                    scanner, poller, speech, logger, timeout=scan_timeout
                )
            finally:
                _scan_task_lock.release()

        import threading as _th
        _th.Thread(target=_run_scan, daemon=True).start()

    display.set_scan_handler(_on_scan_button)

    # 8.3 注册提醒界面「确认服药 / 问AI」两个屏幕按钮回调，
    #      替代原物理按键 A/B（老年用户按键不便，全部改为屏幕触摸按钮）
    def _on_confirm():
        # 拍照确认前先做身份核验（严格模式），face_recognizer 为 None 时降级放行
        handle_confirm(reminder_state, buzzer, display, http_client, logger, speech, config, face_recognizer)

    def _on_ai():
        import threading as _th
        _th.Thread(
            target=_ask_ai_and_speak,
            args=(reminder_state, http_client, speech, logger, config),
            daemon=True,
        ).start()

    display.set_action_handlers({
        "confirm": _on_confirm,
        "ask_ai": _on_ai,
    })

    # 9. 显示主界面（含「扫码查药」触摸按钮）
    display.show_main_screen(device_uuid=device_uuid, server_url=server_url, connected=False)

    # 提醒状态
    reminder_state = ReminderState()

    # LED 心跳与服务器状态检查
    last_status_check = 0
    last_time_update = 0
    server_connected = False

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
                display.show_device_uuid(device_uuid)
                # 更新下一个用药提醒
                if not reminder_state.active:
                    nxt = poller.get_next_reminder(now)
                    display.show_next_reminder(nxt)

            # ---- 检查用药提醒触发 ----
            check_medication_trigger(
                now, poller, reminder_state, buzzer, display, logger, speech
            )

            # ---- 本地重复提醒音：提醒触发后每 60 秒老人仍未确认则再次响铃 ----
            if reminder_state.active and reminder_state.triggered_at is not None:
                if (datetime.now() - reminder_state.triggered_at).total_seconds() >= 60:
                    try:
                        buzzer.play_reminder()
                    except Exception:
                        pass
                    reminder_state.triggered_at = datetime.now()

            # 注：原物理按钮 A/B 检测已移除，确认/问AI 均由屏幕触摸按钮触发
            #     （display.set_action_handlers 注入回调，回调解耦合与硬件无关）

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
        # 释放摄像头句柄，避免退出后 USB 设备被占用
        try:
            if scanner:
                scanner.close()
        except Exception as e:
            logger.warning(f"关闭条码扫描器失败: {e}")
        try:
            if wifi_config_server:
                wifi_config_server.stop()
        except Exception as e:
            logger.warning(f"停止配网服务失败: {e}")
        try:
            if hotspot:
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
