# -*- coding: utf-8 -*-
"""板级硬件访问（行空板 M10 / pinpong）。

集中封装 pinpong Board 初始化与按钮/LED/光线传感器句柄获取，供 main /
services.buzzer / services.device_id 复用，避免各处重复调用 Board().begin()
造成重复初始化风险。所有 pinpong 依赖均为懒加载，非 M10 环境（无 pinpong）
下全部安全降级为 None / False。

本模块仅依赖标准库，不反向依赖任何业务代码，可被单元测试以 Fake 替身注入。
"""
import logging
import threading

logger = logging.getLogger("ElderlyAssistant")

# Board 初始化幂等标志：多次 ensure_board() 仅首次真正执行 begin()
_board_initialized = False
_board_lock = threading.Lock()


def init_board():
    """幂等初始化 pinpong Board；多次调用安全（仅首次真正 begin）。"""
    global _board_initialized
    with _board_lock:
        if _board_initialized:
            return True
        try:
            from pinpong.board import Board
            Board().begin()
            _board_initialized = True
            return True
        except ImportError:
            return False
        except Exception:
            return False


def ensure_board():
    """确保 Board 已初始化（供 buzzer / device_id 等复用，避免重复 begin）。"""
    return _board_initialized or init_board()


def init_pinpong_board():
    """初始化 pinpong Board（供主程序调用并汇报状态）。"""
    if ensure_board():
        print("[主程序] pinpong Board 初始化成功")
        return True
    print("[警告] pinpong 库未安装（非 M10 环境降级）")
    return False


def get_led():
    """获取 LED 句柄（P25），非 M10 环境返回 None。"""
    try:
        from pinpong.board import Pin
        led = Pin(Pin.P25, Pin.OUT)
        return led
    except ImportError:
        return None
    except Exception:
        return None


def get_light_sensor():
    """获取光线传感器句柄，非 M10 环境返回 None（预留扩展接口）。"""
    try:
        from pinpong.extension.unihiker import light
        return light
    except ImportError:
        return None
    except Exception:
        return None
