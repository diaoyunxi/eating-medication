# -*- coding: utf-8 -*-
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
from app.models.user import User
from app.models.medication_plan import MedicationPlan
from app.models.medication_record import MedicationRecord
from app.schemas.medication import MedicationPlanCreate, TakeMedicationRequest

class MedicationService:
    """用药管理服务"""

    @staticmethod
    def create_plan(db: Session, user_id: int, plan_data: MedicationPlanCreate) -> MedicationPlan:
        """创建用药计划"""
        plan = MedicationPlan(
            user_id=user_id,
            drug_name=plan_data.drug_name,
            dosage=plan_data.dosage,
            frequency=plan_data.frequency,
            schedule_times=plan_data.schedule_times,
            total_quantity=plan_data.total_quantity,
            remaining_quantity=plan_data.remaining_quantity,
            unit=plan_data.unit,
            low_stock_threshold=plan_data.low_stock_threshold,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        return plan

    @staticmethod
    def get_plans_by_user(db: Session, user_id: int) -> List[MedicationPlan]:
        """获取老人的所有用药计划"""
        return db.query(MedicationPlan).filter(MedicationPlan.user_id == user_id).all()

    @staticmethod
    def get_plans_for_family(db: Session, group_id: int) -> List[MedicationPlan]:
        """获取家庭组所有老人的用药计划"""
        elderly_users = db.query(User).filter(User.group_id == group_id, User.role == "elderly").all()
        elderly_ids = [u.id for u in elderly_users]
        if not elderly_ids:
            return []
        return db.query(MedicationPlan).filter(MedicationPlan.user_id.in_(elderly_ids)).all()

    @staticmethod
    def take_medication(db: Session, user_id: int, req: TakeMedicationRequest) -> MedicationRecord:
        """记录服药并扣减库存"""
        plan = db.query(MedicationPlan).filter(
            MedicationPlan.id == req.plan_id,
            MedicationPlan.user_id == user_id
        ).first()
        if not plan:
            raise ValueError("用药计划不存在或不属于当前用户")

        record = MedicationRecord(
            user_id=user_id,
            plan_id=req.plan_id,
            scheduled_time=req.scheduled_time,
            taken_time=req.taken_time,
            status="taken",
        )
        db.add(record)

        if plan.remaining_quantity > 0:
            plan.remaining_quantity -= 1.0
            plan.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def get_history(
        db: Session,
        current_user: User,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[MedicationRecord]:
        """获取服药历史"""
        query = db.query(MedicationRecord)

        if current_user.role == "elderly":
            query = query.filter(MedicationRecord.user_id == current_user.id)
        elif current_user.role == "family" and current_user.group_id:
            elderly_users = db.query(User).filter(User.group_id == current_user.group_id, User.role == "elderly").all()
            elderly_ids = [u.id for u in elderly_users]
            if elderly_ids:
                query = query.filter(MedicationRecord.user_id.in_(elderly_ids))
            else:
                return []
        else:
            return []

        if start:
            query = query.filter(MedicationRecord.scheduled_time >= start)
        if end:
            query = query.filter(MedicationRecord.scheduled_time <= end)

        return query.order_by(MedicationRecord.scheduled_time.desc()).all()