# -*- coding: utf-8 -*-
# utils/logger.py
import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

# 记录已配置的 log_dir，用于检测 log_dir 变化并重建 handler
_configured_log_dir = None


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
    fh = TimedRotatingFileHandler(log_file, when='midnight', backupCount=30, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(ch)
    _configured_log_dir = log_dir
    return logger