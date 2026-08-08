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

# HuskyLens 初始化锁: 保护单例的"检查-创建连接-赋值"临界区.
# 即使扫码与拍照未在操作锁内调用 get_huskylens(如首次并发初始化),
# 也不会同时构造 I2C/UART 连接, 避免竞争导致识别或拍照失败.
_HUSKYLENS_INIT_LOCK = threading.Lock()


def _init_huskylens(config):
    """初始化 HuskyLens 连接。

    使用局部变量完成构造与 knock() 验证，成功后由调用方赋值全局单例，
    避免并发调用在 knock() 之前取到尚未验证的句柄。
    """
    cam_config = config.get('camera', {})
    conn_type = cam_config.get('connection', 'i2c')

    try:
        from dfrobot_huskylensv2 import HuskylensV2_I2C, HuskylensV2_UART

        if conn_type == 'uart':
            tty = cam_config.get('uart_tty', '/dev/ttyS1')
            baud = cam_config.get('uart_baudrate', 115200)
            hl = HuskylensV2_UART(tty_name=tty, baudrate=baud)
        else:
            hl = HuskylensV2_I2C()

        # 先完成构造与 knock() 验证，成功后才由调用方发布到全局单例
        if not hl.knock():
            raise RuntimeError("HuskyLens 未响应，请检查连接")
        return hl
    except ImportError:
        raise ImportError("未安装 dfrobot_huskylensv2 库")
    except Exception as e:
        raise


def get_huskylens(config=None):
    """获取 HuskyLens 实例，如未初始化则自动初始化。

    初始化使用独立锁 _HUSKYLENS_INIT_LOCK，保证“检查单例—创建连接—赋值单例”
    处于同一临界区，避免扫码与拍照在首次并发使用时竞争 I2C/UART 句柄
    （即使调用方未持有 _HUSKYLENS_OP_LOCK）。
    """
    global _huskylens
    if _huskylens is not None:
        return _huskylens
    with _HUSKYLENS_INIT_LOCK:
        # 双重检查：可能在等待锁期间已被其他线程初始化完成
        if _huskylens is not None:
            return _huskylens
        if config is None:
            raise RuntimeError("HuskyLens 未初始化，需要提供 config")
        # knock() 验证成功后才发布全局单例，避免并发取到未验证句柄
        _huskylens = _init_huskylens(config)
        return _huskylens


def capture_image(config):
    """使用 HuskyLens 拍照并保存"""
    logger = setup_logger()
    cam_config = config.get('camera', {})
    try:
        save_path = cam_config.get('save_path', 'data/captures')
        os.makedirs(save_path, exist_ok=True)
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        path = os.path.join(save_path, filename)

        # 与扫码(算法切换/读取)共享 HuskyLens 单例: 初始化与拍照均在操作锁内,
        # 避免首次并发使用时竞争 I2C/UART 句柄导致初始化或拍照失败
        with _HUSKYLENS_OP_LOCK:
            hl = get_huskylens(config)
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

