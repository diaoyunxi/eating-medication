# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.chat_message import ChatMessage
from app.schemas.chat import ChatMessageCreate, ChatMessageOut
from app.websocket.manager import manager
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["聊天"])


@router.post("/send", response_model=ChatMessageOut)
async def send_message(msg: ChatMessageCreate, db: Session = Depends(get_db)):
    """发送聊天消息"""
    db_msg = ChatMessage(
        sender_id=msg.sender_id,
        receiver_id=msg.receiver_id,
        sender_name=msg.sender_name,
        content=msg.content
    )
    db.add(db_msg)
    db.commit()
    db.refresh(db_msg)

    # 通过WebSocket推送给接收者
    if msg.receiver_id:
        await manager.send_to_user(msg.receiver_id, {
            "type": "chat_message",
            "id": db_msg.id,
            "sender_id": db_msg.sender_id,
            "sender_name": db_msg.sender_name,
            "content": db_msg.content,
            "timestamp": db_msg.created_at.isoformat()
        })
    return db_msg


@router.get("/history/{user_id}", response_model=List[ChatMessageOut])
async def get_history(user_id: int, limit: int = 50, db: Session = Depends(get_db)):
    """获取用户聊天历史"""
    messages = db.query(ChatMessage).filter(
        (ChatMessage.sender_id == user_id) | (ChatMessage.receiver_id == user_id)
    ).order_by(ChatMessage.created_at.desc()).limit(limit).all()
    return messages


@router.websocket("/ws/{user_id}")
async def ws_chat(websocket: WebSocket, user_id: int):
    """WebSocket聊天连接"""
    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "chat":
                content = data.get("content", "")
                receiver_id = data.get("receiver_id")
                sender_name = data.get("sender_name", "未知")
                if content and receiver_id:
                    db = next(get_db())
                    try:
                        db_msg = ChatMessage(
                            sender_id=user_id,
                            receiver_id=receiver_id,
                            sender_name=sender_name,
                            content=content
                        )
                        db.add(db_msg)
                        db.commit()
                        db.refresh(db_msg)
                        await manager.send_to_user(receiver_id, {
                            "type": "chat_message",
                            "id": db_msg.id,
                            "sender_id": user_id,
                            "sender_name": sender_name,
                            "content": content,
                            "timestamp": db_msg.created_at.isoformat()
                        })
                        await websocket.send_json({
                            "type": "message_sent",
                            "id": db_msg.id
                        })
                    finally:
                        db.close()
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
