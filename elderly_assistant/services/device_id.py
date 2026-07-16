# -*- coding: utf-8 -*-
"""
设备唯一标识符模块
行空板M10专用：通过pinpong库获取FCC ID
"""
import logging
import os
import uuid

logger = logging.getLogger("ElderlyAssistant")


def get_device_id():
    """
    获取设备唯一标识符（FCC ID）
    通过 pinpong 库初始化行空板M10协处理器，获取设备MAC地址生成FCC ID
    兜底：生成随机 UUID 并持久化到本地文件
    """
    # 1. 尝试通过 pinpong 库获取行空板M10 FCC ID
    device_id = _get_fcc_id()
    if device_id:
        logger.info(f"使用行空板M10 FCC ID: {device_id}")
        return device_id

    # 2. 兜底：持久化 UUID
    device_id = _get_persisted_uuid()
    logger.info(f"使用持久化UUID: {device_id}")
    return device_id


def _get_fcc_id():
    """通过 pinpong 库获取行空板M10设备FCC ID"""
    try:
        from pinpong.board import Board
        Board().begin()
        # 通过pinpong库初始化协处理器后，使用MAC地址生成FCC ID
        mac = uuid.getnode()
        fcc_id = f"FCC_{mac:012X}"
        logger.info(f"通过pinpong库获取行空板FCC ID: {fcc_id}")
        return fcc_id
    except Exception as e:
        logger.warning(f"pinpong库获取FCC ID失败: {e}")
        return None


def _get_persisted_uuid():
    """获取或创建持久化UUID（兜底方案）"""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    uuid_file = os.path.join(data_dir, "device_id.txt")

    if os.path.exists(uuid_file):
        with open(uuid_file, 'r') as f:
            return f.read().strip()

    # 生成新 UUID 并保存
    device_uuid = f"DEV_{uuid.uuid4().hex[:16].upper()}"
    with open(uuid_file, 'w') as f:
        f.write(device_uuid)
    return device_uuid
