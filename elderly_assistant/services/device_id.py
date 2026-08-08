# -*- coding: utf-8 -*-
"""
设备唯一标识符模块
行空板M10专用：优先使用网卡MAC地址派生稳定的设备UUID。

说明：
- pinpong 的 `Board` 类（行空板官方文档+真实M10日志双重确认）并未暴露
  uuid / serial 等属性，仅作为硬件初始化入口，因此不能直接从 pinpong 取设备UUID。
- 网卡MAC地址是每设备唯一的稳定硬件标识，`uuid.getnode()` 直接返回该整数值，
  经 uuid5 确定性派生为标准UUID（36字符/4连字符），重启不变、删除本地文件也能重生。
- pinpong 取uuid仅保留为未来版本兼容的兜底尝试；随机持久化UUID为最后兜底。
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
    优先级：
    1. 网卡MAC地址派生（行空板M10稳定硬件标识，确定性、可重生）；
    2. pinpong 库（未来版本若暴露 uuid 属性可直接使用，当前固件无此属性）；
    3. 兜底：生成随机 UUID 并持久化到本地文件。
    """
    # 1. 主硬件来源：网卡MAC地址派生理性稳定的设备UUID
    device_id = _get_mac_uuid()
    if device_id:
        return device_id

    # 2. 兼容尝试：未来 pinpong 版本若暴露 uuid 属性
    device_id = _get_pinpong_uuid()
    if device_id:
        return device_id

    # 3. 兜底：持久化 UUID
    device_id = _get_persisted_uuid()
    logger.info(f"使用持久化UUID: {device_id}")
    return device_id


def _get_mac_uuid():
    """通过网卡MAC地址派生稳定的设备UUID（行空板M10硬件唯一标识）。

    `uuid.getnode()` 直接返回网卡MAC地址的整数值（非函数调用结果需二次处理，
    这里将其赋给局部变量 mac）。以该MAC经标准 uuid5 命名空间确定性派生为合法UUID，
    保证每设备唯一、重启不变、删除本地文件也能从MAC重生。
    """
    try:
        mac = uuid.getnode()
        if not mac:
            logger.warning("未能读取网卡MAC地址，降级到其它UUID来源")
            return None
        # 以固定命名空间+MAC确定性派生标准UUID v5，避免直接暴露MAC且格式合法
        device_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS,
                                    "eating-medication:%012X" % mac))
        logger.info(f"通过MAC地址派生设备UUID: {device_uuid}")
        return device_uuid
    except Exception as e:
        logger.warning(f"获取MAC地址派生UUID失败: {e}")
        return None


def _get_pinpong_uuid():
    """（兼容尝试）通过 pinpong 库获取设备 UUID。

    行空板当前官方固件/pinpong 版本并未在 Board 实例上暴露 uuid 属性
    （仅作为硬件初始化入口），因此该方法在真实M10上通常返回 None，
    仅保留以备未来 pinpong 版本提供该能力时自动启用。
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
            logger.debug("pinpong Board 未提供 uuid 属性，跳过（使用MAC派生UUID）")
            return None
        logger.info(f"通过pinpong库获取行空板UUID: {device_uuid}")
        return str(device_uuid)
    except Exception as e:
        logger.debug(f"pinpong库获取UUID失败（已忽略）: {e}")
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
