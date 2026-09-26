# -*- coding: utf-8 -*-
"""用药计划本地缓存（离线回退）。

老人端优先从服务器拉取用药计划；网络不可用时回退读取本地缓存，保证断网
期间仍能按既有计划按时提醒、扫码查询药品用量。

缓存文件默认为 ``elderly_assistant/data/schedules.json``：
- 写入采用「临时文件 + 原子替换」，避免掉电/进程中断产生半截 JSON；
- 读取时做结构校验，脏数据一律视为无缓存，不让异常扩散到主流程；
- 读写均加进程内锁，避免轮询线程与主线程并发读写同一文件。
"""

import json
import logging
import os
import tempfile
import threading

logger = logging.getLogger("ElderlyAssistant")

# 缓存文件路径：elderly_assistant/data/schedules.json
CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "schedules.json"
)

_lock = threading.Lock()


def _normalize(schedules):
    """校验并规范化计划列表：仅保留 dict 元素，非列表输入返回 None。"""
    if not isinstance(schedules, list):
        return None
    return [item for item in schedules if isinstance(item, dict)]


def load_schedules(path=None):
    """读取本地缓存的用药计划。

    :param path: 缓存文件路径，默认 CACHE_PATH
    :return: 计划列表；文件缺失/损坏/格式非法时返回空列表
    """
    path = path or CACHE_PATH
    with _lock:
        try:
            if not os.path.exists(path):
                return []
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"读取本地用药计划缓存失败: {e}")
            return []
    items = _normalize(data)
    if items is None:
        logger.warning(f"本地用药计划缓存格式非法（应为列表）: {type(data)}")
        return []
    return items


def save_schedules(schedules, path=None):
    """原子写入用药计划缓存。

    :param schedules: 计划列表（非列表将被拒绝）
    :param path: 缓存文件路径，默认 CACHE_PATH
    :return: True 表示写入成功
    """
    items = _normalize(schedules)
    if items is None:
        logger.warning(f"拒绝写入非列表的用药计划缓存: {type(schedules)}")
        return False

    path = path or CACHE_PATH
    directory = os.path.dirname(os.path.abspath(path))
    with _lock:
        tmp_path = None
        try:
            os.makedirs(directory, exist_ok=True)
            # 先写临时文件再原子替换，避免写入中断导致缓存损坏
            fd, tmp_path = tempfile.mkstemp(prefix=".schedules_", suffix=".tmp", dir=directory)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(items, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            tmp_path = None
            return True
        except Exception as e:
            logger.warning(f"写入本地用药计划缓存失败: {e}")
            return False
        finally:
            # 异常路径清理临时文件，避免残留垃圾
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
