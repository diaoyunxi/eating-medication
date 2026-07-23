# -*- coding: utf-8 -*-
import logging
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, JSONResponse
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.vision import ImageRecognitionResp
from app.services.vision_service import VisionService

logger = logging.getLogger(__name__)

# 注意：tags 必须是一个列表，即使只有一个元素
router = APIRouter(prefix="/vision", tags=["药名识别"])

@router.post("/recognize", response_model=ImageRecognitionResp)
async def recognize_drug(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """上传药品图片，识别药名"""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="文件必须是图片")
    try:
        contents = await file.read()
        # 文件大小限制 5MB
        if len(contents) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="文件过大，最大 5MB")
        result = await VisionService.recognize(contents)
        # OCR 未配置或不可用：优雅降级返回明确提示，而非 500 错误
        if not result.get("configured"):
            return JSONResponse(
                status_code=200,
                content={
                    "configured": False,
                    "message": result.get("reason", "OCR 服务未配置，药名识别功能暂不可用"),
                },
            )
        return ImageRecognitionResp(drug_name=result["name"], confidence=result["confidence"])
    except HTTPException:
        # 大小限制等 HTTP 异常直接向上抛出
        raise
    except Exception:
        # 异常细节不返回客户端，仅记录详细日志
        logger.exception("识别失败")
        raise HTTPException(status_code=500, detail="识别失败，请稍后重试")
