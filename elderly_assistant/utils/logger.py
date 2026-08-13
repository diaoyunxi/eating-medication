# -*- coding: utf-8 -*-
# utils/logger.py
import logging
import os
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

# 记录已配置的 log_dir，用于检测 log_dir 变化并重建 handler
_configured_log_dir = None

# Windows 终端默认不解析 ANSI 转义码；借用 colorama 在 Windows 上启用 VT100 颜色。
# 非 Windows / 已支持 ANSI 的终端（如 Git Bash、Linux 终端）下 colorama 自动退化为空操作。
try:
    import colorama
    colorama.init()
except Exception:
    colorama = None

# ANSI 转义码：按日志级别着色，配色对齐 uvicorn 风格（INFO 绿 / WARNING 黄 / ERROR 红），
# 避免之前将主力 INFO 设为青色在部分终端被误看成"蓝色"。
_ANSI_RESET = "\033[0m"
_ANSI_COLORS = {
    logging.DEBUG: "\033[34m",            # 蓝（调试日志少，用作区分）
    logging.INFO: "\033[32m",             # 绿（主力日志）
    logging.WARNING: "\033[33m",          # 黄
    logging.ERROR: "\033[31m",            # 红
    logging.CRITICAL: "\033[1m\033[31m",   # 粗红
}


class _ColoredFormatter(logging.Formatter):
    """按日志级别着色；非 tty（文件/管道）时自动退化为纯文本，避免产生乱码转义码。"""

    def __init__(self, fmt, use_color=True):
        super().__init__(fmt)
        self.use_color = use_color

    def format(self, record):
        text = super().format(record)
        if not self.use_color:
            return text
        code = _ANSI_COLORS.get(record.levelno)
        if not code:
            return text
        return f"{code}{text}{_ANSI_RESET}"


def setup_logger(log_dir="logs"):
    """
    配置并返回 ElderlyAssistant logger。
    - 仅由 main.py 调用一次以配置 handler
    - 若已配置但 log_dir 不同，清除旧 handler 重建
    - 使用 TimedRotatingFileHandler 实现跨日轮转，保留 30 天
    - propagate=False，避免日志向 root logger 重复传播
    """
    global _configured_log_dir
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("ElderlyAssistant")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # log_dir 相同且已有 handler：直接返回，避免重复添加
    if logger.handlers and _configured_log_dir == log_dir:
        return logger

    # log_dir 变化：清除旧 handler 后重建
    if logger.handlers:
        for h in list(logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            logger.removeHandler(h)

    log_file = os.path.join(log_dir, f"assistant_{datetime.now().strftime('%Y%m%d')}.log")
    # TimedRotatingFileHandler：跨日自动轮转，保留最近 30 天日志
    # 文件始终保持纯文本（不上色），便于阅读与检索
    fh = TimedRotatingFileHandler(log_file, when='midnight', backupCount=30, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    # 控制台仅在支持颜色的终端（tty/pty）上色，重定向到文件或管道时退化为纯文本
    console_supports_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    ch.setFormatter(_ColoredFormatter(fmt, use_color=console_supports_color))
    fh.setFormatter(logging.Formatter(fmt))
    logger.addHandler(fh)
    logger.addHandler(ch)
    _configured_log_dir = log_dir
    return logger