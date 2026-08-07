# -*- coding: utf-8 -*-
import os
import threading
from datetime import datetime
from utils.logger import setup_logger

# HuskyLens 实例（模块级单例）
_huskylens = None

# HuskyLens 硬件操作锁：扫码（算法切换/读取）与拍照（takePhoto）共享同一单例
# 句柄，加锁避免二者并发操作同一硬件导致识别失败或拍照异常
_HUSKYLENS_OP_LOCK = threading.Lock()


def _init_huskylens(config):
    """初始化 HuskyLens 连接"""
    global _huskylens
    if _huskylens is not None:
        return _huskylens

    cam_config = config.get('camera', {})
    conn_type = cam_config.get('connection', 'i2c')

    try:
        from dfrobot_huskylensv2 import HuskylensV2_I2C, HuskylensV2_UART

        if conn_type == 'uart':
            tty = cam_config.get('uart_tty', '/dev/ttyS1')
            baud = cam_config.get('uart_baudrate', 115200)
            _huskylens = HuskylensV2_UART(tty_name=tty, baudrate=baud)
        else:
            _huskylens = HuskylensV2_I2C()

        if not _huskylens.knock():
            raise RuntimeError("HuskyLens 未响应，请检查连接")
        return _huskylens
    except ImportError:
        raise ImportError("未安装 dfrobot_huskylensv2 库")
    except Exception as e:
        _huskylens = None
        raise


def get_huskylens(config=None):
    """获取 HuskyLens 实例，如未初始化则自动初始化"""
    global _huskylens
    if _huskylens is not None:
        return _huskylens
    if config is None:
        raise RuntimeError("HuskyLens 未初始化，需要提供 config")
    return _init_huskylens(config)


def capture_image(config):
    """使用 HuskyLens 拍照并保存"""
    logger = setup_logger()
    cam_config = config.get('camera', {})
    try:
        hl = get_huskylens(config)

        save_path = cam_config.get('save_path', 'data/captures')
        os.makedirs(save_path, exist_ok=True)
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        path = os.path.join(save_path, filename)

        # 与扫码（算法切换/读取）共享 HuskyLens 单例，加锁避免并发冲突
        with _HUSKYLENS_OP_LOCK:
            hl.takePhoto()
        logger.info("HuskyLens 拍照指令已发送")

        # 拍照后检查文件是否真正生成，避免返回不存在的路径导致后续 open 失败
        if not os.path.exists(path):
            logger.error(f"拍照后文件不存在: {path}，HuskyLens可能未回传图片")
            return None
        logger.info(f"拍照成功: {path}")
        return path
    except ImportError:
        logger.error("未安装 dfrobot_huskylensv2 库")
        return None
    except RuntimeError as e:
        logger.error(f"HuskyLens 连接失败: {e}")
        return None
    except Exception as e:
        logger.error(f"摄像头操作异常: {e}")
        return None


def reset_connection():
    """重置 HuskyLens 连接"""
    global _huskylens
    _huskylens = None

