# -*- coding: utf-8 -*-
"""每用户 AI 助手配置接口（多厂商 OpenAI 兼容）

- GET  /api/v1/user/ai-config   读取当前用户（或指定设备/用户）的 AI 配置（api_key 不回传明文）
- PUT  /api/v1/user/ai-config   新增/更新当前用户（或指定设备/用户）的 AI 配置
- GET  /api/v1/ai/providers     公开：返回前端下拉所需的厂商预设

授权模型：默认操作「当前登录用户」自身配置；可通过 device_id / user_id 指定目标用户，
仅当目标用户与当前用户同属一个家庭组（group_id 一致，即家属为被照护老人配置）时允许。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.core.crypto import encrypt_text, decrypt_text
from app.models.user import User
from app.services.device_service import DeviceService
from app.models.user_ai_config import UserAIConfig
from app.schemas.ai import UserAIConfigIn, UserAIConfigOut, AIProviderPreset
from app.services.ai_service import (
    SUPPORTED_PROVIDERS,
    PROVIDER_DEFAULT_MODELS,
    PROVIDER_BASE_URLS,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI健康助手配置"])

# 厂商中文名与申请文档（前端下拉展示用）
_PROVIDER_META = {
    "zhipuai": ("智谱 AI (GLM)", "https://open.bigmodel.cn/"),
    "hunyuan": ("腾讯混元", "https://cloud.tencent.com/product/hunyuan"),
    "minimax": ("MiniMax", "https://www.minimax.io/platform"),
    "kimi": ("月之暗面 Kimi", "https://platform.moonshot.cn/"),
    "deepseek": ("DeepSeek", "https://platform.deepseek.com/"),
    "doubao": ("豆包 (火山方舟)", "https://www.volcengine.com/product/ark"),
    "qwen": ("通义千问 (Qwen)", "https://dashscope.console.aliyun.com/"),
    "custom": ("自定义 (OpenAI 兼容)", ""),
}

# 需要用户显式填写 base_url 的厂商（custom 必填；火山方舟需推理接入点专属网关）
_REQUIRE_BASE_URL = {"custom", "doubao"}


def _resolve_target_user(
    db: Session, current_user: User, device_id: Optional[str], user_id: Optional[int]
) -> User:
    """解析被操作的目标用户，并校验授权。

    - 未指定 device_id/user_id：目标即当前登录用户自身。
    - 指定 device_id：解析为设备绑定的用户（优先 device_id 字段，回退 username）。
    - 指定 user_id：按 id 查找。
    授权：目标 == 自身，或目标与自身同组（group_id 一致）才允许，否则 403。
    """
    if device_id:
        # 复用统一设备→用户解析（device_service 不反向依赖本模块，无循环依赖）
        user = DeviceService.get_device_user(db, device_id)
    elif user_id is not None:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
    else:
        return current_user

    if user.id == current_user.id:
        return user
    if user.group_id and user.group_id == current_user.group_id:
        return user
    raise HTTPException(status_code=403, detail="无权配置该用户的 AI 设置")


def _to_out(row: Optional[UserAIConfig]) -> UserAIConfigOut:
    """将数据库行转为对外响应（不回传明文 api_key）"""
    if not row:
        return UserAIConfigOut(
            provider="zhipuai", model="", base_url=None, enabled=False, has_api_key=False
        )
    return UserAIConfigOut(
        provider=row.provider,
        model=row.model,
        base_url=row.base_url,
        enabled=bool(row.enabled),
        has_api_key=bool(row.api_key),
    )


@router.get("/user/ai-config", response_model=UserAIConfigOut)
async def get_ai_config(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    device_id: Optional[str] = Query(None, description="目标设备ID（家属为被照护老人配置）"),
    user_id: Optional[int] = Query(None, description="目标用户ID"),
):
    """读取 AI 配置（api_key 不回传明文，仅返回 has_api_key 标识）"""
    target = _resolve_target_user(db, current_user, device_id, user_id)
    row = db.query(UserAIConfig).filter(UserAIConfig.user_id == target.id).first()
    return _to_out(row)


@router.put("/user/ai-config", response_model=UserAIConfigOut)
async def upsert_ai_config(
    payload: UserAIConfigIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    device_id: Optional[str] = Query(None, description="目标设备ID（家属为被照护老人配置）"),
    user_id: Optional[int] = Query(None, description="目标用户ID"),
):
    """新增或更新 AI 配置（api_key 加密存储）"""
    provider = (payload.provider or "zhipuai").lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的厂商: {provider}（可选: {', '.join(SUPPORTED_PROVIDERS)}）",
        )

    # 模型：未填写且厂商有默认值则自动补默认；custom 必须填写
    model = (payload.model or "").strip()
    if not model:
        model = PROVIDER_DEFAULT_MODELS.get(provider, "")
    if not model:
        raise HTTPException(status_code=400, detail=f"厂商 {provider} 必须填写模型名")

    # base_url：custom/火山方舟必须填写
    base_url = (payload.base_url or "").strip() or None
    if provider in _REQUIRE_BASE_URL and not base_url:
        raise HTTPException(
            status_code=400, detail=f"厂商 {provider} 必须填写 base_url（OpenAI 兼容地址）"
        )

    target = _resolve_target_user(db, current_user, device_id, user_id)

    row = db.query(UserAIConfig).filter(UserAIConfig.user_id == target.id).first()
    # api_key 为空时：已有配置则保留原密钥，否则置空（未配置）
    if payload.api_key:
        encrypted_key = encrypt_text(payload.api_key)
    elif row and row.api_key:
        encrypted_key = row.api_key
    else:
        encrypted_key = ""

    if row:
        row.provider = provider
        row.api_key = encrypted_key
        row.model = model
        row.base_url = base_url
        row.enabled = payload.enabled
    else:
        row = UserAIConfig(
            user_id=target.id,
            provider=provider,
            api_key=encrypted_key,
            model=model,
            base_url=base_url,
            enabled=payload.enabled,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    logger.info(f"✅ 已保存用户 {target.id} 的 AI 配置: provider={provider}, model={model}")
    return _to_out(row)


@router.get("/providers", response_model=list[AIProviderPreset])
async def list_providers(current_user: User = Depends(get_current_user)):
    """公开：返回前端下拉所需的厂商预设列表"""
    presets = []
    for pid in SUPPORTED_PROVIDERS:
        name, doc = _PROVIDER_META.get(pid, (pid, ""))
        presets.append(
            AIProviderPreset(
                id=pid,
                name=name,
                default_model=PROVIDER_DEFAULT_MODELS.get(pid, ""),
                requires_base_url=pid in _REQUIRE_BASE_URL,
                requires_model=True,  # 所有厂商均需填写模型名
                doc_url=doc,
            )
        )
    return presets
