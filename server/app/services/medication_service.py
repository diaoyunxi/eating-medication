# -*- coding: utf-8 -*-
import asyncio
import logging
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from app.models.user import User
from app.models.medication_plan import MedicationPlan
from app.models.medication_record import MedicationRecord
from app.schemas.medication import MedicationPlanCreate, TakeMedicationRequest

logger = logging.getLogger(__name__)

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
        """记录服药并扣减库存（H9：原子扣减 + 去重 + 状态计算）"""
        from sqlalchemy import update

        plan = db.query(MedicationPlan).filter(
            MedicationPlan.id == req.plan_id,
            MedicationPlan.user_id == user_id
        ).first()
        if not plan:
            raise ValueError("用药计划不存在或不属于当前用户")

        # H9：按 plan_id + scheduled_time 去重，已存在则更新而非新建
        existing_record = db.query(MedicationRecord).filter(
            MedicationRecord.plan_id == req.plan_id,
            MedicationRecord.scheduled_time == req.scheduled_time,
        ).first()

        # H9：根据 taken_time 与 scheduled_time 计算 status
        # F3 修复：统一使用 naive UTC 比较，避免 aware/naive 混用导致 TypeError
        if req.taken_time is None:
            # 未确认服药，超过计划时间 30 分钟则记为漏服
            # F3 修复：将 scheduled_time 统一转为 naive UTC，避免 aware/naive 混用导致 TypeError
            threshold = req.scheduled_time
            if threshold.tzinfo is not None:
                threshold = threshold.replace(tzinfo=None)
            threshold = threshold + timedelta(minutes=30)
            now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
            status = "missed" if now_naive > threshold else "pending"
        else:
            status = "taken"

        if existing_record:
            existing_record.taken_time = req.taken_time
            existing_record.status = status
            record = existing_record
        else:
            record = MedicationRecord(
                user_id=user_id,
                plan_id=req.plan_id,
                scheduled_time=req.scheduled_time,
                taken_time=req.taken_time,
                status=status,
            )
            db.add(record)

        # H9/O10：仅在确实服药时原子扣减库存，避免并发超扣
        # 事务边界：record 的 add 与库存扣减在同一事务内，扣减失败 rollback 会一并回滚 record
        if status == "taken":
            result = db.execute(
                update(MedicationPlan)
                .where(
                    MedicationPlan.id == req.plan_id,
                    MedicationPlan.remaining_quantity >= 1,
                )
                .values(remaining_quantity=MedicationPlan.remaining_quantity - 1)
            )
            if result.rowcount == 0:
                # 库存不足或计划不存在，回滚本次记录（O10：确保记录与扣减原子一致）
                db.rollback()
                raise ValueError("库存不足，无法扣减")

        db.commit()
        db.refresh(record)

        # 服药后通知家属（仅在确实服药时）
        if status == "taken":
            try:
                from app.websocket.notifier import notifier
                taken_time_str = record.taken_time.isoformat() if record.taken_time else None
                asyncio.run(notifier.notify_taken_medication(db, user_id, plan.drug_name, taken_time_str))
            except Exception as e:
                logger.error(f"服药通知发送失败: {e}")

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