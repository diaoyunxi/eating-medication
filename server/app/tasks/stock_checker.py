# -*- coding: utf-8 -*-
"""
定时任务：每天扫描低库存药品并推送通知
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.medication_plan import MedicationPlan
from app.models.user import User
from app.websocket.notifier import notifier

logger = logging.getLogger(__name__)

# 全局调度器实例
scheduler = BackgroundScheduler()

def check_low_stock_job():
    """
    定时任务：检查所有老人的低库存药品并发送通知
    建议每天凌晨 2:00 执行
    """
    logger.info("开始执行低库存检查任务...")
    db = SessionLocal()
    try:
        # 获取所有老人用户
        elderly_users = db.query(User).filter(User.role == "elderly").all()
        
        for elderly in elderly_users:
            # 查询该老人的所有用药计划
            plans = db.query(MedicationPlan).filter(MedicationPlan.user_id == elderly.id).all()
            
            for plan in plans:
                if plan.remaining_quantity <= plan.low_stock_threshold:
                    # 发送低库存通知
                    import asyncio
                    asyncio.create_task(
                        notifier.notify_low_stock(
                            db,
                            elderly.id,
                            plan.drug_name,
                            plan.remaining_quantity,
                            plan.low_stock_threshold
                        )
                    )
                    logger.info(f"检测到低库存：用户 {elderly.id} 的 {plan.drug_name} 剩余 {plan.remaining_quantity}")
        
        logger.info("低库存检查任务完成")
    except Exception as e:
        logger.error(f"低库存检查任务出错: {e}")
    finally:
        db.close()

def start_scheduler():
    """启动后台定时任务调度器"""
    if not scheduler.running:
        # 每天凌晨 2:00 执行一次
        scheduler.add_job(
            check_low_stock_job,
            trigger=CronTrigger(hour=2, minute=0),
            id="low_stock_check",
            name="低库存检查",
            replace_existing=True
        )
        scheduler.start()
        logger.info("定时任务调度器已启动，低库存检查将在每天 02:00 执行")

def shutdown_scheduler():
    """关闭定时任务调度器"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("定时任务调度器已关闭")