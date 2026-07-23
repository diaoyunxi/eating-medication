# -*- coding: utf-8 -*-
from typing import Dict, List
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    """
    WebSocket 连接管理器
    维护 user_id -> WebSocket 连接列表的映射

    注意：本实现仅适用于单进程部署。多进程部署时需使用 Redis Pub/Sub
    或其他消息中间件在进程间同步连接与消息，否则消息只能送达本进程内的连接。
    """

    def __init__(self):
        # 存储用户的所有活动连接（一个用户可能有多个设备连接）
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        """接受 WebSocket 连接并存储"""
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info(f"用户 {user_id} WebSocket 已连接，当前连接数: {len(self.active_connections[user_id])}")

    def disconnect(self, websocket: WebSocket, user_id: int):
        """移除断开的 WebSocket 连接"""
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
                logger.info(f"用户 {user_id} WebSocket 已断开")
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_to_user(self, user_id: int, message: dict):
        """向指定用户的所有连接发送消息"""
        if user_id in self.active_connections:
            # 遍历副本，避免遍历过程中 disconnect 修改原列表导致 RuntimeError
            for connection in list(self.active_connections[user_id]):
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"向用户 {user_id} 发送消息失败: {e}")

    async def broadcast_to_group(self, group_id: int, message: dict, db):
        """
        向家庭组内所有成员（老人+家属）广播消息
        需要传入 db 会话查询组成员
        """
        from app.services.user_service import UserService
        members = UserService.get_family_members(db, group_id)
        for member in members:
            await self.send_to_user(member.id, message)

# 全局单例
manager = ConnectionManager()