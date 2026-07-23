# -*- coding: utf-8 -*-
"""
蜂鸣器服务模块
行空板M10专用：使用 pinpong 库的 buzzer 控制蜂鸣器
"""
import logging
import threading
import time

logger = logging.getLogger("ElderlyAssistant")


class Buzzer:
    """蜂鸣器控制类（基于 pinpong 库的 buzzer）"""

    def __init__(self, config=None):
        # config 可为字典或 None（兼容旧调用）
        self.config = config or {}
        self.buzzer = None
        self._lock = threading.Lock()
        # 是否正在持续提醒（直到确认或暂缓）
        self._reminding = False
        # 提醒线程
        self._reminder_thread = None
        self._init_buzzer()

    def _init_buzzer(self):
        """初始化行空板M10蜂鸣器（使用pinpong库）"""
        try:
            from pinpong.board import Board
            from pinpong.extension.unihiker import buzzer
            Board().begin()
            self.buzzer = buzzer
            logger.info("行空板M10蜂鸣器初始化成功（pinpong buzzer）")
        except ImportError:
            logger.warning("pinpong库未安装，蜂鸣器不可用（非M10环境降级）")
        except Exception as e:
            logger.error(f"蜂鸣器初始化失败: {e}")
            self.buzzer = None

    def play_reminder(self):
        """
        播放用药提醒音乐（持续循环，直到 stop() 被调用）
        在独立线程中循环播放 BA_DING 提示音，不阻塞主循环
        """
        with self._lock:
            if not self.buzzer:
                logger.warning("蜂鸣器未初始化，无法播放提醒")
                return
            if self._reminding:
                # 已经在提醒中，避免重复启动线程
                return
            self._reminding = True

        self._reminder_thread = threading.Thread(
            target=self._reminder_loop, daemon=True
        )
        self._reminder_thread.start()
        logger.info("开始播放用药提醒音乐")

    def _reminder_loop(self):
        """提醒音乐循环（在独立线程中运行）"""
        interval = self.config.get('reminder', {}).get('buzzer_loop_interval', 3) \
            if isinstance(self.config, dict) else 3
        try:
            while self._reminding:
                if not self.buzzer:
                    break
                try:
                    # 播放提示音一次
                    self.buzzer.play(self.buzzer.BA_DING, self.buzzer.Once)
                except Exception as e:
                    logger.error(f"播放提醒音失败: {e}")
                # 等待间隔（每秒检查一次停止标志，便于快速响应）
                for _ in range(max(1, int(interval))):
                    if not self._reminding:
                        break
                    time.sleep(1)
        except Exception as e:
            logger.error(f"提醒循环异常: {e}")
        finally:
            logger.info("提醒音乐循环结束")

    def stop(self):
        """停止蜂鸣器（停止持续提醒）"""
        with self._lock:
            self._reminding = False
        # 先 join 提醒线程再停止蜂鸣器，避免线程竞态
        if self._reminder_thread and self._reminder_thread.is_alive():
            self._reminder_thread.join(timeout=2)
        if self.buzzer:
            try:
                self.buzzer.stop()
            except Exception as e:
                logger.error(f"停止蜂鸣器失败: {e}")
        logger.info("蜂鸣器已停止")

    def play_success(self):
        """播放成功提示音（单次）"""
        if not self.buzzer:
            logger.warning("蜂鸣器未初始化，无法播放成功提示音")
            return
        try:
            # 使用 JUMP_UP 作为成功提示音
            self.buzzer.play(self.buzzer.JUMP_UP, self.buzzer.Once)
            logger.info("播放成功提示音")
        except Exception as e:
            logger.error(f"播放成功提示音失败: {e}")

    def beep(self, volume=None):
        """蜂鸣（play_reminder 的别名，兼容旧调用）"""
        # volume 参数仅为兼容旧调用 signature，当前 play_reminder 不接受音量参数
        self.play_reminder()

    def is_reminding(self):
        """是否正在持续提醒"""
        return self._reminding

    def __del__(self):
        """清理资源"""
        try:
            self.stop()
        except Exception:
            pass
