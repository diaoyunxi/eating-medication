# -*- coding: utf-8 -*-
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class ChatMessageCreate(BaseModel):
    """创建聊天消息请求（sender_id 从 token 提取，不接收客户端传入）

    移除客户端传入的 sender_name，改为服务端从 current_user.username 获取，
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
