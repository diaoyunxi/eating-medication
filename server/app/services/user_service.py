# -*- coding: utf-8 -*-
"""
用户服务层

提供用户管理、家庭组绑定、设备-老人关联等核心业务逻辑。
"""
import json
import logging
from sqlalchemy.orm import Session
from typing import Optional, List
from app.models.user import User
from app.models.medication_plan import MedicationPlan
from app.models.medication_record import MedicationRecord
from app.models.ai_query_log import AIQueryLog
from app.models.chat_message import ChatMessage
from app.schemas.user import UserUpdate, NotificationSettings

logger = logging.getLogger(__name__)


class UserService:
    """用户服务"""

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
        """根据ID获取用户"""
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def update_user(db: Session, user_id: int, update_data: UserUpdate) -> Optional[User]:
        """更新用户信息"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None

        if update_data.username is not None:
            user.username = update_data.username
        if update_data.phone is not None:
            user.phone = update_data.phone

        # 通知偏好设置：合并默认值后整体保存为 JSON 字符串（白名单内的布尔键）
        if update_data.notification_settings is not None:
            ns = update_data.notification_settings
            if not isinstance(ns, dict):
                raise ValueError("notification_settings 必须是对象")
            merged = NotificationSettings(
                **{k: bool(v) for k, v in ns.items() if k in NotificationSettings.model_fields}
            )
            user.notification_settings = json.dumps(merged.model_dump(), ensure_ascii=False)

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def _migrate_virtual_user_data(db: Session, virtual_user: User, real_elderly: User) -> None:
        """将虚拟用户（device/register 自动创建）的数据迁移到真实老人

        迁移范围：
        - medication_plans（用药计划）
        - medication_records（服药记录）
        - ai_query_logs（AI 查询日志）
        - chat_messages（聊天消息：sender_id 或 receiver_id）

        :param db: 数据库会话
        :param virtual_user: 虚拟用户（待删除）
        :param real_elderly: 真实老人（数据接收方）
        """
        virtual_id = virtual_user.id
        real_id = real_elderly.id

        # 用药计划
        plans_migrated = db.query(MedicationPlan).filter(
            MedicationPlan.user_id == virtual_id
        ).update({MedicationPlan.user_id: real_id})
        # 服药记录
        records_migrated = db.query(MedicationRecord).filter(
            MedicationRecord.user_id == virtual_id
        ).update({MedicationRecord.user_id: real_id})
        # AI 查询日志
        logs_migrated = db.query(AIQueryLog).filter(
            AIQueryLog.user_id == virtual_id
        ).update({AIQueryLog.user_id: real_id})
        # 聊天消息（sender 或 receiver 是虚拟用户）
        chat_migrated = db.query(ChatMessage).filter(
            ChatMessage.sender_id == virtual_id
        ).update({ChatMessage.sender_id: real_id})
        chat_migrated += db.query(ChatMessage).filter(
            ChatMessage.receiver_id == virtual_id
        ).update({ChatMessage.receiver_id: real_id})

        logger.info(
            "虚拟用户数据迁移完成: virtual_id=%s -> real_id=%s, "
            "plans=%s, records=%s, ai_logs=%s, chat_msgs=%s",
            virtual_id, real_id,
            plans_migrated, records_migrated, logs_migrated, chat_migrated
        )

    @staticmethod
    def bind_family(
        db: Session,
        elderly_user_id: int,
        family_user_id: int,
        device_id: Optional[str] = None,
    ) -> Optional[int]:
        """将家属绑定到老人的家庭组，并关联设备到真实老人

        修复"设备即用户"设计缺陷的核心逻辑：
        1. 校验真实老人和家属存在且角色正确
        2. 如果传入 device_id：
           a. 校验 device_id 未被其他老人占用
           b. 如果 device_id 对应一个虚拟用户（username == device_id 且 device_id 字段为空），
              把虚拟用户的数据迁移到真实老人，然后删除虚拟用户
           c. 把 device_id 关联到真实老人（elderly.device_id = device_id）
        3. 老人未成组时以自身 ID 作为 group_id，家属加入该组

        :param db: 数据库会话
        :param elderly_user_id: 真实老人用户 ID
        :param family_user_id: 家属用户 ID
        :param device_id: 设备 ID（可选，传入则关联到真实老人）
        :return: 家庭组 group_id，失败返回 None
        """
        elderly = db.query(User).filter(User.id == elderly_user_id, User.role == "elderly").first()
        family = db.query(User).filter(User.id == family_user_id, User.role == "family").first()

        if not elderly or not family:
            return None

        # 设备关联逻辑
        if device_id:
            # 校验 device_id 未被其他老人占用
            # 注意：家属账号也会复用 User.device_id 字段持有设备关联（见 /family/device/bind），
            # 因此这里必须限定 role=="elderly"，否则会把家属误判为「设备已绑定其他用户」而拒绝，
            # 导致绑定设备后无法建立家庭组（表现为「添加老人」报 尚未绑定老人/设备）。
            existing = db.query(User).filter(
                User.device_id == device_id, User.role == "elderly"
            ).first()
            if existing and existing.id != elderly.id:
                logger.warning(
                    "设备ID已被其他老人占用: device_id=%s, existing_elderly_id=%s",
                    device_id, existing.id
                )
                return None

            # 如果 device_id 对应一个虚拟用户（username == device_id），迁移数据并删除
            virtual_user = db.query(User).filter(
                User.username == device_id,
                User.device_id.is_(None),
                User.id != elderly.id,
            ).first()
            if virtual_user:
                logger.info(
                    "发现虚拟用户，开始迁移: virtual_id=%s, device_id=%s, real_elderly_id=%s",
                    virtual_user.id, device_id, elderly.id
                )
                UserService._migrate_virtual_user_data(db, virtual_user, elderly)
                # 删除虚拟用户（不会触发级联删除，因为数据已迁移）
                db.delete(virtual_user)
                # 移除中间 commit，统一在方法末尾提交，保证单一事务

            # 把 device_id 关联到真实老人
            elderly.device_id = device_id
            # 如果老人 username 还是默认值，可考虑同步更新为更友好的标识
            # （这里保持原 username 不变，避免破坏老人登录）

        # 家庭组绑定（原有逻辑）
        if elderly.group_id is None:
            elderly.group_id = elderly.id
            # 移除中间 commit，统一在方法末尾提交

        family.group_id = elderly.group_id
        # 单一事务，仅在方法末尾 commit 一次，异常时回滚
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

        return elderly.group_id

    @staticmethod
    def get_family_members(db: Session, group_id: int) -> List[User]:
        """获取家庭组所有成员"""
        return db.query(User).filter(User.group_id == group_id).all()

    @staticmethod
    def delete_user(db: Session, user_id: int) -> bool:
        """
        硬删除指定用户

        会触发级联删除（MedicationPlan / MedicationRecord / AIQueryLog，
        依据 User 模型 relationship 的 cascade="all, delete-orphan" 配置），
        删除后不可恢复。

        :param db: 数据库会话
        :param user_id: 待删除用户 ID
        :return: True 删除成功，False 用户不存在
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        db.delete(user)
        db.commit()
        return True

    @staticmethod
    def create_elderly(db: Session, name: str, group_id: int) -> User:
        """家属创建同家庭组的老人账号（网页「增加老年人」，无需老人自行注册）

        创建的老人 username=姓名，无密码（OAuth 式），不持有 device_id（设备鉴权由
        设备主体用户代理），通过 group_id 与家属、设备主体同组，从而被设备端聚合拉取计划。

        :param db: 数据库会话
        :param name: 老人姓名（作为昵称）
        :param group_id: 家庭组 ID（取自当前登录家属的 group_id）
        :return: 新建的老人 User 对象
        """
        elderly = User(
            username=name,
            hashed_password=None,
            role="elderly",
            group_id=group_id,
            device_id=None,
            pending_learn=False,
            husky_face_id=None,
        )
        db.add(elderly)
        db.commit()
        db.refresh(elderly)
        return elderly

    @staticmethod
    def list_elderly(db: Session, group_id: int) -> List[User]:
        """列出家庭组内所有老人（按 id 升序，保证列表顺序稳定）"""
        return (
            db.query(User)
            .filter(User.group_id == group_id, User.role == "elderly")
            .order_by(User.id)
            .all()
        )

    @staticmethod
    def set_husky_face_id(db: Session, user_id: int, husky_face_id: int) -> Optional[User]:
        """录入人脸完成时回填老人的二哈人脸 ID，并清除待录入标记"""
        user = UserService.get_user_by_id(db, user_id)
        if not user:
            return None
        user.husky_face_id = husky_face_id
        user.pending_learn = False
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def set_pending_learn(db: Session, user_id: int, value: bool) -> Optional[User]:
        """设置/清除老人的待录入人脸标记（家属网页触发录入后置 True）"""
        user = UserService.get_user_by_id(db, user_id)
        if not user:
            return None
        user.pending_learn = value
        db.commit()
        db.refresh(user)
        return user