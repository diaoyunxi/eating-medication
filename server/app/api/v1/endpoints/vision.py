# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.vision import ImageRecognitionResp
from app.services.vision_service import VisionService

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
        result = await VisionService.recognize(contents)
        return ImageRecognitionResp(drug_name=result["name"], confidence=result["confidence"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"识别失败: {str(e)}")