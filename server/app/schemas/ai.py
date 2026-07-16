# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field

class AIQuestion(BaseModel):
    """AI 健康助手提问请求"""
    question: str = Field(..., min_length=1, max_length=500)

class AIAnswer(BaseModel):
    """AI 回答响应"""
    answer: str