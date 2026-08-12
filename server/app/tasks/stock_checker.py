# -*- coding: utf-8 -*-
"""
定时任务：每天扫描低库存药品并推送通知
使用 AsyncIOScheduler，任务函数为 async，可直接 await 异步通知。
使用 join 查询消除 N+1；基于 last_notified_at 去重，每条计划每天最多通知一次。

重要修复（v2.38.6）：
原 check_low_stock_job / check_missed_medication_job 是 async 函数，却直接在
asyncio 主事件循环上调用同步 SQLAlchemy 的 db.query()/db.commit()。这些同步 DB 调用
不会让出事件循环，导致后台任务在事件循环线程上串行执行成千上万次 commit，期间所有
HTTP 请求（设备注册、TOTP、登录等）被卡住排队，表现为全局 14s+ 超时。
现把「查 + 写」的同步部分抽成独立函数，通过 run_in_threadpool 在后台线程执行，
仅在事件循环线程发出异步通知，从而彻底释放事件循环。
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
from datetime import datetime, timezone, timedelta

from fastapi.concurrency import run_in_threadpool
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


def _collect_low_stock(db):
    """同步扫描低库存计划，更新通知时间并提交，返回需通知列表。

    设计为在 run_in_threadpool 中执行，避免长循环里的同步 DB 写阻塞事件循环。
    不在此函数内做异步通知，通知统一由 async 包装函数在事件循环线程发出。
    """
    rows = (
        db.query(MedicationPlan, User)
        .join(User, MedicationPlan.user_id == User.id)
        .filter(
            User.role == "elderly",
            MedicationPlan.remaining_quantity <= MedicationPlan.low_stock_threshold,
        )
        .all()
    )
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    to_notify = []
    for plan, elderly in rows:
        last = plan.last_notified_at
        if last is not None:
            # 统一转换为 naive UTC 后比较（对 naive 无副作用，对 aware 安全）
            last_naive = last.replace(tzinfo=None)
            if now_naive - last_naive < _NOTIFY_INTERVAL:
                continue
        # 更新通知时间并提交（同步写，运行在后台线程，不阻塞事件循环）
        plan.last_notified_at = datetime.now(timezone.utc)
        db.commit()
        to_notify.append(
            (elderly.id, plan.drug_name, plan.remaining_quantity, plan.low_stock_threshold)
        )
    logger.info(
        f"低库存检查扫描完成，候选 {len(rows)} 条，待通知 {len(to_notify)} 条"
    )
    return to_notify


async def check_low_stock_job():
    """
    定时任务：检查所有老人的低库存药品并发送通知（建议每天凌晨 2:00 执行）

    DB 查询/写入通过 run_in_threadpool 在后台线程执行，不阻塞事件循环，
    避免后台任务占用主循环导致所有 HTTP 请求排队超时。
    """
    logger.info("开始执行低库存检查任务...")
    db = SessionLocal()
    try:
        to_notify = await run_in_threadpool(_collect_low_stock, db)
        for elderly_id, drug_name, remaining, threshold in to_notify:
            try:
                await notifier.notify_low_stock(
                    db, elderly_id, drug_name, remaining, threshold
                )
                logger.info(f"检测到低库存：用户 {elderly_id} 的 {drug_name} 剩余 {remaining}")
            except Exception as e:
                logger.error(f"低库存通知失败(用户 {elderly_id}): {e}")
        logger.info(f"低库存检查任务结束，本次通知 {len(to_notify)} 条")
    except Exception as e:
        logger.error(f"低库存检查任务出错: {e}")
    finally:
        await run_in_threadpool(db.close)


def _collect_missed(db):
    """同步扫描漏服计划，写入 missed 记录并提交，返回需通知列表。

    在 run_in_threadpool 中执行，避免长循环里的同步 DB 写阻塞事件循环。
    """
    plans = (
        db.query(MedicationPlan)
        .join(User, MedicationPlan.user_id == User.id)
        .filter(User.role == "elderly")
        .all()
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    to_notify = []
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
                to_notify.append((plan.user_id, plan.drug_name, sched.isoformat()))
    logger.info(f"漏服检查扫描完成，本次待通知 {len(to_notify)} 条")
    return to_notify


async def check_missed_medication_job():
    """定时任务：扫描已过点且未服药的计划，标记漏服并通知家属（修复缺口②）

    每 5 分钟执行一次；对同一 plan_id+scheduled_time 仅通知一次（置 missed 后跳过）。
    DB 查询/写入通过 run_in_threadpool 在后台线程执行，不阻塞事件循环，
    避免后台任务占用主循环导致所有 HTTP 请求排队超时。
    """
    logger.info("开始执行漏服检查任务...")
    db = SessionLocal()
    try:
        to_notify = await run_in_threadpool(_collect_missed, db)
        for user_id, drug_name, sched_iso in to_notify:
            try:
                await notifier.notify_missed_medication(
                    db, user_id, drug_name, sched_iso
                )
                logger.info(f"漏服通知：用户 {user_id} 的 {drug_name} @ {sched_iso}")
            except Exception as e:
                logger.error(f"漏服通知失败(用户 {user_id}): {e}")
        logger.info(f"漏服检查任务结束，本次通知 {len(to_notify)} 条")
    except Exception as e:
        logger.error(f"漏服检查任务出错: {e}")
    finally:
        await run_in_threadpool(db.close)


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
