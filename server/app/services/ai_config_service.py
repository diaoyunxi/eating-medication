# -*- coding: utf-8 -*-
"""AI 配置解析服务：从数据库解析某用户的生效 AI 配置

解析优先级（使「家属在子女端为被照护老人配置」能正确生效）：
1. 用户自身的 user_ai_configs 配置（且 enabled 且有 api_key）；
2. 同家庭组（group_id 一致）中家属(family)用户的配置（兜底）；
3. 均无则返回 None，交由 AIService.ask 回退到全局 settings.ZHIPUAI_*。
"""
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.user_ai_config import UserAIConfig
from app.core.crypto import decrypt_text
import logging

logger = logging.getLogger(__name__)


def get_effective_config(db: Session, user: User) -> dict:
    """返回用户生效的 AI 配置 dict（provider/api_key/model/base_url），无则 {}。"""
    # 1) 用户自身配置
    row = db.query(UserAIConfig).filter(UserAIConfig.user_id == user.id).first()
    if row and row.enabled and row.api_key:
        return {
            "provider": row.provider,
            "api_key": decrypt_text(row.api_key),
            "model": row.model,
            "base_url": row.base_url,
        }

    # 2) 同组家属配置兜底
    if user.group_id:
        fam_row = (
            db.query(UserAIConfig)
            .join(User, UserAIConfig.user_id == User.id)
            .filter(
                User.group_id == user.group_id,
                User.role == "family",
                UserAIConfig.enabled == True,  # noqa: E712
                UserAIConfig.api_key != "",
            )
            .first()
        )
        if fam_row:
            logger.info(
                f"用户 {user.id} 无自身 AI 配置，使用同组家属 {fam_row.user_id} 的配置（provider={fam_row.provider}）"
            )
            return {
                "provider": fam_row.provider,
                "api_key": decrypt_text(fam_row.api_key),
                "model": fam_row.model,
                "base_url": fam_row.base_url,
            }

    # 3) 无配置
    return {}
