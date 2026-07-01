# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field
from typing import Optional


class ImageRecognitionResp(BaseModel):
    """药品图片识别响应"""
    drug_name: str = Field(..., description="识别的药名")
    # M20：置信度可能无法从 OCR 结果获取，允许为 None
    confidence: Optional[float] = Field(None, ge=0, le=1, description="置信度")
