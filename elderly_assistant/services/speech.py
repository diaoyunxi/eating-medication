# -*- coding: utf-8 -*-
"""语音播报服务（老人端 M10）。

TTS 引擎优先级：
1. edge-tts（联网优先）：中文神经语音，音质明显优于本地 espeak；
   产出 MP3 后由系统播放器（mpg123/ffplay/mpv/play）播放，无网或请求失败时降级。
2. pyttsx3（离线兜底）：本地 espeak 引擎，优先选用 mbrola-cn1 中文语音包
   （需 `apt install mbrola mbrola-cn1`，由 main.py 自动安装）；缺失则退回默认语音。

两个引擎均在初始化期尝试加载，运行时按优先级选择；任一失败自动切换到另一引擎，
全部不可用时禁用语音（不影响主流程）。
"""
import asyncio
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from utils.logger import setup_logger


# edge-tts 使用的中文神经语音
EDGE_TTS_VOICE = "zh-CN-XiaoxiaoNeural"
# MP3 播放器探测顺序（按优先级）；mpg123 由 main.py 自动 apt 安装
_PLAYER_ARGS = {
    "mpg123": ["-q"],
    "ffplay": ["-nodisp", "-autoexit"],
    "mpv": ["--no-terminal", "--force-window=no"],
    "play": [],
}


class Speech:
    def __init__(self, config=None):
        self.logger = setup_logger()
        # speech 配置段为幽灵字段（历史遗留，从未生效），统一删除，此处不读取
        self.config = {}
        self._speak_queue = queue.Queue(maxsize=20)  # 有界队列，避免无界增长
        self._stop_event = threading.Event()
        self._edge_tts = None
        self._edge_available = False
        self._pyttsx_engine = None
        # 播报串行锁：_speak 可能被多个调用方经队列串行触发，但回调/线程边界
        # 不保证原子；加锁避免 edge-tts(asyncio.run) 与 pyttsx3(runAndWait)
        # 在同一播放线程内交错导致引擎状态混乱或某条播报被吞。
        self._speak_lock = threading.Lock()
        # 最近一次播报失败原因，便于外部诊断（如「识别到但没播报」排查）
        self.last_error = None

        self._init_engines()

        if self._edge_available or self._pyttsx_engine:
            self._worker_thread = threading.Thread(target=self._speak_worker, daemon=True)
            self._worker_thread.start()
        else:
            self.logger.warning("语音引擎全部不可用，语音播报已禁用")

    def _init_engines(self):
        """初始化两套引擎：edge-tts（联网优先）+ pyttsx3（离线兜底）。"""
        # 1. edge-tts：仅检测模块是否可导入（联网在播报时实时校验）
        try:
            import edge_tts
            self._edge_tts = edge_tts
            self._edge_available = True
            self.logger.info("edge-tts 可用（联网时优先用于语音播报）")
        except Exception as e:
            self._edge_available = False
            self.logger.info(f"edge-tts 不可用，将使用 pyttsx3 离线播报: {e}")

        # 2. pyttsx3 离线兜底（优先 mbrola-cn1 中文语音）
        # 注意：语音选择（setProperty('voice')）在某些后端（如 Windows SAPI5
        # 或 espeak-mbrola 未正确安装）可能抛 SetVoiceByName 错误（-1），
        # 该失败只影响"选哪个语音"，不应连累引擎本身初始化。因此将
        # init / volume / rate 与 语音选择 分两段 try，确保默认语音可用时
        # 离线引擎仍可被使用（见 issue #42）。
        try:
            import pyttsx3
            eng = pyttsx3.init()
            eng.setProperty('volume', 0.9)
            eng.setProperty('rate', 150)
            self._pyttsx_engine = eng
            self.logger.info("pyttsx3 TTS 引擎初始化成功（离线兜底）")
        except Exception as e:
            self._pyttsx_engine = None
            self.logger.warning(f"pyttsx3 初始化失败: {e}")
            return

        # 引擎已就绪，再尝试优选中文语音；失败仅退回默认语音，不中断服务
        try:
            self._select_mbrola_voice(eng)
        except Exception as e:
            self.logger.warning(f"pyttsx3 语音选择失败（使用默认语音）: {e}")

    def _select_mbrola_voice(self, eng):
        """在 pyttsx3 语音列表中优先选用 mbrola 中文语音（mbrola-cn1）。

        espeak 启用 mbrola 后，语音 id 形如 `mbrola/cn1`；缺失或
        setProperty('voice') 在部分后端失败（如 issue #42 的 SetVoiceByName
        -1）时退回默认语音，不向上抛出异常，保证引擎仍可用。
        """
        voices = eng.getProperty('voices') or []
        for v in voices:
            vid = (getattr(v, 'id', '') or '').lower()
            if 'mbrola' in vid and 'cn' in vid:
                try:
                    eng.setProperty('voice', v.id)
                    self.logger.info(f"已选用 mbrola 中文语音: {vid}")
                except Exception as e:
                    self.logger.warning(f"设置 mbrola 语音失败（使用默认）: {e}")
                return
        self.logger.info("未找到 mbrola-cn1 语音，pyttsx3 使用默认语音")

    def _speak_worker(self):
        while not self._stop_event.is_set():
            try:
                text = self._speak_queue.get(timeout=1)
                if text is None:
                    break
                self._speak(text)
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"语音 worker 异常: {e}")
                time.sleep(1)

    def _speak(self, text):
        """按优先级播报：先 edge-tts，失败或无网则 pyttsx3。

        全程加锁，避免两条播报（如「请把药盒对准摄像头」与扫码识别结果）
        在同一 worker 线程内对 TTS 引擎的交替调用相互干扰，导致识别结果
        被静默吞掉（表现为「识别到但没播报」）。任一路失败都会记录到
        ``last_error`` 并打印明确日志，不再静默丢弃。
        """
        with self._speak_lock:
            self.last_error = None
            if self._edge_available:
                try:
                    self._speak_edge(text)
                    return
                except Exception as e:
                    self.last_error = f"edge-tts: {e}"
                    self.logger.warning(f"edge-tts 播报失败，转 pyttsx3: {e}")
            if self._pyttsx_engine:
                try:
                    self._pyttsx_engine.say(text)
                    self._pyttsx_engine.runAndWait()
                    return
                except Exception as e:
                    self.last_error = f"pyttsx3: {e}"
                    self.logger.error(f"pyttsx3 播报失败: {e}")
                    try:
                        self._init_engines()
                    except Exception:
                        pass
            else:
                # 两个引擎均不可用/失败：明确记录，便于排查为何无声音
                self.last_error = "无可用语音引擎"
                self.logger.error(f"语音播报失败（两路引擎均不可用）: {text}")

    def _speak_edge(self, text):
        """使用 edge-tts 合成并播放（需联网）。"""
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            communicate = self._edge_tts.Communicate(text, voice=EDGE_TTS_VOICE)
            asyncio.run(communicate.save(tmp_path))
            self._play_mp3(tmp_path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _play_mp3(self, path):
        """用系统中可用的播放器播放 MP3；无可用播放器则抛错触发 pyttsx3 兜底。"""
        for player, extra in _PLAYER_ARGS.items():
            exe = shutil.which(player)
            if exe:
                try:
                    subprocess.run(
                        [exe] + extra + [path],
                        capture_output=True, text=True, timeout=30,
                    )
                    return
                except Exception as e:
                    self.logger.warning(f"播放器 {player} 执行失败: {e}")
                    continue
        raise RuntimeError("无可用音频播放器（需 mpg123/ffplay/mpv/play 之一）")

    def speak(self, text, volume=None):
        if not (self._edge_available or self._pyttsx_engine):
            # 两路引擎均不可用：记录诊断信息（不再静默），便于排查
            # 「识别到但没播报」等问题；扫码等场景可据此回退到屏幕显示。
            self.last_error = "无可用语音引擎"
            self.logger.warning("语音合成不可用（已记录 last_error）")
            return
        # 队列有界，满时丢弃并告警，避免无界增长导致内存溢出
        try:
            self._speak_queue.put_nowait(text)
        except queue.Full:
            self.last_error = "语音队列已满"
            self.logger.warning("语音队列已满，丢弃")

    def stop(self):
        # 先 put 哨兵并 join worker，再置 None，避免竞态
        self._stop_event.set()
        try:
            self._speak_queue.put_nowait(None)
        except queue.Full:
            pass

        if hasattr(self, '_worker_thread') and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2)

        if self._pyttsx_engine:
            try:
                self._pyttsx_engine.stop()
            except Exception:
                pass
            self._pyttsx_engine = None
        self._edge_tts = None
        self._edge_available = False

        self.logger.info("语音服务已停止")
