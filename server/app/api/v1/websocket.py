# -*- coding: utf-8 -*-
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.websocket.manager import manager
from app.core.security import decode_token

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """
    WebSocket 连接入口，需要提供 JWT token 作为查询参数。
    H14：通过 Query 传递 token 存在被日志/代理记录的风险，
    生产环境应改用 Sec-WebSocket-Protocol 子协议或连接后首条消息传递 token。
    此处增加 token 长度校验，防止日志过长或异常输入。
    """
    # H14：token 长度校验（防止日志过长/异常输入）
    if not token or len(token) > 2048:
        await websocket.close(code=1008)
        return

    user_id = None
    try:
        payload = decode_token(token)
        sub = payload.get("sub")
        if not sub:
            await websocket.close(code=1008)
            return
        # H7：sub 统一为字符串，解码后转为 int
        user_id = int(sub)
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
