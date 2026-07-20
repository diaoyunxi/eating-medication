# -*- coding: utf-8 -*-
"""
简单的内存限流工具（基于调用方标识，每分钟固定次数）。
用于 AI 公开端点（C5.6/M21）与注册端点（L8）等场景。
注意：仅适用于单进程部署，多进程需改用 Redis 等共享存储。
"""
import time
from collections import defaultdict
from typing import Dict, List

# 内存存储：key -> [时间戳列表]
_bucket: Dict[str, List[float]] = defaultdict(list)


def check_rate_limit(key: str, max_calls: int, window_seconds: int = 60) -> bool:
    """
    检查是否超出限流。
    返回 True 表示允许调用，False 表示已被限流。

    :param key: 限流键（如客户端 IP）
    :param max_calls: 时间窗口内允许的最大调用次数
    :param window_seconds: 时间窗口（秒），默认 60
    """
    now = time.time()
    cutoff = now - window_seconds
    # 清理过期记录
    recent = [t for t in _bucket[key] if t > cutoff]
    # Bug4 修复：当 recent 为空时从 _bucket 中删除该 key，
    # 避免 _bucket 无限增长（每个新 IP 或 key 都会留下空列表条目永不清理）。
    if not recent:
        _bucket.pop(key, None)
        recent = [now]
        # 空列表直接放行，但需记录本次调用
        _bucket[key] = recent
        return True
    _bucket[key] = recent
    if len(recent) >= max_calls:
        return False
    _bucket[key].append(now)
    return True
