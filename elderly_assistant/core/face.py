# -*- coding: utf-8 -*-
"""二哈（HuskyLens V2）人脸识别封装：用于老人端服药前的身份核验与家属录入人脸。

复用 core.camera 的 HuskyLens 单例与硬件操作锁，避免与拍照/扫码并发冲突。
无硬件或库缺失时优雅降级（recognize 返回空、learn 返回 False），不阻塞主流程。
"""
from typing import List

from utils.logger import setup_logger

from core.camera import get_huskylens, _HUSKYLENS_OP_LOCK

logger = setup_logger()

# 人脸识别算法号（HuskyLens V2 标准：FACE_RECOGNITION = 2）。库亦提供同名常量，优先使用。
_ALGORITHM_FACE_RECOGNITION = 2


def _face_algorithm() -> int:
    """返回二哈人脸识别算法号，优先使用库常量。"""
    try:
        import dfrobot_huskylensv2 as hl_mod
        return getattr(hl_mod, "ALGORITHM_FACE_RECOGNITION", _ALGORITHM_FACE_RECOGNITION)
    except Exception:
        return _ALGORITHM_FACE_RECOGNITION


class FaceRecognizer:
    """二哈人脸识别器（设备端真实实现）。"""

    def __init__(self, config: dict):
        self.config = config or {}

    def is_available(self) -> bool:
        """摄像头与二哈库是否可用。"""
        try:
            logger.info("二哈人脸识别可用性检查: 尝试获取 HuskyLens 句柄")
            get_huskylens(self.config)
            logger.info("二哈人脸识别可用")
            return True
        except Exception as e:
            logger.warning("二哈人脸识别不可用（将降级）: %s", e)
            return False

    def recognize(self) -> List[int]:
        """识别当前帧中的人脸，返回已学习的人脸 ID 列表。

        空列表表示：未检测到人脸、未录入任何人脸，或摄像头不可用（严格模式下据此提示）。
        """
        try:
            algo = _face_algorithm()
            logger.info("二哈人脸识别: 获取硬件锁，算法号=%s", algo)
            with _HUSKYLENS_OP_LOCK:
                hl = get_huskylens(self.config)
                if hasattr(hl, "switchAlgorithm"):
                    logger.info("二哈人脸识别: switchAlgorithm(%s)", algo)
                    hl.switchAlgorithm(algo)
                count = hl.getResult(algo) if hasattr(hl, "getResult") else 0
                logger.debug("二哈人脸识别: getResult=%s", count)
                ids: List[int] = []
                if hasattr(hl, "getCachedResultByID"):
                    for i in range(count or 0):
                        block = hl.getCachedResultByID(algo, i)
                        if block is not None:
                            ids.append(getattr(block, "id", None))
                elif hasattr(hl, "result"):
                    blocks = (hl.result.get(algo, {}) or {}).get("blocks", []) or []
                    ids = [getattr(b, "id", None) for b in blocks]
                ids = [i for i in ids if i is not None]
                logger.info("二哈人脸识别到 %d 张人脸: %s", len(ids), ids)
                return ids
        except Exception as e:
            logger.warning("二哈人脸识别失败（降级为未检测到）: %s", e)
            return []

    def learn(self, face_id: int) -> bool:
        """学习当前帧人脸为指定 face_id。成功返回 True。

        face_id 由后端建议（同家庭组已录入人脸 ID 的最大值 + 1），保证设备内唯一。
        """
        try:
            algo = _face_algorithm()
            logger.info("二哈人脸学习: 获取硬件锁，算法号=%s face_id=%s", algo, face_id)
            with _HUSKYLENS_OP_LOCK:
                hl = get_huskylens(self.config)
                if hasattr(hl, "switchAlgorithm"):
                    logger.info("二哈人脸学习: switchAlgorithm(%s)", algo)
                    hl.switchAlgorithm(algo)
                fn = (
                    getattr(hl, "learnFace", None)
                    or getattr(hl, "learn_once", None)
                    or getattr(hl, "learn", None)
                )
                if not fn:
                    logger.error("二哈库不支持人脸学习方法")
                    return False
                logger.info("二哈人脸学习: 调用 %s(%s)", getattr(fn, "__name__", fn), face_id)
                try:
                    ret = fn(face_id)
                except TypeError:
                    # 部分二哈库实现签名不同（如需要额外参数），再次尝试
                    try:
                        ret = fn(face_id, "elderly")
                    except Exception as e:
                        logger.warning("二哈人脸学习调用失败: %s", e)
                        return False
                # 库返回 False / 0 表示未检测到人脸或学习超时，绝不能当作成功，
                # 否则服务端会写入一个设备上并不存在的 face_id，导致后续核验永远“非本人”。
                if ret is False or ret == 0:
                    logger.warning("二哈人脸学习未成功（未检测到人脸或超时），face_id=%s", face_id)
                    return False
                logger.info("二哈已学习人脸，face_id=%s", face_id)
                return True
        except Exception as e:
            logger.warning("二哈人脸学习失败: %s", e)
            return False
