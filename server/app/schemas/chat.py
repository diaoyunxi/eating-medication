# -*- coding: utf-8 -*-
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class ChatMessageCreate(BaseModel):
    sender_id: int
    receiver_id: Optional[int] = None
    sender_name: str
    content: str


class ChatMessageOut(BaseModel):
    id: int
    sender_id: int
    receiver_id: Optional[int] = None
    sender_name: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
