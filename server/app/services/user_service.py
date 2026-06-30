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