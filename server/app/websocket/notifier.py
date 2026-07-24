# -*- coding: utf-8 -*-
from sqlalchemy.orm import Session
from app.websocket.manager import manager
from app.services.user_service import UserService
import logging

logger = logging.getLogger(__name__)

class Notifier:
    """消息推送工具类"""

    @staticmethod
    async def notify_taken_medication(
        db: Session,
        elderly_id: int,
        drug_name: str,
        taken_time: str
    ):
        """通知家属：老人已服药"""
        # 获取老人信息
        user = UserService.get_user_by_id(db, elderly_id)
        if not user or user.role != "elderly" or not user.group_id:
            return

        message = {
            "type": "medication_taken",
            "elderly_id": elderly_id,
            "elderly_name": user.username,
            "drug_name": drug_name,
            "taken_time": taken_time,
            "message": f"{user.username} 已服用 {drug_name}"
        }

        # 广播给同组所有成员
        await manager.broadcast_to_group(user.group_id, message, db)
        logger.info(f"已通知家庭组 {user.group_id}：{user.username} 服用了 {drug_name}")

    @staticmethod
    async def notify_missed_medication(
        db: Session,
        elderly_id: int,
        drug_name: str,
        scheduled_time: str
    ):
        """通知家属：老人漏服药品"""
        user = UserService.get_user_by_id(db, elderly_id)
        if not user or user.role != "elderly" or not user.group_id:
            return

        message = {
            "type": "medication_missed",
            "elderly_id": elderly_id,
            "elderly_name": user.username,
            "drug_name": drug_name,
            "scheduled_time": scheduled_time,
            "message": f"{user.username} 漏服 {drug_name}，请注意提醒"
        }

        await manager.broadcast_to_group(user.group_id, message, db)
        logger.warning(f"漏服通知：{user.username} 漏服 {drug_name}")

    @staticmethod
    async def notify_low_stock(
        db: Session,
        elderly_id: int,
        drug_name: str,
        remaining: float,
        threshold: int
    ):
        """通知家属：药品库存不足"""
        user = UserService.get_user_by_id(db, elderly_id)
        if not user or user.role != "elderly" or not user.group_id:
            return

        message = {
            "type": "low_stock",
            "elderly_id": elderly_id,
            "elderly_name": user.username,
            "drug_name": drug_name,
            "remaining": remaining,
            "threshold": threshold,
            "message": f"{user.username} 的 {drug_name} 库存不足（剩余 {remaining}），请及时购买"
        }

        await manager.broadcast_to_group(user.group_id, message, db)
        logger.info(f"低库存通知：{user.username} 的 {drug_name} 仅剩 {remaining}")

    @staticmethod
    async def notify_family_message(
        db: Session,
        group_id: int,
        sender_name: str,
        content: str
    ):
        """发送家庭消息"""
        message = {
            "type": "family_message",
            "sender": sender_name,
            "content": content,
            "timestamp": None  # 可添加时间戳
        }
        await manager.broadcast_to_group(group_id, message, db)

# 全局单例
notifier = Notifier()