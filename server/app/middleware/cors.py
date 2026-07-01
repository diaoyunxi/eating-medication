# -*- coding: utf-8 -*-
import os
from fastapi.middleware.cors import CORSMiddleware


def _load_allowed_origins():
    """C7：从环境变量读取允许的来源（逗号分隔），默认空列表——生产必须配置"""
    raw = os.getenv("ALLOWED_ORIGINS", "")
    if not raw:
        return []
    return [o.strip() for o in raw.split(",") if o.strip()]


ALLOWED_ORIGINS = _load_allowed_origins()


def setup_cors(app):
    """
    配置 CORS 允许特定来源（C7）。
    生产环境必须通过 ALLOWED_ORIGINS 环境变量配置白名单。
    未配置时不启用 CORS（拒绝跨域），避免使用不安全的通配符 "*"。
    """
    if ALLOWED_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=ALLOWED_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Device-Token"],
        )
