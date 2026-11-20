# -*- coding: utf-8 -*-
import json
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from datetime import datetime

class NotificationSettings(BaseModel):
    """用户通知偏好设置

    各开关默认：用药提醒/漏服提醒/设备离线/声音 默认开启，浏览器通知默认关闭。
    与设置页五个开关一一对应。
    """
    medication_reminder: bool = True   # 用药提醒通知
    missed_reminder: bool = True       # 漏服提醒通知
    offline_reminder: bool = True       # 设备离线通知
    browser_notification: bool = False  # 浏览器通知
    sound_alert: bool = True            # 声音提醒

    @classmethod
    def from_json(cls, raw: Optional[str]) -> "NotificationSettings":
        """从数据库存储的 JSON 字符串解析；为空或非法时返回默认全开配置"""
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return cls(**{k: bool(v) for k, v in data.items() if k in cls.model_fields})
        except Exception:
            return cls()
        return cls()


class UserOut(BaseModel):
    """用户信息响应"""
    id: int
    username: Optional[str] = None  # 昵称
    role: str
    phone: Optional[str] = None
    email: Optional[str] = None
    group_id: Optional[int] = None
    # 设备ID（老人绑定设备后填充，家属为 None）
    device_id: Optional[str] = None
    # 是否已开启 TOTP 第二因子（前端据此引导动态码输入）
    mfa_enabled: bool = False
    # 通知偏好设置（数据库存 JSON 字符串，响应时解析为 dict；缺失则返回默认）
    notification_settings: Optional[dict] = None
    created_at: datetime

    @field_validator("notification_settings", mode="before")
    @classmethod
    def _parse_notification_settings(cls, v):
        # 数据库返回的是 JSON 字符串，需解析为 dict；非法/空则回退默认
        if isinstance(v, str):
            try:
                return json.loads(v) if v else None
            except Exception:
                return None
        return v

    model_config = ConfigDict(from_attributes=True)

class UserUpdate(BaseModel):
    """更新用户信息请求（昵称与手机号均可修改，二选一或全部）"""
    username: Optional[str] = Field(None, max_length=50, description="昵称")
    phone: Optional[str] = Field(None, description="手机号")
    # 通知偏好设置（可选；传入则整体覆盖保存）
    notification_settings: Optional[dict] = Field(None, description="通知偏好设置")

class BindFamilyReq(BaseModel):
    """家属绑定老人请求"""
    elderly_user_id: int = Field(..., description="老人用户ID")
    # 弱保护：家属必须知道老人的设备ID（老人用户名即设备注册时的 device_id）
    device_id: str = Field(..., description="老人设备ID（弱保护：需知道设备ID才能绑定）")


class CreateElderlyReq(BaseModel):
    """家属创建同家庭组老人账号请求（无需老人自行注册，按姓名即可创建）"""
    name: str = Field(..., min_length=1, max_length=50, description="老人姓名（作为账号昵称）")


class ElderlyOut(BaseModel):
    """家庭组老人简要信息（用于网页老人管理列表与用药设置下拉）"""
    id: int
    name: Optional[str] = None
    # 二哈已录入人脸 ID（未录入为 None）；前端据此提示是否需录入
    husky_face_id: Optional[int] = None
    # 该账号是否绑定了设备（设备主体用户）；设备主体不可被删除，需先解绑
    has_device: bool = False


class FaceIdReq(BaseModel):
    """网页端为老人填写的二哈人脸 ID（用户已自行在二哈录入人脸）"""
    face_id: int = Field(..., description="二哈摄像头屏幕上显示的人脸ID（非负整数）")
