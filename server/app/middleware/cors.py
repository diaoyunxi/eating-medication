# -*- coding: utf-8 -*-
from fastapi.middleware.cors import CORSMiddleware


def setup_cors(app):
    """
    配置 CORS 允许特定来源（C7）。
    生产环境必须通过 ALLOWED_ORIGINS 环境变量配置白名单。
    未配置时不启用 CORS（拒绝跨域），避免使用不安全的通配符 "*"。

    S-09 修复：直接从 settings.ALLOWED_ORIGINS 读取，移除模块级重复读取环境变量。
    """
    from app.core.config import settings
    # 直接使用 settings 中已加载的 ALLOWED_ORIGINS（逗号分隔）
    raw = settings.ALLOWED_ORIGINS or ""
    allowed_origins = [o.strip() for o in raw.split(",") if o.strip()]
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )
