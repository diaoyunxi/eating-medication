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


# ===== 板载功放静音控制（修复 #34：语音播报电流声）=====
# 行空板 M10 的板载音频功放由 GPIO 使能引脚控制（P20，高电平=输出、低电平=静音）。
# 程序未播报时该引脚默认悬空/高电平，功放持续通电，会在静默期产生明显
# 「电流声」（直流偏置/开关噪声）。修复方式：默认将功放置为静音，仅在真正
# 播放音频（TTS / 蜂鸣器）时临时解除静音，播放结束后立即重新静音。
_AUDIO_AMP_PIN = 20  # 行空板 M10 音频功放使能引脚（Pin.P20）


class AudioAmpMute:
    """板载功放静音控制器（上下文管理器）。

    非 M10 环境（无 pinpong）自动降级为「空操作」，不影响主流程与其它平台运行。
    通过引用计数支持 TTS / 蜂鸣器并发调用：最后一个使用者退出时才重新静音。
    """

    def __init__(self):
        self._pin = None
        self._available = False
        self._lock = threading.Lock()
        self._refcount = 0
        self._initialized = False

    def _ensure_init(self):
        # CodeRabbit 修复：用实例锁同步初始化。先获取锁再检查/设置 _initialized，
        # 并持锁直至 Pin 创建、默认静音、可用性设置完成；这样并发的 TTS 与蜂鸣器
        # 调用方不会观察到部分初始化的实例，也不会因竞态跳过引用计数更新。
        with self._lock:
            if self._initialized:
                return
            self._initialized = True
            try:
                from pinpong.board import Pin
                self._pin = Pin(getattr(Pin, f"P{_AUDIO_AMP_PIN}"), Pin.OUT)
                # 上电即静音（低电平），避免待机电流声。
                self._pin.write_digital(0)
                self._available = True
                logger.info("板载功放静音控制已启用（引脚 P%d）", _AUDIO_AMP_PIN)
            except ImportError:
                logger.info("pinpong 未安装，功放静音控制降级为无操作（非 M10 环境）")
            except Exception as e:
                logger.warning(f"功放静音控制初始化失败，降级为无操作: {e}")

    def unmute(self):
        """解除静音（开始播放音频前调用）。引用计数，可重入。"""
        self._ensure_init()
        if not self._available:
            return
        with self._lock:
            if self._refcount == 0:
                try:
                    self._pin.write_digital(1)
                except Exception as e:
                    logger.warning(f"功放解除静音失败: {e}")
            self._refcount += 1

    def mute(self):
        """恢复静音（播放音频结束后调用）。与 unmute 配对，引用归零才真正静音。"""
        self._ensure_init()
        if not self._available:
            return
        with self._lock:
            self._refcount = max(0, self._refcount - 1)
            if self._refcount == 0:
                try:
                    self._pin.write_digital(0)
                except Exception as e:
                    logger.warning(f"功放恢复静音失败: {e}")

    def force_mute(self):
        """强制静音（忽略引用计数），用于初始化/退出时兜底。"""
        self._ensure_init()
        if not self._available:
            return
        with self._lock:
            self._refcount = 0
            try:
                self._pin.write_digital(0)
            except Exception as e:
                logger.warning(f"功放强制静音失败: {e}")

    def __enter__(self):
        self.unmute()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.mute()
        return False


# 进程级单例：保证功放引脚只初始化一次，且 TTS 与蜂鸣器共享同一引用计数。
_audio_amp = None
_audio_amp_lock = threading.Lock()


def get_audio_amp():
    """获取（懒加载、线程安全）板载功放静音控制器单例。"""
    global _audio_amp
    if _audio_amp is None:
        with _audio_amp_lock:
            if _audio_amp is None:
                _audio_amp = AudioAmpMute()
    return _audio_amp


def get_light_sensor():
    """获取光线传感器句柄，非 M10 环境返回 None（预留扩展接口）。"""
    try:
        from pinpong.extension.unihiker import light
        return light
    except ImportError:
        return None
    except Exception:
        return None
