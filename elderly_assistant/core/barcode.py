# -*- coding: utf-8 -*-
"""药品条码识别（一维条码 / 二维码）。

提供两条互补的扫码通路，运行时按配置自动选择：

1. **HuskyLens 板载识别**：DFRobot 二代智能摄像头内置条码（算法号 17）与
   二维码（算法号 18）识别算法，通过 ``switchAlgorithm`` + ``getResult``
   直接取回解码后的文本，行空板本机无需做图像解码，CPU 占用极低。
2. **USB 摄像头 + 本地解码**：OpenCV 抓帧 + pyzbar（zbar）本地解码，
   适用于未接 HuskyLens 或 HuskyLens 不可用的场景。

所有第三方依赖（dfrobot_huskylensv2 / cv2 / pyzbar）均为懒加载，缺失时
该通路自动标记为不可用并降级到另一条通路，不影响主程序运行。

配置项（.env）：
    SCAN_SOURCE       auto | huskylens | usb，默认 auto（优先 HuskyLens）
    SCAN_USB_INDEX    USB 摄像头设备序号，默认 0
    SCAN_TIMEOUT_SEC  单次扫码超时秒数，默认 8
"""

import logging
import threading
import time

from core.camera import get_huskylens, _HUSKYLENS_OP_LOCK

logger = logging.getLogger("ElderlyAssistant")

# HuskyLens 官方算法编号；优先从驱动模块读取常量，取不到时用字面量兜底
_DEFAULT_ALGO_BARCODE = 17
_DEFAULT_ALGO_QRCODE = 18

# 单次扫码默认超时（秒）
DEFAULT_TIMEOUT_SEC = 8.0
# 两次取帧之间的间隔（秒），避免占满 CPU
_POLL_INTERVAL_SEC = 0.2


def _clean_code(text):
    """规范化解码结果：bytes 解码为 str，去除不可打印字符与首尾空白。

    :return: 规范化后的编码文本；为空则返回 None
    """
    if text is None:
        return None
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8", "ignore")
        except Exception:
            return None
    try:
        code = "".join(ch for ch in str(text) if ch.isprintable()).strip()
    except Exception:
        return None
    return code or None


class HuskyLensScanner:
    """HuskyLens 板载条码/二维码识别通路。"""

    name = "HuskyLens"

    def __init__(self, config=None):
        self._config = config or {}
        self._hl = None
        self._algos = ()
        # 当前已切换到的算法号，避免每帧重复下发切换指令
        self._current_algo = None

    def _ensure(self):
        """懒加载 HuskyLens 句柄与算法常量；不可用时抛异常由调用方降级。"""
        if self._hl is not None:
            return self._hl
        # 同步 HuskyLens 单例的初始化，避免多线程首次并发使用时竞态
        with _HUSKYLENS_OP_LOCK:
            if self._hl is not None:
                return self._hl
            # 复用 core.camera 的连接单例，避免与拍照功能争抢 I2C/UART 句柄
            import dfrobot_huskylensv2 as hl_module

            hl = get_huskylens(self._config)
            self._algos = (
                getattr(hl_module, "ALGORITHM_BARCODE_RECOGNITION", _DEFAULT_ALGO_BARCODE),
                getattr(hl_module, "ALGORITHM_QRCODE_RECOGNITION", _DEFAULT_ALGO_QRCODE),
            )
            self._hl = hl
            return hl

    @staticmethod
    def _read_contents(hl, algo):
        """读取指定算法本轮识别到的全部文本内容。

        关键修复：HuskyLens 的 ``hl.result[algo]["blocks"]`` 是驱动内部缓存，
        部分驱动版本在 ``getResult(algo)`` 返回 0（当前帧无目标）时并不会清空
        该缓存，导致上一次识别到的条码/二维码 ``content`` 残留。若直接信任该
        字典，会出现「镜头前已无条码，却仍返回第一次识别的结果」的缺陷。

        因此这里**不读取 ``result`` 旧字典**，统一改用 ``getCachedResultByID``
        逐个实时拉取当前帧——该函数每次调用都会重新向摄像头下发取数指令，
        返回空即代表当前帧确实没有可识别目标。``getResult`` 仅作为循环上界
        参考，且当 ``total <= 0`` 时直接返回空（不读取任何残留缓存）。
        """
        try:
            total = int(hl.getResult(algo) or 0)
        except (TypeError, ValueError):
            total = 0
        if total <= 0:
            # 当前帧无目标：保持干净，绝不可读取残留缓存
            return []

        getter = getattr(hl, "getCachedResultByID", None)
        if callable(getter):
            # HuskyLens 的学习 ID 从 1 开始编号；以实时返回为准，忽略 result 缓存
            blocks = []
            for idx in range(1, total + 1):
                try:
                    item = getter(algo, idx)
                except Exception:
                    item = None
                if item is not None:
                    blocks.append(item)
        else:
            # 极少数驱动未提供 getCachedResultByID：回退读取 result 字典，
            # 但仅取其内容——此时已确认 total > 0，残留风险由上层轮询兜底
            cache = getattr(hl, "result", None)
            blocks = []
            if isinstance(cache, dict):
                entry = cache.get(algo) or {}
                if isinstance(entry, dict):
                    blocks = list(entry.get("blocks") or [])

        codes = []
        for block in blocks:
            code = _clean_code(getattr(block, "content", None))
            if code:
                codes.append(code)
        return codes

    def scan_once(self):
        """尝试识别一次（条码优先、二维码兜底），无结果返回 None。"""
        hl = self._ensure()
        # 与拍照（takePhoto）共享 HuskyLens 单例句柄，加锁避免并发切换/读取冲突
        with _HUSKYLENS_OP_LOCK:
            for algo in self._algos:
                if self._current_algo != algo:
                    try:
                        hl.switchAlgorithm(algo)
                    except Exception as e:
                        logger.debug(f"HuskyLens 切换算法 {algo} 失败: {e}")
                        continue
                    self._current_algo = algo
                codes = self._read_contents(hl, algo)
                if codes:
                    return codes[0]
        return None

    def close(self):
        """释放引用（HuskyLens 连接由 core.camera 单例统一管理，此处不断开）。"""
        self._hl = None
        self._current_algo = None


class UsbCameraScanner:
    """USB 摄像头 + pyzbar 本地解码通路。"""

    name = "USB摄像头"

    def __init__(self, config=None):
        scan_cfg = (config or {}).get("scan") or {}
        try:
            self.index = int(scan_cfg.get("usb_index", 0))
        except (TypeError, ValueError):
            self.index = 0
        self._cap = None
        self._decode = None

    def _ensure(self):
        """懒加载 OpenCV 摄像头与 pyzbar 解码函数；不可用时抛异常由调用方降级。"""
        if self._cap is not None and self._decode is not None:
            return
        import cv2
        from pyzbar.pyzbar import decode as zbar_decode

        cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            # 打开失败必须释放句柄，避免设备被占用无法重试
            try:
                cap.release()
            except Exception:
                pass
            raise RuntimeError(f"USB 摄像头(index={self.index}) 打开失败")
        self._cap = cap
        self._decode = zbar_decode

    def scan_once(self):
        """抓取一帧并本地解码，无结果返回 None。"""
        self._ensure()
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        for symbol in self._decode(frame) or []:
            code = _clean_code(getattr(symbol, "data", None))
            if code:
                return code
        return None

    def close(self):
        """释放摄像头句柄。"""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        self._cap = None
        self._decode = None


class BarcodeScanner:
    """统一扫码入口，满足 ports.BarcodeScannerPort。

    按配置 ``scan.source`` 选择通路：auto 模式下优先 HuskyLens（板载解码，
    速度快且不占本机 CPU），其不可用时自动回退 USB 摄像头本地解码。
    扫码为独占硬件操作，内部用非阻塞锁保证同一时刻只有一个扫码任务。
    """

    def __init__(self, config=None):
        cfg = config or {}
        scan_cfg = cfg.get("scan") or {}
        self._config = cfg
        self.source = (str(scan_cfg.get("source", "auto")).strip().lower() or "auto")
        try:
            self.timeout_sec = float(scan_cfg.get("timeout_sec", DEFAULT_TIMEOUT_SEC))
        except (TypeError, ValueError):
            self.timeout_sec = DEFAULT_TIMEOUT_SEC
        if self.timeout_sec <= 0:
            self.timeout_sec = DEFAULT_TIMEOUT_SEC
        self._backends = None
        self._lock = threading.Lock()

    def _build_backends(self):
        """按 source 配置构造通路列表（auto 时两条通路都参与，按序尝试）。"""
        if self.source == "huskylens":
            return [HuskyLensScanner(self._config)]
        if self.source == "usb":
            return [UsbCameraScanner(self._config)]
        if self.source != "auto":
            logger.warning(f"未知扫码源 {self.source!r}，按 auto 处理")
        return [HuskyLensScanner(self._config), UsbCameraScanner(self._config)]

    def scan(self, timeout=None):
        """在超时时间内轮询各通路，返回首个识别到的编码文本。

        :param timeout: 超时秒数，None 表示使用配置值
        :return: 编码文本；超时或全部通路不可用时返回 None
        """
        try:
            timeout = float(timeout) if timeout is not None else self.timeout_sec
        except (TypeError, ValueError):
            timeout = self.timeout_sec
        if timeout <= 0:
            timeout = DEFAULT_TIMEOUT_SEC

        # 非阻塞加锁：重复触发时直接忽略，避免多线程争抢同一摄像头
        if not self._lock.acquire(False):
            logger.info("已有扫码任务进行中，忽略本次扫码请求")
            return None
        try:
            if self._backends is None:
                self._backends = self._build_backends()
            deadline = time.monotonic() + timeout
            broken = set()
            while time.monotonic() < deadline:
                for idx, backend in enumerate(self._backends):
                    if idx in broken:
                        continue
                    try:
                        code = backend.scan_once()
                    except Exception as e:
                        # 通路初始化/读取失败：本次扫码内不再重试该通路
                        logger.warning(f"{backend.name} 扫码通路不可用: {e}")
                        broken.add(idx)
                        continue
                    if code:
                        logger.info(f"{backend.name} 识别到药品编码: {code}")
                        return code
                if len(broken) >= len(self._backends):
                    logger.error("所有扫码通路均不可用，请检查摄像头连接与依赖安装")
                    return None
                time.sleep(_POLL_INTERVAL_SEC)
            logger.info(f"扫码超时（{timeout:.0f} 秒）未识别到条码")
            return None
        finally:
            self._lock.release()

    def close(self):
        """释放所有通路占用的硬件资源。"""
        for backend in self._backends or []:
            try:
                backend.close()
            except Exception:
                pass
        self._backends = None
