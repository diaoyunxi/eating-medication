# -*- coding: utf-8 -*-
"""
二哈摄像头模块（网络图传版）

【重大改造说明 v2.43.0】
原 camera.py 使用「I2C/UART 拍照 → 二哈 SD 卡保存 → M10 挂载 U 盘取回」方案。
现改为：M10 与二哈 V2 连接同一 WiFi，通过网络（HTTP 快照 / RTSP 拉流）获取实时图片。

I2C/UART 总线保留用途（仅用于识别，不再用于拍照）：
  - core/barcode.py：条码识别（switchAlgorithm + getResult 读取识别结果）
  - core/face.py  ：人脸识别（switchAlgorithm + getResult 读取人脸 ID）
  以上功能保持原逻辑不变，通过 get_huskylens() 复用已有单例。

新增网络图传能力（core/network_camera.py）：
  - capture_image(config)   → 获取一帧 JPEG 并保存到本地，返回文件路径
  - capture_frame(config)   → 直接返回 JPEG 字节（不保存文件）
  - discover_huskylens_on_network() → 自动扫描局域网中的二哈设备

兼容模式：若未配置 HUSKYLENS_IP，则回退到原有 I2C 拍照+SD卡取回方案（已废弃）。
"""

import glob
import os
import shutil
import threading
from datetime import datetime
from uuid import uuid4
from utils.logger import setup_logger

logger = setup_logger()

# ─────────────────────────────────────────────────────────────────
# 以下 I2C/UART 相关代码保留，仅供 barcode.py / face.py 使用
# ─────────────────────────────────────────────────────────────────

# HuskyLens 实例（模块级单例）
_huskylens = None

# HuskyLens 硬件操作锁：扫码（算法切换/读取）与拍照（takePhoto）共享同一单例
# 句柄，加锁避免二者并发操作同一硬件导致识别失败或拍照异常
_HUSKYLENS_OP_LOCK = threading.Lock()

# HuskyLens 初始化锁: 保护单例的"检查-创建连接-赋值"临界区.
# 即使扫码与拍照未在操作锁内调用 get_huskylens(如首次并发初始化),
# 也不会同时构造 I2C/UART 连接, 避免竞争导致识别或拍照失败.
_HUSKYLENS_INIT_LOCK = threading.Lock()


def _init_huskylens(config):
    """初始化 HuskyLens I2C/UART 连接（仅供条码/人脸识别使用）。"""
    cam_config = config.get('camera', {})
    conn_type = cam_config.get('connection', 'i2c')
    logger.info("二哈 I2C/UART 连接初始化: 连接方式=%s（仅供识别使用）", conn_type)

    try:
        from dfrobot_huskylensv2 import HuskylensV2_I2C, HuskylensV2_UART

        if conn_type == 'uart':
            tty = cam_config.get('uart_tty', '/dev/ttyS1')
            baud = cam_config.get('uart_baudrate', 115200)
            logger.info("二哈 UART 参数: tty=%s baudrate=%s", tty, baud)
            hl = HuskylensV2_UART(tty_name=tty, baudrate=baud)
        else:
            hl = HuskylensV2_I2C()

        logger.info("二哈执行 knock() 握手验证...")
        if not hl.knock():
            raise RuntimeError("HuskyLens 未响应，请检查 I2C/UART 连接（条码/人脸功能受影响）")
        logger.info("二哈 knock() 验证通过，I2C/UART 连接就绪")
        return hl
    except ImportError:
        raise ImportError("未安装 dfrobot_huskylensv2 库（条码/人脸功能不可用）")
    except Exception as e:
        raise


def get_huskylens(config=None):
    """获取 HuskyLens I2C/UART 实例（仅供条码/人脸识别使用）。

    注意：此单例不再用于拍照/图传（图传已改为网络方式）。
    """
    global _huskylens
    if _huskylens is not None:
        logger.debug("二哈 I2C/UART 单例已存在，复用")
        return _huskylens
    with _HUSKYLENS_INIT_LOCK:
        if _huskylens is not None:
            logger.debug("二哈 I2C/UART 单例已被其他线程初始化，复用")
            return _huskylens
        if config is None:
            raise RuntimeError("HuskyLens 未初始化，需要提供 config")
        logger.info("二哈 I2C/UART 单例不存在，开始初始化连接")
        _huskylens = _init_huskylens(config)
        logger.info("二哈 I2C/UART 单例初始化完成并发布")
        return _huskylens


def reset_i2c_connection():
    """重置 HuskyLens I2C/UART 连接（不影响网络图传）。"""
    global _huskylens
    _huskylens = None
    logger.info("二哈 I2C/UART 连接已重置")


# ─────────────────────────────────────────────────────────────────
# 网络图传入口（主流程使用）
# ─────────────────────────────────────────────────────────────────

def capture_image(config):
    """使用网络图传获取二哈实时画面并保存到本地。

    优先从 network_camera 模块获取（HTTP/RTSP），
    若未配置 HUSKYLENS_IP 则回退到原有 I2C 拍照+SD卡取回方案（已废弃，仅兼容）。

    :param config: 完整配置字典
    :return: 本地保存的 .jpg 文件路径；全部失败返回 None
    """
    # 优先尝试网络图传
    try:
        from core.network_camera import capture_image as network_capture
        result = network_capture(config)
        if result:
            return result
        logger.warning("网络图传失败，尝试回退到 I2C 拍照方案（已废弃）")
    except ImportError:
        logger.warning("network_camera 模块不可用，尝试回退到 I2C 拍照方案（已废弃）")
    except Exception as e:
        logger.warning("网络图传异常: %s，尝试回退", e)

    # 回退：原有 I2C 拍照 + SD卡取回（兼容旧部署，建议逐步移除）
    return _capture_image_legacy(config)


def _capture_image_legacy(config):
    """[已废弃] 原有 I2C 拍照 + SD 卡取回方案。

    仅在未配置 HUSKYLENS_IP 时作为兼容回退使用。
    建议迁移到网络图传后删除此函数。
    """
    cam_config = config.get('camera', {})
    save_path = cam_config.get('save_path', 'data/captures')
    os.makedirs(save_path, exist_ok=True)

    resolution = cam_config.get('photo_resolution', 'default')
    logger.info("[兼容模式] 二哈 I2C 拍照: resolution=%s", resolution)

    try:
        with _HUSKYLENS_OP_LOCK:
            hl = get_huskylens(config)
            remote_name = hl.takePhoto(resolution)
        logger.info("HuskyLens 拍照指令已发送，返回文件名: %r", remote_name)

        if not remote_name:
            logger.error("I2C 拍照失败（takePhoto 未返回文件名）")
            return None

        # 从二哈 SD 卡挂载点取回照片
        local_path = _fetch_huskylens_photo(remote_name, save_path, cam_config, logger)
        if not local_path:
            logger.error(
                "拍照后未找到二哈 SD 卡上的照片 %s（SD 卡需挂载到 M10）",
                remote_name,
            )
            return None
        logger.info("I2C 拍照成功（兼容模式）: %s", local_path)
        return local_path
    except ImportError:
        logger.error("未安装 dfrobot_huskylensv2 库")
        return None
    except RuntimeError as e:
        logger.error(f"I2C 连接失败: {e}")
        return None
    except Exception as e:
        logger.error(f"摄像头操作异常: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# SD 卡取回辅助函数（兼容回退使用）
# ─────────────────────────────────────────────────────────────────

_DEFAULT_SD_SEARCH_ROOTS = ["/media", "/mnt", "/run/media"]


def _normalize_sd_search_paths(cam_config):
    """将 camera.sd_search_paths 归一化为根目录列表。"""
    raw = cam_config.get('sd_search_paths')
    if not raw:
        return list(_DEFAULT_SD_SEARCH_ROOTS)
    if isinstance(raw, str):
        return [p.strip() for p in raw.split(',') if p.strip()]
    return list(raw)


def _discover_huskylens_storage(cam_config):
    """自动发现二哈 V2 U 盘上的照片目录（兼容回退使用）。"""
    found = []
    for base in _normalize_sd_search_paths(cam_config):
        if not os.path.isdir(base):
            continue
        for mount in glob.glob(os.path.join(base, "*")):
            if not os.path.isdir(mount):
                continue
            for name in ("Huskylens", "huskylens", "HUSKYLENS"):
                for husk in glob.glob(os.path.join(mount, "**", name), recursive=True):
                    photo_dir = os.path.join(husk, "storage", "photo")
                    if os.path.isdir(photo_dir):
                        found.append(photo_dir)
    return found


def _fetch_huskylens_photo(remote_name, save_path, cam_config, logger_inst):
    """将二哈 SD 卡上的照片复制到本地（兼容回退使用）。"""
    try:
        roots = _normalize_sd_search_paths(cam_config) + _discover_huskylens_storage(cam_config)
    except Exception as e:
        logger_inst.debug("自动探测二哈 U 盘目录失败: %s", e)
        roots = _normalize_sd_search_paths(cam_config)

    seen = set()
    for root in roots:
        if not root or root in seen:
            continue
        seen.add(root)
        if not os.path.isdir(root):
            continue
        pattern = os.path.join(root, "**", os.path.basename(remote_name))
        for src in glob.glob(pattern, recursive=True):
            dst = os.path.join(
                save_path,
                f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid4().hex}.jpg",
            )
            try:
                shutil.copy2(src, dst)
                logger_inst.info("已从二哈 SD 卡取回照片: %s -> %s", src, dst)
                return dst
            except Exception as e:
                logger_inst.warning("复制二哈照片失败 %s: %s", src, e)
                continue
    return None
