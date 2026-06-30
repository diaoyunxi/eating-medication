# -*- coding: utf-8 -*-
import os
import secrets
from pydantic_settings import BaseSettings
from typing import Optional


def _generate_secret_key():
    """生成安全的随机密钥"""
    return secrets.token_urlsafe(32)


class Settings(BaseSettings):
    APP_NAME: str = "老年人用药管理系统"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "sqlite:///./data/elderly_care.db"

    SECRET_KEY: str = _generate_secret_key()
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    ZHIPUAI_API_KEY: Optional[str] = None
    ZHIPUAI_MODEL: str = "glm-4.7-flash"

    OCR_PROVIDER: Optional[str] = None
    OCR_API_KEY: Optional[str] = None
    OCR_SECRET_KEY: Optional[str] = None
    OCR_APP_ID: Optional[str] = None

    JD_APP_KEY: Optional[str] = None
    JD_APP_SECRET: Optional[str] = None
    JD_ENABLE_REAL_API: bool = False

    WS_HEARTBEAT_INTERVAL: int = 30

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()