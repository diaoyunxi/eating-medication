# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional
from app.core.dependencies import get_db, get_current_user
from app.core.database import SessionLocal
from app.core.security import decode_token
from app.models.user import User
from app.models.chat_message import ChatMessage
from app.schemas.chat import ChatMessageCreate, ChatMessageOut
from app.websocket.manager import manager
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["聊天"])


@router.post("/send", response_model=ChatMessageOut)
async def send_message(
    msg: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # 加认证
):
    """发送聊天消息

    校验 receiver_id 与 sender 属于同一家庭组，防止 IDOR。
    """
    # sender_id 从 token 提取，覆盖任何客户端传入值
    # sender_name 从服务端 current_user.full_name 获取，防止客户端伪造
    # 校验接收者是否与发送者同组
    if msg.receiver_id:
        receiver = db.query(User).filter(User.id == msg.receiver_id).first()
        if not receiver:
            raise HTTPException(status_code=404, detail="接收者不存在")
        # 校验同组关系（双方都必须有 group_id 且一致）
        if not current_user.group_id or current_user.group_id != receiver.group_id:
            raise HTTPException(status_code=403, detail="只能向同一家庭组成员发送消息")

    db_msg = ChatMessage(
        sender_id=current_user.id,
        receiver_id=msg.receiver_id,
        sender_name=current_user.full_name,
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
async def get_history(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),  # 限制 limit 范围 1~200
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # 加认证
):
    """获取用户聊天历史"""
    # 校验当前用户必须是消息参与者
    if user_id == current_user.id:
        # 查询自己的全部历史
        messages = db.query(ChatMessage).filter(
            or_(
                ChatMessage.sender_id == user_id,
                ChatMessage.receiver_id == user_id,
            )
        ).order_by(ChatMessage.created_at.desc()).limit(limit).all()
    else:
        # 仅允许查询自己与 user_id 之间的对话（current_user 必须是消息参与者）
        messages = db.query(ChatMessage).filter(
            or_(
                and_(ChatMessage.sender_id == current_user.id, ChatMessage.receiver_id == user_id),
                and_(ChatMessage.sender_id == user_id, ChatMessage.receiver_id == current_user.id),
            )
        ).order_by(ChatMessage.created_at.desc()).limit(limit).all()
    return messages


@router.websocket("/ws/{user_id}")
async def ws_chat(websocket: WebSocket, user_id: int, token: Optional[str] = Query(None)):
    """WebSocket聊天连接（从 query 参数读取 token 校验，使用 token 中的 user_id）

    JWT sub 字段是 username（字符串），不能直接 int() 转换，
    改为通过 username 查库获取数字 user_id。
    """
    # C4：token 校验，无效则关闭连接（code=1008）
    authenticated_user_id = None
    if token:
        try:
            payload = decode_token(token)
            sub = payload.get("sub")
            if sub is not None:
                # JWT sub 字段存储的是 user.id（数字字符串），
                # 原代码用 User.username == sub 查询，导致所有 WebSocket 连接
                # 认证失败返回 403。改为用 User.id == int(sub) 查询。
                with SessionLocal() as db:
                    user = db.query(User).filter(User.id == int(sub)).first()
                    if user:
                        authenticated_user_id = user.id
        except (ValueError, TypeError):
            # sub 不是有效的数字 ID
            authenticated_user_id = None
        except Exception:
            authenticated_user_id = None
    if authenticated_user_id is None:
        await websocket.close(code=1008)
        return
    # 使用 token 中的 user_id，忽略 URL 中的 user_id
    user_id = authenticated_user_id
    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "chat":
                content = data.get("content", "")
                receiver_id = data.get("receiver_id")
                if content and receiver_id:
                    with SessionLocal() as db:
                        # sender_name 从服务端查库获取，防止客户端伪造
                        sender = db.query(User).filter(User.id == user_id).first()
                        sender_name = sender.full_name if sender else "未知"
                        # sender 可能为 None（用户被删除），
                        # 原代码直接访问 sender.group_id 会抛出 AttributeError，
                        # 导致 WebSocket 连接异常中断。增加 None 检查。
                        if not sender:
                            await websocket.send_json({"type": "error", "message": "发送者账号不存在"})
                            continue
                        # 校验接收者是否与发送者同组
                        receiver = db.query(User).filter(User.id == receiver_id).first()
                        if not receiver:
                            await websocket.send_json({"type": "error", "message": "接收者不存在"})
                            continue
                        if not sender.group_id or sender.group_id != receiver.group_id:
                            await websocket.send_json({"type": "error", "message": "只能向同一家庭组成员发送消息"})
                            continue
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
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket 异常: {e}")
    finally:
        manager.disconnect(websocket, user_id)
