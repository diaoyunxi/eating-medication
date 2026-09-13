# -*- coding: utf-8 -*-
from datetime import datetime, timezone
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
    async def notify_unconfirmed_reminder(
        db: Session,
        elderly_id: int,
        drug_name: str,
        stage: str,
        scheduled_time: str
    ):
        """通知家属：老人端在 1 分钟 / 3 分钟内未确认用药（推送到网页聊天框）。

        stage="1m"：超过计划时间 1 分钟仍未确认；
        stage="3m"：超过计划时间 3 分钟仍未确认，提示确认老人状况或拨打 120。

        以 type=chat_message 推送，使家属端网页聊天界面可直接渲染显示。
        """
        user = UserService.get_user_by_id(db, elderly_id)
        if not user or user.role != "elderly" or not user.group_id:
            return

        try:
            sched_dt = datetime.fromisoformat(scheduled_time)
            plan_time = sched_dt.strftime("%H:%M")
        except Exception:
            plan_time = scheduled_time or ""

        if stage == "3m":
            content = (
                f"🚨 用药提醒：{user.username} 应于 {plan_time} 服用 {drug_name}，"
                f"已超过 3 分钟未确认，请确认老人状况或拨打 120。"
            )
        else:
            content = (
                f"🕐 用药提醒：{user.username} 应于 {plan_time} 服用 {drug_name}，"
                f"已超过 1 分钟未确认。"
            )

        message = {
            "type": "chat_message",
            "sender": "system",
            "sender_id": "system",
            "sender_name": "用药提醒",
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "group_id": user.group_id,
        }
        await manager.broadcast_to_group(user.group_id, message, db)
        logger.warning(f"未确认用药通知({stage})：{user.username} {drug_name} @ {plan_time}")

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
