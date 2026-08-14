# -*- coding: utf-8 -*-
"""设备唯一标识符模块

行空板 M10 专用：直接使用 `uuid.getnode()` 返回的网卡 MAC 地址整数值作为设备 ID。

说明：
- `uuid.getnode()` 返回网卡 MAC 地址的整数形式（如 218356669348204），
  每台设备唯一、重启不变，无需本地持久化文件即可稳定重生。
- 相比此前的 uuid5 派生（36 字符含连字符），整数形式显著更短，
  便于在 M10 小屏上完整显示，也便于家属在子女端手工输入绑定。
"""
import logging
import uuid

logger = logging.getLogger("ElderlyAssistant")


def get_device_id():
    """获取设备唯一标识符（网卡 MAC 地址整数值的字符串形式）。

    直接取 `uuid.getnode()`，返回如 '218356669348204' 的十进制字符串。
    统一返回字符串类型，与服务端 device_id 字段（str）及既有调用方保持一致。

    :return: 设备 ID 字符串；无法读取 MAC 时返回 None
    """
    try:
        mac = uuid.getnode()
    except Exception as e:
        logger.warning(f"获取网卡 MAC 地址失败: {e}")
        return None
    if not mac:
        logger.warning("未能读取网卡 MAC 地址，设备 ID 不可用")
        return None
    device_id = str(mac)
    return device_id
