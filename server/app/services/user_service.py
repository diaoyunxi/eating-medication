# -*- coding: utf-8 -*-
from sqlalchemy.orm import Session
from typing import Optional, List
from app.models.user import User
from app.schemas.user import UserUpdate

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

        if update_data.full_name is not None:
            user.full_name = update_data.full_name
        if update_data.phone is not None:
            user.phone = update_data.phone

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def bind_family(db: Session, elderly_user_id: int, family_user_id: int) -> Optional[int]:
        """将家属绑定到老人的家庭组，返回 group_id"""
        elderly = db.query(User).filter(User.id == elderly_user_id, User.role == "elderly").first()
        family = db.query(User).filter(User.id == family_user_id, User.role == "family").first()

        if not elderly or not family:
            return None

        if elderly.group_id is None:
            elderly.group_id = elderly.id
            db.commit()

        family.group_id = elderly.group_id
        db.commit()

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