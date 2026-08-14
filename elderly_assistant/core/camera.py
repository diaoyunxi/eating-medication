# -*- coding: utf-8 -*-
import glob
import os
import shutil
import threading
from datetime import datetime
from uuid import uuid4
from utils.logger import setup_logger

# 模块级 logger：供 get_huskylens / _init_huskylens 等模块作用域函数使用，
# 否则首次初始化 HuskyLens 连接（扫码调用链 barcode -> _ensure -> get_huskylens）
# 会触发 NameError: name 'logger' is not defined。
logger = setup_logger()

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
    logger.info("二哈连接初始化: 连接方式=%s", conn_type)

    try:
        from dfrobot_huskylensv2 import HuskylensV2_I2C, HuskylensV2_UART

        if conn_type == 'uart':
            tty = cam_config.get('uart_tty', '/dev/ttyS1')
            baud = cam_config.get('uart_baudrate', 115200)
            logger.info("二哈 UART 参数: tty=%s baudrate=%s", tty, baud)
            hl = HuskylensV2_UART(tty_name=tty, baudrate=baud)
        else:
            hl = HuskylensV2_I2C()

        # 先完成构造与 knock() 验证，成功后才由调用方发布到全局单例
        logger.info("二哈执行 knock() 握手验证...")
        if not hl.knock():
            raise RuntimeError("HuskyLens 未响应，请检查连接")
        logger.info("二哈 knock() 验证通过，连接就绪")
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
        logger.debug("二哈单例已存在，复用既有连接")
        return _huskylens
    with _HUSKYLENS_INIT_LOCK:
        # 双重检查：可能在等待锁期间已被其他线程初始化完成
        if _huskylens is not None:
            logger.debug("二哈单例已被其他线程初始化，复用")
            return _huskylens
        if config is None:
            raise RuntimeError("HuskyLens 未初始化，需要提供 config")
        # knock() 验证成功后才发布全局单例，避免并发取到未验证句柄
        logger.info("二哈单例不存在，开始初始化连接")
        _huskylens = _init_huskylens(config)
        logger.info("二哈单例初始化完成并发布")
        return _huskylens


# 二哈（HuskyLens V2）拍照后照片保存在自身 SD 卡，M10 需能从挂载点读到该文件。
# 二哈 V2 通过 USB 接入主控板后会作为 U 盘出现，内部目录为 Huskylens/storage/photo。
# 下列为常见 Linux / 行空板 M10 的 SD 卡挂载候选根目录，可由 camera.sd_search_paths
# 覆盖；代码同时会自动探测二哈 U 盘目录，通常无需手动配置。
_DEFAULT_SD_SEARCH_ROOTS = ["/media", "/mnt", "/run/media"]


def _normalize_sd_search_paths(cam_config):
    """将 camera.sd_search_paths 归一化为根目录列表（兼容字符串/列表/空值）。"""
    raw = cam_config.get('sd_search_paths')
    if not raw:
        return list(_DEFAULT_SD_SEARCH_ROOTS)
    if isinstance(raw, str):
        return [p.strip() for p in raw.split(',') if p.strip()]
    return list(raw)


def _discover_huskylens_storage(cam_config):
    """自动发现二哈 V2 U 盘上的照片目录，免去手动配置挂载点。

    二哈 V2 通过 USB 接入主控板后作为 U 盘出现，内部目录结构为
    <挂载点>/Huskylens/storage/photo（拍照）与 .../storage/screenshot（截屏）。
    这里在各候选挂载根下查找名为 Huskylens（大小写不敏感）的目录，返回其
    storage/photo 子目录，作为额外的照片搜索根。
    """
    found = []
    for base in _normalize_sd_search_paths(cam_config):
        if not os.path.isdir(base):
            continue
        # 先取一层挂载卷（如 /media/root/<VOL>），再在其内部递归查找 Huskylens 目录
        for mount in glob.glob(os.path.join(base, "*")):
            if not os.path.isdir(mount):
                continue
            for name in ("Huskylens", "huskylens", "HUSKYLENS"):
                for husk in glob.glob(os.path.join(mount, "**", name), recursive=True):
                    photo_dir = os.path.join(husk, "storage", "photo")
                    if os.path.isdir(photo_dir):
                        found.append(photo_dir)
    return found


def _fetch_huskylens_photo(remote_name, save_path, cam_config, logger):
    """将二哈 SD 卡上的照片复制到本地 save_path，返回本地路径；找不到返回 None。

    二哈 over I2C/UART 拍照后仅返回文件名（官方库 dfrobot_huskylensv2 不提供回传
    字节的接口），因此照片必须位于 M10 可访问的挂载点上。候选根目录可由
    camera.sd_search_paths 配置覆盖（逗号分隔字符串或列表）；同时会自动探测
    二哈 V2 通过 USB 接入后作为 U 盘出现的 Huskylens/storage/photo 目录。
    """
    # 配置指定的根 + 自动探测到的二哈 U 盘照片目录
    try:
        roots = _normalize_sd_search_paths(cam_config) + _discover_huskylens_storage(cam_config)
    except Exception as e:
        logger.debug("自动探测二哈 U 盘目录失败（将仅使用配置路径）: %s", e)
        roots = _normalize_sd_search_paths(cam_config)

    seen = set()
    logger.debug("二哈照片搜索根目录: %s", roots)
    for root in roots:
        if not root or root in seen:
            continue
        seen.add(root)
        if not os.path.isdir(root):
            continue
        # 递归查找与文件名同名的文件（二哈照片通常在 SD 卡根目录或子目录）
        pattern = os.path.join(root, "**", os.path.basename(remote_name))
        for src in glob.glob(pattern, recursive=True):
            dst = os.path.join(
                save_path,
                f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid4().hex}.jpg",
            )
            try:
                shutil.copy2(src, dst)
                logger.info("已从二哈 SD 卡取回照片: %s -> %s", src, dst)
                return dst
            except Exception as e:
                logger.warning("复制二哈照片失败 %s: %s", src, e)
                continue
    return None


def capture_image(config):
    """使用 HuskyLens 拍照并取回本地路径。

    修复点（对照官方 dfrobot_huskylensv2 库源码）：
    1. takePhoto 必须传入 resolution 参数（default/640x480/1280x720/1920x1080），
       否则函数直接返回空串（原代码无参调用会在运行时抛 TypeError）；
    2. takePhoto 返回的是二哈 SD 卡上的文件名（库不提供回传字节的接口），
       拍照后需在 M10 可访问的挂载点找到该文件并复制到本地 save_path，
       原代码却去检查本地 data/captures/<时间戳>.jpg（二哈不会写入），导致永远返回 None。
    """
    logger = setup_logger()
    cam_config = config.get('camera', {})
    try:
        save_path = cam_config.get('save_path', 'data/captures')
        os.makedirs(save_path, exist_ok=True)

        # 1) 拍照：必须传入 resolution（官方库 takePhoto(self, resolution) 必填）
        resolution = cam_config.get('photo_resolution', 'default')
        logger.info("二哈拍照: 获取硬件锁并发送 takePhoto(resolution=%s)", resolution)
        with _HUSKYLENS_OP_LOCK:
            hl = get_huskylens(config)
            remote_name = hl.takePhoto(resolution)
        logger.info("HuskyLens 拍照指令已发送，返回文件名: %r", remote_name)

        if not remote_name:
            logger.error(
                "HuskyLens 拍照失败（takePhoto 未返回文件名），请检查 resolution=%r 与摄像头连接",
                resolution,
            )
            return None

        # 2) 从二哈 SD 卡挂载点取回照片到本地
        local_path = _fetch_huskylens_photo(remote_name, save_path, cam_config, logger)
        if not local_path:
            logger.error(
                "拍照后未找到二哈 SD 卡上的照片 %s（SD 卡需挂载到 M10 且 camera.sd_search_paths 配置正确）",
                remote_name,
            )
            return None
        logger.info("拍照成功: %s", local_path)
        return local_path
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

