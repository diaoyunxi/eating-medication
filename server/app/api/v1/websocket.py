# -*- coding: utf-8 -*-
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from app.websocket.manager import manager
from app.core.security import decode_token
from app.core.dependencies import get_db
from sqlalchemy.orm import Session
from app.services.user_service import UserService

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """
    WebSocket 连接入口，需要提供 JWT token 作为查询参数
    注意：生产环境应通过安全的通道传递token，如WSS和请求头
    例如: wss://localhost:8000/ws?token=eyJ...
    """
    user_id = None
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=1008)
            return
    except Exception:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, user_id)
    try:
        while True:
            # 接收客户端消息（可用于心跳或主动通知）
            data = await websocket.receive_text()
            # 可处理心跳消息，例如 {"type": "ping"}
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)