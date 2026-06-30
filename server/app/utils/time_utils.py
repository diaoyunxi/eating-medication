# -*- coding: utf-8 -*-
from datetime import datetime, time, date
from typing import Optional, Union

def now() -> datetime:
    """获取当前 UTC 时间"""
    return datetime.utcnow()

def format_datetime(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """格式化日期时间"""
    if dt is None:
        return ""
    return dt.strftime(fmt)

def parse_datetime(dt_str: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> Optional[datetime]:
    """解析日期时间字符串"""
    try:
        return datetime.strptime(dt_str, fmt)
    except (ValueError, TypeError):
        return None

def get_today_start() -> datetime:
    """获取今日开始时间（00:00:00）"""
    today_date = datetime.utcnow().date()
    return datetime.combine(today_date, time.min)

def get_today_end() -> datetime:
    """获取今日结束时间（23:59:59）"""
    today_date = datetime.utcnow().date()
    return datetime.combine(today_date, time.max)

def get_date_range(days: int = 7) -> tuple:
    """
    获取日期范围（最近 N 天）
    返回 (start_date, end_date)
    """
    from datetime import timedelta
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    return start_date, end_date

def is_same_day(dt1: datetime, dt2: datetime) -> bool:
    """判断两个 datetime 是否是同一天"""
    return dt1.date() == dt2.date()

def parse_time_string(time_str: str) -> Optional[time]:
    """
    解析时间字符串（如 "08:00"）为 time 对象
    """
    try:
        parts = time_str.split(":")
        if len(parts) == 2:
            return time(int(parts[0]), int(parts[1]), 0)
        elif len(parts) == 3:
            return time(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        pass
    return None

def is_time_passed(scheduled_time: datetime, buffer_minutes: int = 30) -> bool:
    """
    判断计划时间是否已经过去（可设置缓冲分钟数）
    如果计划时间 + 缓冲分钟 < 当前时间，则认为已过时
    """
    from datetime import timedelta
    threshold = scheduled_time + timedelta(minutes=buffer_minutes)
    return datetime.utcnow() > threshold