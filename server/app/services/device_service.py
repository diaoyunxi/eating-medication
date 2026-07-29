# -*- coding: utf-8 -*-
"""设备服务：封装老人端设备相关的业务逻辑。

从 public.py 抽离的纯逻辑（设备身份解析、注册/心跳、下线、状态计算、图片上传、
服药确认处理），路由层（public.py）仅负责 I/O（请求模型、Header、响应），便于单测。

风格对齐 medication_service：业务逻辑以 ``@staticmethod`` 暴露，``db`` 为首个参数；
异步方法内需要 WebSocket 通知时懒导入 notifier，避免循环依赖与启动期副作用。
"""
import base64
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.security import hash_password, mask_device_id
from app.utils.datetime_utils import hhmm_to_today
from app.models.chat_message import ChatMessage
from app.models.medication_plan import MedicationPlan
from app.models.medication_record import MedicationRecord
from app.models.user import User
from app.schemas.medication import TakeMedicationRequest
from app.services.medication_service import MedicationService

logger = logging.getLogger(__name__)

# 设备上传图片保存根目录（位于 server/data/uploads，已被 .gitignore 忽略）
_UPLOAD_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "uploads")
)


def _parse_dt(s):
    """宽松解析 ISO 时间字符串为 naive datetime，失败返回 None"""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None

def _match_plans_by_drug(db, user, drug_name, now_dt):
    """兼容旧版设备：仅传 drug_name 时，按药名+时间窗口匹配本用户计划"""
    if not drug_name:
        return []
    plans = db.query(MedicationPlan).filter(MedicationPlan.user_id == user.id).all()
    matched = []
    for p in plans:
        if p.drug_name != drug_name:
            continue
        for t in p.schedule_times:
            sched = hhmm_to_today(t, now_dt)
            if sched and abs((now_dt - sched).total_seconds()) <= 90 * 60:
                matched.append({
                    "plan_id": p.id,
                    "drug_name": p.drug_name,
                    "scheduled_time": t,
                })
    return matched


class DeviceService:
    """设备相关业务逻辑。"""

    @staticmethod
    def get_device_user(db: Session, device_id: str) -> User:
        """查找设备对应的真实用户

        优先按 User.device_id 字段查找（真实老人，家属绑定后关联），
        回退按 User.username == device_id 查找（兼容旧虚拟用户）。

        :raises HTTPException: 设备未注册时抛 404
        """
        user = db.query(User).filter(User.device_id == device_id).first()
        if user:
            return user
        user = db.query(User).filter(User.username == device_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="设备未注册")
        return user

    @staticmethod
    def get_device_user_authed(
        db: Session, device_id: str, device_token: Optional[str]
    ) -> User:
        """查找设备用户并校验 X-Device-Token

        无 token 的设备拒绝访问（不再放行旧数据兼容）；令牌不匹配返回 403。

        :raises HTTPException: 设备未注册(404) 或令牌缺失/不匹配(403)
        """
        user = DeviceService.get_device_user(db, device_id)
        if not user.device_token:
            raise HTTPException(
                status_code=403,
                detail="设备未初始化令牌，请联系家属重新绑定设备"
            )
        if not device_token or not secrets.compare_digest(user.device_token, device_token):
            raise HTTPException(status_code=403, detail="设备令牌无效或缺失")
        return user

    @staticmethod
    def register_or_heartbeat(
        db: Session, device_id: str, device_name: Optional[str] = None
    ):
        """设备注册 / 心跳上报

        返回 ``(user, device_token)``：
        - 首次注册（均找不到）创建虚拟用户并返回新生成的 device_token；
        - 已注册设备更新心跳，不返回 token（防止通过 register 枚举已注册设备令牌）。

        查找逻辑：优先 device_id 字段，回退 username（旧虚拟用户）。
        """
        _masked = mask_device_id(device_id or "")
        logger.info(f"设备注册/心跳: {_masked}")

        user = db.query(User).filter(User.device_id == device_id).first()
        if not user:
            user = db.query(User).filter(User.username == device_id).first()

        if not user:
            # 都找不到，创建虚拟用户（待家属后续绑定到真实老人）
            device_token = secrets.token_urlsafe(32)
            user = User(
                username=device_id,
                hashed_password=hash_password(secrets.token_urlsafe(32)),
                role="elderly",
                last_heartbeat_at=datetime.now(timezone.utc),
                device_token=device_token,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"自动创建设备用户（待绑定）: {_masked}")
            return user, device_token

        # 已注册设备 - 心跳上报
        user.last_heartbeat_at = datetime.now(timezone.utc)
        # 已注册设备不再返回 device_token，防止攻击者通过 /device/register 枚举
        # device_id 获取已有设备的访问令牌。若旧用户尚无 device_token，自动生成但不返回。
        if not user.device_token:
            user.device_token = secrets.token_urlsafe(32)
            logger.warning(f"旧设备无 token，已自动生成（需家属重新绑定）: {_masked}")
        db.commit()
        logger.info(f"设备心跳更新: {_masked}")
        return user, None

    @staticmethod
    def mark_offline(db: Session, user: User):
        """设备主动下线：将 last_heartbeat_at 置为很早时间，使在线判断立即为 false。

        设备正常退出时调用，避免子女端在心跳超时窗口内看到虚假"在线"；
        掉电/SIGKILL 等异常退出仍依赖心跳超时判定。
        """
        _masked = mask_device_id(user.device_id or user.username or "")
        user.last_heartbeat_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        db.commit()
        logger.info(f"设备已标记离线: {_masked}")

    @staticmethod
    def compute_status(db: Session, user: User, device_id: str) -> dict:
        """计算设备状态信息（供子女端查询）

        兼容两类历史问题：设备-用户关联（真实老人 / 旧虚拟用户）、
        SQLite 不保留时区导致取出的 datetime 需补 UTC 时区。
        """
        total_plans = db.query(MedicationPlan).filter(MedicationPlan.user_id == user.id).count()
        total_records = db.query(MedicationRecord).filter(MedicationRecord.user_id == user.id).count()

        now = datetime.now(timezone.utc)
        is_online = False
        last_heartbeat = None
        if user.last_heartbeat_at:
            heartbeat = user.last_heartbeat_at
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
            last_heartbeat = heartbeat.isoformat()
            time_diff = (now - heartbeat).total_seconds()
            is_online = time_diff <= 60

        resolved_device_id = user.device_id or device_id or user.username
        return {
            "device_id": resolved_device_id,
            "device_name": user.username,
            "role": user.role,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "total_plans": total_plans,
            "total_records": total_records,
            "status": "online" if is_online else "offline",
            "last_heartbeat": last_heartbeat,
            "is_online": is_online,
        }

    @staticmethod
    def get_schedule(db: Session, user: User) -> list:
        """获取设备的用药计划列表（供老人端每分钟轮询）"""
        plans = db.query(MedicationPlan).filter(MedicationPlan.user_id == user.id).all()
        schedules = []
        for plan in plans:
            for time_str in plan.schedule_times:
                schedules.append({
                    "plan_id": plan.id,
                    "drug_name": plan.drug_name,
                    "dosage": plan.dosage,
                    "time": time_str,
                    "frequency": plan.frequency,
                    "remaining_quantity": plan.remaining_quantity,
                    "unit": plan.unit,
                })
        return schedules

    @staticmethod
    def get_plans(db: Session, user: User) -> list:
        """获取设备的所有用药计划（供子女端查看）"""
        plans = MedicationService.get_plans_by_user(db, user.id)
        return [
            {
                "id": p.id,
                "drug_name": p.drug_name,
                "dosage": p.dosage,
                "frequency": p.frequency,
                "schedule_times": p.schedule_times,
                "total_quantity": p.total_quantity,
                "remaining_quantity": p.remaining_quantity,
                "unit": p.unit,
                "low_stock_threshold": p.low_stock_threshold,
            }
            for p in plans
        ]

    @staticmethod
    def get_records(db: Session, user: User, limit: int = 100) -> list:
        """获取设备的服药记录（限制 limit 范围，防止一次拉取过多）"""
        limit = max(1, min(limit, 500))
        records = (
            db.query(MedicationRecord)
            .filter(MedicationRecord.user_id == user.id)
            .order_by(MedicationRecord.scheduled_time.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "plan_id": r.plan_id,
                "scheduled_time": r.scheduled_time.isoformat() if r.scheduled_time else None,
                "taken_time": r.taken_time.isoformat() if r.taken_time else None,
                "status": r.status,
                "note": r.note,
            }
            for r in records
        ]

    @staticmethod
    def get_chat_history(db: Session, user: User, limit: int = 50) -> list:
        """获取设备相关的聊天历史（供子女端 BFF 调用）"""
        from sqlalchemy import or_

        limit = max(1, min(limit, 200))
        messages = (
            db.query(ChatMessage)
            .filter(
                or_(
                    ChatMessage.sender_id == user.id,
                    ChatMessage.receiver_id == user.id,
                )
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "receiver_id": m.receiver_id,
                "sender_name": m.sender_name,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]

    @staticmethod
    def save_upload(db: Session, user: User, image_base64: str, note: Optional[str] = None) -> str:
        """保存设备上传的服药照片（base64 解码后落盘），返回相对路径。

        校验解码有效性与大小/格式，防止恶意载荷。
        """
        try:
            raw = base64.b64decode(image_base64, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="图片编码无效")
        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="图片过大（上限10MB）")
        if not (raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"\x89PNG")):
            raise HTTPException(status_code=400, detail="仅支持 JPEG/PNG 图片")
        user_dir = os.path.join(_UPLOAD_ROOT, str(user.id))
        os.makedirs(user_dir, exist_ok=True)
        fname = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jpg"
        fpath = os.path.join(user_dir, fname)
        with open(fpath, "wb") as f:
            f.write(raw)
        logger.info(f"设备上传图片已保存: {fpath}")
        return f"uploads/{user.id}/{fname}"

    @staticmethod
    async def handle_medication(db: Session, user: User, data: dict):
        """处理设备上报的服药确认：写入服药记录并实时通知家属（修复缺口①）

        设备优先通过 data.items 携带 plan_id + scheduled_time(HH:MM) 精确匹配；
        旧版设备仅传 drug_name 时，按药名+时间窗口回退匹配。
        """
        taken_dt = _parse_dt(data.get("taken_at")) or datetime.now(timezone.utc).replace(tzinfo=None)
        items = data.get("items") or []
        if not items:
            items = _match_plans_by_drug(db, user, data.get("drug_name", ""), taken_dt)

        if not items:
            # 兜底：无法匹配到计划也至少通知家属，保证反馈闭环
            try:
                from app.websocket.notifier import notifier
                await notifier.notify_taken_medication(
                    db, user.id, data.get("drug_name", "药品"), taken_dt.isoformat()
                )
            except Exception as e:
                logger.error(f"设备服药确认兜底通知失败: {e}")
            return

        for it in items:
            try:
                plan_id = int(it.get("plan_id"))
                sched_raw = it.get("scheduled_time") or data.get("taken_at")
                if isinstance(sched_raw, str) and len(sched_raw) <= 5 and ":" in sched_raw:
                    sched_dt = _hhmm_to_today(sched_raw, taken_dt)
                else:
                    sched_dt = _parse_dt(sched_raw)
                if sched_dt is None:
                    sched_dt = taken_dt
                req_obj = TakeMedicationRequest(
                    plan_id=plan_id,
                    scheduled_time=sched_dt,
                    taken_time=taken_dt,
                )
                await MedicationService.take_medication(db, user.id, req_obj)
            except Exception as e:
                logger.error(f"设备服药确认处理失败(plan_id={it.get('plan_id')}): {e}")
