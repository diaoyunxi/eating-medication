# -*- coding: utf-8 -*-
"""
设备唯一标识符模块
行空板M10专用：通过pinpong库获取设备UUID
"""
import logging
import os
import uuid

logger = logging.getLogger("ElderlyAssistant")

# 模块加载时导入 ensure_board（仅依赖标准库，不会触发 pinpong 硬件初始化）。
# 测试环境下 elderly_assistant 目录由 load_module 临时加入 sys.path，
# 故在加载阶段完成导入，避免调用阶段路径已被移除导致 ImportError。
try:
    from hardware.board import ensure_board
except Exception:
    ensure_board = None


def get_device_id():
    """
    获取设备唯一标识符（UUID）
    优先通过 pinpong 库初始化行空板M10协处理器，读取设备 UUID；
    兜底：生成随机 UUID 并持久化到本地文件。
    """
    # 1. 尝试通过 pinpong 库获取行空板M10 设备 UUID
    device_id = _get_pinpong_uuid()
    if device_id:
        logger.info(f"使用行空板M10 UUID: {device_id}")
        return device_id

    # 2. 兜底：持久化 UUID
    device_id = _get_persisted_uuid()
    logger.info(f"使用持久化UUID: {device_id}")
    return device_id


def _get_pinpong_uuid():
    """通过 pinpong 库获取行空板M10设备 UUID。

    Board 初始化交由 hardware.board.ensure_board() 统一幂等管理，
    非 M10 环境（无 pinpong）下 ensure_board 返回 False，直接降级到持久化 UUID。

    行空板M10 的 pinpong Board 在初始化后提供设备唯一 UUID（board.uuid）；
    若当前 pinpong 版本未暴露该属性，则降级到持久化 UUID。
    """
    try:
        if ensure_board is None or not ensure_board():
            return None
        # ensure_board 内部已完成 Board().begin()，pinpong 将实例保存在模块全局 gboard
        from pinpong.board import gboard
        board = gboard
        if board is None:
            return None
        device_uuid = getattr(board, "uuid", None)
        if not device_uuid:
            logger.warning("pinpong Board 未提供 uuid 属性，降级到持久化 UUID")
            return None
        logger.info(f"通过pinpong库获取行空板UUID: {device_uuid}")
        return str(device_uuid)
    except Exception as e:
        logger.warning(f"pinpong库获取UUID失败: {e}")
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
    device_uuid = str(uuid.uuid4())
    with open(uuid_file, 'w') as f:
        f.write(device_uuid)
    return device_uuid
