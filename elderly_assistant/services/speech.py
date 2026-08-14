# -*- coding: utf-8 -*-
"""语音播报服务（离线优先 + edge-tts 在线合成，带本地缓存与播放器自动安装）

设计要点：
1. 离线优先：pyttsx3 可用时优先（离线、零延迟、无外部依赖）；不可用才走 edge-tts。
2. edge-tts 本地缓存：每次合成结果落盘到缓存目录，并以 index.json 建立索引
   （key=文本+音色+语速 的 sha256）。再次播报相同内容时，先查索引命中则直接播放
   本地文件，避免重复联网合成，降低延迟与流量。
3. 播放器自动安装：探测 mpg123/ffplay/mpv/play 均不存在时，Linux（Debian/M10）
   自动 apt 安装 mpg123；Windows 则给出明确提示（设备端为 Debian，此处仅告警）。
4. 全场景容错：edge-tts 异常时自动降级到 pyttsx3；pyttsx3 不可用时静默跳过。
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess

from pathlib import Path

logger = logging.getLogger("ElderlyAssistant")

try:
    import edge_tts
except Exception as e:  # pragma: no cover - 依赖缺失时静态通过
    logger.warning(f"edge_tts 导入失败: {e}")
    edge_tts = None


class Speech:
    """语音播报封装。"""

    def __init__(self, config=None):
        # 兼容无配置构造（测试 / 独立调用）
        self._online = False
        self._tts = None
        self._voice = "zh-CN-XiaoxiaoNeural"
        self._rate = "+0%"
        self._player_precedence = ["mpg123", "ffplay", "mpv", "play"]
        self._cache_dir = None
        self._index_path = None
        self._player = None  # 探测到的可执行播放器（绝对路径或命令名）

        if config:
            audio_cfg = config.get("audio", {}) if isinstance(config, dict) else {}
            self._voice = audio_cfg.get("edge_tts_voice", self._voice)
            self._rate = audio_cfg.get("edge_tts_rate", self._rate)
            prec = audio_cfg.get("player_precedence", self._player_precedence)
            if isinstance(prec, str):
                prec = [p.strip() for p in prec.split(",") if p.strip()]
            if prec:
                self._player_precedence = prec
            cache_dir = audio_cfg.get("tts_cache_dir", "data/tts_cache")
            self._init_cache_dir(cache_dir)

        self._init_tts()
        # 播放器探测 / 安装（仅在 edge-tts 启用时有意义，但提前探测无副作用）
        self._ensure_player()

    # ------------------------------------------------------------------ #
    # 缓存目录与索引
    # ------------------------------------------------------------------ #
    def _init_cache_dir(self, cache_dir):
        """初始化 edge-tts 缓存目录与索引路径。

        :param cache_dir: 相对 BASE_DIR 的相对路径或绝对路径
        """
        base = Path(__file__).resolve().parent.parent  # elderly_assistant/
        path = Path(cache_dir)
        if not path.is_absolute():
            path = base / cache_dir
        self._cache_dir = path
        self._index_path = self._cache_dir / "index.json"
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # 目录不可写时降级：缓存失效但不影响播报
            logger.warning(f"创建 TTS 缓存目录失败，将不使用本地缓存: {e}")
            self._cache_dir = None
            self._index_path = None

    def _index_load(self):
        """读取缓存索引；损坏或不存在返回空 dict（容错）。"""
        if not self._index_path:
            return {}
        try:
            if self._index_path.exists():
                with open(self._index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f"读取 TTS 缓存索引失败，重建索引: {e}")
        return {}

    def _index_save(self, index):
        """原子写入缓存索引，避免并发/异常损坏。"""
        if not self._index_path:
            return
        tmp = self._index_path.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
            tmp.replace(self._index_path)
        except Exception as e:
            logger.warning(f"写入 TTS 缓存索引失败: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    @staticmethod
    def _cache_key(text, voice, rate):
        """生成缓存键：文本 + 音色 + 语速 的稳定哈希（sha256 前 16 位）。"""
        raw = f"{text}|{voice}|{rate}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _index_lookup(self, key):
        """查询缓存索引，返回存在的本地文件路径；文件缺失则返回 None。"""
        if not self._cache_dir:
            return None
        index = self._index_load()
        entry = index.get(key)
        if not entry:
            return None
        fp = self._cache_dir / entry.get("file", "")
        if fp.exists() and fp.is_file():
            return str(fp)
        # 索引指向文件已丢失：清理无效条目
        logger.warning(f"TTS 缓存文件缺失，清理索引条目: {key}")
        index.pop(key, None)
        self._index_save(index)
        return None

    def _index_register(self, key, file_path):
        """登记一条缓存记录（文件落盘后调用）。"""
        if not self._cache_dir:
            return
        index = self._index_load()
        index[key] = {
            "file": Path(file_path).name,
            "voice": self._voice,
            "rate": self._rate,
        }
        self._index_save(index)

    # ------------------------------------------------------------------ #
    # 播放器探测与自动安装
    # ------------------------------------------------------------------ #
    def _find_player(self):
        """按优先级探测可用播放器，返回命令名 / 绝对路径；均无返回 None。"""
        for name in self._player_precedence:
            exe = shutil.which(name)
            if exe:
                return exe
        return None

    def _install_player(self):
        """检测不到播放器时自动安装。

        - Linux（Debian/M10）：apt 安装 mpg123（优先），失败回退 ffmpeg（提供 ffplay）。
        - Windows：设备端为 Debian，此处仅打印明确提示并要求手动安装 mpg123。
        :return: 安装后探测到的播放器路径，失败返回 None
        """
        if os.name == "nt":
            logger.error(
                "未检测到音频播放器。Windows 需手动安装 mpg123 或 ffmpeg 并加入 PATH；"
                "设备端 M10（Debian）无需此操作。"
            )
            return None
        # Linux：尝试安装 mpg123（最轻量、无 X 依赖）
        try:
            logger.warning("未检测到播放器，尝试自动安装 mpg123 ...")
            subprocess.run(
                "apt-get update -qq && apt-get install -y mpg123",
                shell=True,
                check=False,
                timeout=300,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if self._find_player() is None:
                # mpg123 安装失败，尝试 ffmpeg（提供 ffplay）
                logger.warning("mpg123 安装失败，尝试安装 ffmpeg ...")
                subprocess.run(
                    "apt-get install -y ffmpeg",
                    shell=True,
                    check=False,
                    timeout=600,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception as e:
            logger.warning(f"自动安装播放器异常: {e}")
        return self._find_player()

    def _ensure_player(self):
        """确保存在可用播放器：先探测，失败则尝试安装。"""
        self._player = self._find_player()
        if self._player is None:
            self._player = self._install_player()
            if self._player is None:
                logger.warning("无可用音频播放器，edge-tts 音频将无法播放（将降级 pyttsx3）。")

    # ------------------------------------------------------------------ #
    # TTS 引擎初始化
    # ------------------------------------------------------------------ #
    def _init_tts(self):
        try:
            import pyttsx3

            self._tts = pyttsx3.init()
            self._tts.setProperty("rate", 150)
            self._tts.setProperty("volume", 0.9)
            self._online = False
            return
        except Exception as e:
            logger.warning(f"离线语音不可用，回退 edge-tts: {e}")
        if edge_tts is None:
            self._online = False
            return
        self._online = True

    # ------------------------------------------------------------------ #
    # 播放
    # ------------------------------------------------------------------ #
    def _play_file(self, file_path):
        """用探测到的播放器播放本地音频文件。"""
        if self._player is None:
            logger.warning("无可用播放器，跳过音频播放。")
            return
        try:
            subprocess.run(
                [self._player, file_path],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
        except Exception as e:
            logger.warning(f"播放音频失败: {e}")

    # ------------------------------------------------------------------ #
    # 合成 / 播报
    # ------------------------------------------------------------------ #
    def _speak_edge(self, text):
        """edge-tts 在线合成（带本地缓存命中逻辑）。"""
        if edge_tts is None:
            logger.warning("edge_tts 未安装，无法在线合成。")
            return

        key = self._cache_key(text, self._voice, self._rate)
        cached = self._index_lookup(key)
        if cached:
            logger.info(f"TTS 缓存命中，直接播放本地文件: {cached}")
            self._play_file(cached)
            return

        tmp = None
        try:
            # 落盘目标：缓存目录内以 cache key 命名的 mp3（便于索引复用）
            if self._cache_dir:
                out_file = str(self._cache_dir / f"{key}.mp3")
            else:
                import tempfile

                fd, out_file = tempfile.mkstemp(suffix=".mp3")
                os.close(fd)
                tmp = out_file

            communicate = edge_tts.Communicate(text, self._voice, rate=self._rate)
            import asyncio

            asyncio.run(communicate.save(out_file))

            if self._cache_dir:
                self._index_register(key, out_file)
                logger.info(f"TTS 合成完成并缓存: {out_file}")
            self._play_file(out_file)
        except Exception as e:
            logger.warning(f"edge-tts 合成失败: {e}")
            # 异常时尝试离线兜底
            if self._tts:
                try:
                    self._tts.say(text)
                    self._tts.runAndWait()
                except Exception as e2:
                    logger.warning(f"离线兜底播报也失败: {e2}")
        finally:
            # 仅临时文件（未启用缓存）在播放后清理
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass

    def speak(self, text):
        """播报文本：离线优先，失败回退 edge-tts 在线合成。"""
        if not isinstance(text, str) or not text.strip():
            logger.warning("播报文本为空，已跳过。")
            return
        if self._online:
            self._speak_edge(text)
        elif self._tts:
            try:
                self._tts.say(text)
                self._tts.runAndWait()
                logger.info(f"离线播报: {text}")
            except Exception as e:
                logger.warning(f"离线播报失败，尝试 edge-tts: {e}")
                self._speak_edge(text)
        else:
            logger.warning("语音引擎完全不可用，无法播报。")

    @property
    def mode(self):
        """当前语音模式：'offline' / 'online'。"""
        return "online" if self._online else "offline"
