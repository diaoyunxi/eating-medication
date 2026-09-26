# -*- coding: utf-8 -*-
"""server 端日期时间工具函数，消除跨文件重复（_hhmm_to_today、_utcnow 等）。"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """返回带时区的当前 UTC 时间"""
    return datetime.now(timezone.utc)


def hhmm_to_today(t, now):
    """将 HH:MM 时间字符串转换为今天对应的 naive datetime，失败返回 None"""
    try:
        from datetime import time as _time
        hh, mm = str(t).strip().split(":")
        return datetime.combine(now.date(), _time(int(hh), int(mm)))
    except Exception:
        return None
