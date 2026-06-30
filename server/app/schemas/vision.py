# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field

class ImageRecognitionResp(BaseModel):
    """药品图片识别响应"""
    drug_name: str = Field(..., description="识别的药名")
    confidence: float = Field(..., ge=0, le=1, description="置信度")