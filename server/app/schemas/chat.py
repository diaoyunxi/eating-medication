# -*- coding: utf-8 -*-
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class ChatMessageCreate(BaseModel):
    """创建聊天消息请求（C4：移除 sender_id，改为从 token 提取）

    S-01 修复：移除客户端传入的 sender_name，改为服务端从 current_user.full_name 获取，
    防止客户端伪造发送者姓名。
    """
    receiver_id: Optional[int] = None
    content: str


class ChatMessageOut(BaseModel):
    id: int
    sender_id: int
    receiver_id: Optional[int] = None
    sender_name: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
