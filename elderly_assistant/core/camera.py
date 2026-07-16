# -*- coding: utf-8 -*-
import os
from datetime import datetime
from utils.logger import setup_logger

# HuskyLens 实例（模块级单例）
_huskylens = None


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

        hl.takePhoto()
        logger.info("HuskyLens 拍照指令已发送")

        # P2 修复：拍照后检查文件是否真正生成，避免返回不存在的路径导致后续 open 失败
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


def recognize_objects(config, algorithm=None):
    """使用 HuskyLens 进行物体识别

    :param config: 配置字典
    :param algorithm: 算法类型，默认使用物体识别
    :return: 识别结果列表，每项包含 ID, name, xCenter, yCenter, width, height 等
    """
    logger = setup_logger()
    try:
        from dfrobot_huskylensv2 import ALGORITHM_OBJECT_RECOGNITION
        hl = get_huskylens(config)

        algo = algorithm or ALGORITHM_OBJECT_RECOGNITION
        hl.switchAlgorithm(algo)
        hl.getResult(algo)

        results = []
        if hl.available(algo):
            count = hl.getCachedResultNum(algo)
            for i in range(count):
                r = hl.getCachedResultByIndex(algo, i)
                if r:
                    results.append({
                        'id': r.ID,
                        'name': getattr(r, 'name', ''),
                        'content': getattr(r, 'content', ''),
                        'x': r.first,
                        'y': r.second,
                        'width': r.third,
                        'height': r.fourth,
                    })
        logger.info(f"识别到 {len(results)} 个目标")
        return results
    except Exception as e:
        logger.error(f"物体识别异常: {e}")
        return []


def recognize_face(config):
    """使用 HuskyLens 进行人脸识别

    :return: 人脸识别结果列表
    """
    from dfrobot_huskylensv2 import ALGORITHM_FACE_RECOGNITION
    return recognize_objects(config, algorithm=ALGORITHM_FACE_RECOGNITION)


def reset_connection():
    """重置 HuskyLens 连接"""
    global _huskylens
    _huskylens = None

