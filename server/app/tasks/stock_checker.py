# -*- coding: utf-8 -*-
"""
定时任务：每天扫描低库存药品并推送通知
使用 AsyncIOScheduler，任务函数为 async，可直接 await 异步通知。
使用 join 查询消除 N+1；基于 last_notified_at 去重，每条计划每天最多通知一次。
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
from datetime import datetime, timezone, timedelta

from app.core.database import SessionLocal
from app.utils.datetime_utils import hhmm_to_today
from app.models.medication_plan import MedicationPlan
from app.models.medication_record import MedicationRecord
from app.models.user import User
from app.websocket.notifier import notifier

logger = logging.getLogger(__name__)

# 全局调度器实例改用 AsyncIOScheduler
scheduler = AsyncIOScheduler()

# 低库存重复通知间隔（1 天）
_NOTIFY_INTERVAL = timedelta(days=1)


async def check_low_stock_job():
    """
    定时任务：检查所有老人的低库存药品并发送通知
    建议每天凌晨 2:00 执行

    S-05 处理流程：
    (a) 使用 MedicationPlan JOIN User 单次查询，消除 N+1；
    (b) 基于 plan.last_notified_at 去重，仅在未通知或超过 1 天时通知，通知后更新该时间。
    """
    logger.info("开始执行低库存检查任务...")
    db = SessionLocal()
    try:
        # join 查询所有老人低库存计划，消除 N+1
        low_stock_rows = (
            db.query(MedicationPlan, User)
            .join(User, MedicationPlan.user_id == User.id)
            .filter(
                User.role == "elderly",
                MedicationPlan.remaining_quantity <= MedicationPlan.low_stock_threshold,
            )
            .all()
        )

        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        notified_count = 0
        for plan, elderly in low_stock_rows:
            # 去重，仅在未通知或距上次通知超过 1 天时发送
            last = plan.last_notified_at
            if last is not None:
                # 统一转换为 naive UTC 后比较（对 naive 无副作用，对 aware 安全）
                last_naive = last.replace(tzinfo=None)
                if now_naive - last_naive < _NOTIFY_INTERVAL:
                    continue

            # 在异步调度器中直接 await，无需 asyncio.create_task
            await notifier.notify_low_stock(
                db,
                elderly.id,
                plan.drug_name,
                plan.remaining_quantity,
                plan.low_stock_threshold
            )
            # 更新通知时间并提交
            plan.last_notified_at = datetime.now(timezone.utc)
            db.commit()
            notified_count += 1
            logger.info(f"检测到低库存：用户 {elderly.id} 的 {plan.drug_name} 剩余 {plan.remaining_quantity}")

        logger.info(f"低库存检查任务完成，本次通知 {notified_count} 条（候选 {len(low_stock_rows)} 条）")
    except Exception as e:
        logger.error(f"低库存检查任务出错: {e}")
    finally:
        db.close()


async def check_missed_medication_job():
    """定时任务：扫描已过点且未服药的计划，标记漏服并通知家属（修复缺口②）

    每 5 分钟执行一次；对同一 plan_id+scheduled_time 仅通知一次（置 missed 后跳过）。
    """
    logger.info("开始执行漏服检查任务...")
    db = SessionLocal()
    try:
        plans = (
            db.query(MedicationPlan)
            .join(User, MedicationPlan.user_id == User.id)
            .filter(User.role == "elderly")
            .all()
        )
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        missed_count = 0
        for plan in plans:
            for t in plan.schedule_times:
                # 检查今天和昨天的计划时间（修复跨天漏服边界缺陷：00:00-00:30 窗口
                # 可能漏检前一天的 23:00 漏服）
                sched_today = hhmm_to_today(t, now)
                if sched_today is None:
                    continue
                sched_yesterday = sched_today - timedelta(days=1)

                for sched in (sched_yesterday, sched_today):
                    # 仅处理已超过计划时间 30 分钟的时间点；未来时间点跳过
                    if now < sched + timedelta(minutes=30):
                        continue
                    rec = (
                        db.query(MedicationRecord)
                        .filter(
                            MedicationRecord.plan_id == plan.id,
                            MedicationRecord.scheduled_time == sched,
                        )
                        .first()
                    )
                    if rec and rec.status in ("taken", "missed"):
                        continue
                    if rec:
                        rec.status = "missed"
                    else:
                        rec = MedicationRecord(
                            plan_id=plan.id,
                            user_id=plan.user_id,
                            scheduled_time=sched,
                            status="missed",
                        )
                        db.add(rec)
                    db.commit()
                    await notifier.notify_missed_medication(
                        db, plan.user_id, plan.drug_name, sched.isoformat()
                    )
                    missed_count += 1
                    logger.info(f"漏服通知：用户 {plan.user_id} 的 {plan.drug_name} @ {sched}")
        logger.info(f"漏服检查完成，本次通知 {missed_count} 条")
    except Exception as e:
        logger.error(f"漏服检查任务出错: {e}")
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
        # 漏服检查：每 5 分钟执行一次
        scheduler.add_job(
            check_missed_medication_job,
            trigger="interval",
            minutes=5,
            id="missed_medication_check",
            name="漏服检查",
            replace_existing=True
        )
        scheduler.start()
        logger.info("定时任务调度器已启动，低库存检查将在每天 02:00 执行")


def shutdown_scheduler():
    """关闭定时任务调度器"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("定时任务调度器已关闭")
