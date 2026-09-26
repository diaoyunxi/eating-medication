# -*- coding: utf-8 -*-
from typing import Optional

from pydantic import BaseModel, Field

class AIQuestion(BaseModel):
    """AI 健康助手提问请求"""
    question: str = Field(..., min_length=1, max_length=500)

class AIAnswer(BaseModel):
    """AI 回答响应"""
    answer: str


class UserAIConfigIn(BaseModel):
    """每用户 AI 配置（写入）"""
    provider: str = "zhipuai"
    api_key: str = ""
    model: str = ""
    base_url: Optional[str] = None
    enabled: bool = True


class UserAIConfigOut(BaseModel):
    """每用户 AI 配置（返回，api_key 不回传明文，仅告知是否已配置）"""
    provider: str
    model: str
    base_url: Optional[str] = None
    enabled: bool
    has_api_key: bool = False


class AIProviderPreset(BaseModel):
    """前端厂商预设（用于下拉选择）"""
    id: str
    name: str
    default_model: str = ""
    requires_base_url: bool = False
    requires_model: bool = True
    doc_url: str = ""