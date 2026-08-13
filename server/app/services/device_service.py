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
from datetime import datetime, timezone, timedelta
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
    def find_device_accounts(
        db: Session, device_id: str
    ) -> "tuple[Optional[User], Optional[User]]":
        """按 device_id 查找「设备-用户」的两个候选，集中维护查询模式。

        返回 ``(by_device_id_field, by_username)``：
        - by_device_id_field：``User.device_id == device_id`` 命中（已被家属绑定的真实老人）
        - by_username：``User.username == device_id`` 命中（开机注册自动创建的虚拟用户）

        作为 device_id->用户的唯一查询原语，避免各端点重复实现。
        """
        # by_field 仅匹配"设备本人"(role=elderly)，排除被家属绑定后写入 device_id
        # 的家属账号，避免家属账号污染 get_device_user 反查（否则老人端 register/
        # status 会误命中家属账号，导致设备无法找到自身账户）。
        by_field = (
            db.query(User)
            .filter(User.device_id == device_id, User.role == "elderly")
            .first()
        )
        by_name = db.query(User).filter(User.username == device_id).first()
        return by_field, by_name

    @staticmethod
    def get_device_user(db: Session, device_id: str) -> User:
        """查找设备对应的真实用户

        优先按 User.device_id 字段查找（真实老人，家属绑定后关联），
        回退按 User.username == device_id 查找（兼容旧虚拟用户）。

        :raises HTTPException: 设备未注册时抛 404
        """
        by_field, by_name = DeviceService.find_device_accounts(db, device_id)
        user = by_field or by_name
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

        by_field, by_name = DeviceService.find_device_accounts(db, device_id)
        user = by_field or by_name

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
        elderly_ids = DeviceService._group_elderly_ids(db, user)
        total_plans = db.query(MedicationPlan).filter(MedicationPlan.user_id.in_(elderly_ids)).count()
        total_records = db.query(MedicationRecord).filter(MedicationRecord.user_id.in_(elderly_ids)).count()

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
        """获取设备的用药计划列表（供老人端每分钟轮询）

        多老人：聚合设备所属家庭组（group_id）下所有老人的计划，每条附带
        elderly_id / elderly_name / husky_face_id，供老人端拍照前核验身份。
        """
        elderly_ids = DeviceService._group_elderly_ids(db, user)
        elders = {
            e.id: e
            for e in db.query(User).filter(User.id.in_(elderly_ids)).all()
        }
        plans = db.query(MedicationPlan).filter(MedicationPlan.user_id.in_(elderly_ids)).all()
        schedules = []
        for plan in plans:
            owner = elders.get(plan.user_id)
            for time_str in plan.schedule_times:
                schedules.append({
                    "plan_id": plan.id,
                    "elderly_id": plan.user_id,
                    "elderly_name": owner.username if owner else None,
                    "husky_face_id": owner.husky_face_id if owner else None,
                    "drug_name": plan.drug_name,
                    "dosage": plan.dosage,
                    "product_code": plan.product_code,
                    "time": time_str,
                    "frequency": plan.frequency,
                    "remaining_quantity": plan.remaining_quantity,
                    "unit": plan.unit,
                })
        return schedules

    @staticmethod
    def get_plans(db: Session, user: User) -> list:
        """获取设备的所有用药计划（供子女端查看）

        多老人：聚合家庭组下所有老人的计划，并附带所属老人信息。
        """
        elderly_ids = DeviceService._group_elderly_ids(db, user)
        elders = {
            e.id: e
            for e in db.query(User).filter(User.id.in_(elderly_ids)).all()
        }
        plans = db.query(MedicationPlan).filter(MedicationPlan.user_id.in_(elderly_ids)).all()
        return [
            {
                "id": p.id,
                "elderly_id": p.user_id,
                "elderly_name": elders.get(p.user_id).username if elders.get(p.user_id) else None,
                "drug_name": p.drug_name,
                "dosage": p.dosage,
                "product_code": p.product_code,
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
        """获取设备的服药记录（限制 limit 范围，防止一次拉取过多）。

        返回字段对齐子女端 records.html 的真实数据需求：
        medication_name/dosage 取自关联用药计划；
        confirmed 由记录状态推导（已服药即视为已确认）；
        photo 当前未与记录关联，返回 None 以避免虚假显示"有照片"。
        """
        limit = max(1, min(limit, 500))
        elderly_ids = DeviceService._group_elderly_ids(db, user)
        elders = {e.id: e for e in db.query(User).filter(User.id.in_(elderly_ids)).all()}
        rows = (
            db.query(MedicationRecord, MedicationPlan.drug_name, MedicationPlan.dosage)
            .outerjoin(MedicationPlan, MedicationRecord.plan_id == MedicationPlan.id)
            .filter(MedicationRecord.user_id.in_(elderly_ids))
            .order_by(MedicationRecord.scheduled_time.desc())
            .limit(limit)
            .all()
        )
        records = []
        for r, drug_name, dosage in rows:
            owner = elders.get(r.user_id)
            records.append(
                {
                    "id": r.id,
                    "plan_id": r.plan_id,
                    "elderly_id": r.user_id,
                    "elderly_name": owner.username if owner else None,
                    "medication_name": drug_name,
                    "dosage": dosage,
                    "scheduled_time": r.scheduled_time.isoformat() if r.scheduled_time else None,
                    "taken_time": r.taken_time.isoformat() if r.taken_time else None,
                    "status": r.status,
                    "confirmed": r.status == "taken" or r.taken_time is not None,
                    "photo": r.photo,
                    "note": r.note,
                }
            )
        return records

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
    def get_reminders(db: Session, user: User, limit: int = 50) -> list:
        """生成绑定设备的今日服药提醒（供子女端仪表盘）。

        基于用药计划逐个时间点展开，并关联已上报的服药记录标记完成状态。
        字段对齐子女端 get_reminders 的期望：id/plan_id/drug_name/planned_time/
        status/taken_time/note。
        """
        from app.utils.datetime_utils import hhmm_to_today
        from datetime import datetime as _dt

        limit = max(1, min(limit, 200))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # 今日零点，用于只索引"今天"的服药记录，避免把历史全部记录载入内存
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elderly_ids = DeviceService._group_elderly_ids(db, user)
        elders = {e.id: e for e in db.query(User).filter(User.id.in_(elderly_ids)).all()}
        plans = db.query(MedicationPlan).filter(MedicationPlan.user_id.in_(elderly_ids)).all()
        # 已上报记录按 (plan_id, 计划时点) 建索引，便于匹配完成状态；
        # 仅取 today 起的记录（scheduled_time 由 hhmm_to_today 生成为今日时点）
        records = (
            db.query(MedicationRecord)
            .filter(
                MedicationRecord.user_id.in_(elderly_ids),
                MedicationRecord.scheduled_time >= today_start,
            )
            .all()
        )
        record_index = {}
        for r in records:
            key = (r.plan_id, (r.scheduled_time.strftime("%H:%M") if r.scheduled_time else ""))
            record_index[key] = r

        reminders = []
        rid = 0
        for plan in plans:
            for time_str in plan.schedule_times:
                scheduled = hhmm_to_today(time_str, now)
                rid += 1
                rec = record_index.get((plan.id, time_str))
                owner = elders.get(plan.user_id)
                reminders.append({
                    "id": rid,
                    "plan_id": plan.id,
                    "elderly_id": plan.user_id,
                    "elderly_name": owner.username if owner else None,
                    "drug_name": plan.drug_name,
                    "dosage": plan.dosage,
                    "planned_time": scheduled.isoformat() if scheduled else None,
                    "status": rec.status if rec else "pending",
                    "taken_time": rec.taken_time.isoformat() if rec and rec.taken_time else None,
                    "note": rec.note if rec else None,
                })
        # 按计划时点排序，限制数量
        reminders.sort(key=lambda x: x["planned_time"] or "")
        return reminders[:limit]

    @staticmethod
    def photo_abs_path(photo_rel: str) -> str:
        """将记录中存储的相对路径（uploads/{user_id}/{filename}.jpg）换算为磁盘绝对路径。"""
        return os.path.join(os.path.dirname(_UPLOAD_ROOT), photo_rel)

    @staticmethod
    def save_upload(
        db: Session,
        user: User,
        image_base64: str,
        note: Optional[str] = None,
        plan_id: Optional[int] = None,
        scheduled_time: Optional[str] = None,
        elderly_id: Optional[int] = None,
    ) -> str:
        """保存设备上传的服药照片（base64 解码后落盘），并将照片关联到对应服药记录。

        校验解码有效性与大小/格式，防止恶意载荷。
        关联策略：
        1. 若上传携带 plan_id + scheduled_time（设备确认时附带的服药标识），精确匹配记录；
        2. 否则回退：关联最近一条已服药（taken_time 在 10 分钟内）且尚无照片的记录，
           避免照片游离、无法在网页端展示。
        """
        # 兼容带 data URI 前缀的 base64（设备客户端可能附带 "data:image/jpeg;base64,"）
        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]
        try:
            raw = base64.b64decode(image_base64, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="图片编码无效")
        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="图片过大（上限10MB）")
        if not (raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"\x89PNG")):
            raise HTTPException(status_code=400, detail="仅支持 JPEG/PNG 图片")
        # 多老人：照片归属到具体老人（elderly_id 指定），默认回退设备主体用户
        owner = DeviceService._resolve_elderly(db, user, elderly_id)
        owner_id = owner.id
        user_dir = os.path.join(_UPLOAD_ROOT, str(owner_id))
        os.makedirs(user_dir, exist_ok=True)
        # 使用排他创建模式（O_EXCL），防止并发上传时覆盖既有照片
        for _ in range(3):  # 最多重试 3 次，应对极端碰撞
            fname = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}_{secrets.token_hex(4)}.jpg"
            fpath = os.path.join(user_dir, fname)
            try:
                fd = os.open(fpath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                with os.fdopen(fd, "wb") as f:
                    f.write(raw)
                break
            except FileExistsError:
                logger.warning(f"文件名冲突，重试: {fname}")
                continue
        else:
            raise HTTPException(status_code=500, detail="上传图片失败：文件名碰撞次数过多")
        logger.info(f"设备上传图片已保存: {fpath}")
        rel_path = f"uploads/{owner_id}/{fname}"

        # ---- 关联照片到服药记录 ----
        rec = None
        if plan_id:
            try:
                pid = int(plan_id)
                sched_dt = None
                if scheduled_time and len(str(scheduled_time)) <= 5 and ":" in str(scheduled_time):
                    sched_dt = hhmm_to_today(str(scheduled_time))
                if sched_dt is not None:
                    rec = (
                        db.query(MedicationRecord)
                        .filter(
                            MedicationRecord.user_id == owner_id,
                            MedicationRecord.plan_id == pid,
                            MedicationRecord.scheduled_time == sched_dt,
                        )
                        .first()
                    )
            except Exception as e:
                logger.warning(f"按 plan_id 关联照片失败：{e}")
                rec = None
        if rec is None:
            # 回退：最近一条已服药且在 10 分钟内、尚无照片的记录
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
            rec = (
                db.query(MedicationRecord)
                .filter(
                    MedicationRecord.user_id == owner_id,
                    MedicationRecord.taken_time != None,
                    MedicationRecord.taken_time >= cutoff,
                    MedicationRecord.photo == None,
                )
                .order_by(MedicationRecord.taken_time.desc())
                .first()
            )
        if rec is not None:
            rec.photo = rel_path
            db.commit()

        return rel_path

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
                # 多老人：记录归属到具体老人（elderly_id 指定），默认回退设备主体用户
                owner = DeviceService._resolve_elderly(
                    db, user, it.get("elderly_id") if isinstance(it, dict) else None
                )
                sched_raw = it.get("scheduled_time") or data.get("taken_at")
                if isinstance(sched_raw, str) and len(sched_raw) <= 5 and ":" in sched_raw:
                    sched_dt = hhmm_to_today(sched_raw, taken_dt)
                else:
                    sched_dt = _parse_dt(sched_raw)
                if sched_dt is None:
                    sched_dt = taken_dt
                req_obj = TakeMedicationRequest(
                    plan_id=plan_id,
                    scheduled_time=sched_dt,
                    taken_time=taken_dt,
                )
                await MedicationService.take_medication(db, owner.id, req_obj)
            except Exception as e:
                logger.error(f"设备服药确认处理失败(plan_id={it.get('plan_id')}): {e}")

    @staticmethod
    def _group_elderly_ids(db: Session, user: User) -> list:
        """返回设备所属家庭组（group_id）下所有老人的 user_id 列表

        设备主体用户（持有 device_id/device_token）与额外老人共享 group_id；
        多老人下，设备的计划/记录/提醒均按此列表聚合。
        """
        if user.group_id is None:
            return [user.id]
        ids = [
            u[0]
            for u in db.query(User.id)
            .filter(User.group_id == user.group_id, User.role == "elderly")
            .all()
        ]
        return ids or [user.id]

    @staticmethod
    def _resolve_elderly(db: Session, device_user: User, elderly_id: Optional[int]) -> User:
        """解析服药/照片归属的老人用户

        elderly_id 为空或非法时回退到设备主体用户（单老人兼容）；
        elderly_id 必须属于同一家庭组，否则拒绝写入（防止越权写入他人记录）。
        """
        if elderly_id:
            # 未加入家庭组的设备（group_id 为 NULL）只能操作自身，禁止通过传入其他
            # group_id 同样为 NULL 的老人 ID 越权访问他人记录。
            if device_user.group_id is None:
                if int(elderly_id) == device_user.id:
                    return device_user
                raise HTTPException(
                    status_code=403,
                    detail="设备未加入家庭组，仅可操作自身记录",
                )
            target = db.query(User).filter(
                User.id == elderly_id,
                User.role == "elderly",
                User.group_id == device_user.group_id,
            ).first()
            if target:
                return target
            raise HTTPException(
                status_code=403,
                detail="老人ID不属于当前设备家庭组，拒绝写入",
            )
        return device_user


