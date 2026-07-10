# -*- coding: utf-8 -*-
import os
import secrets
from pydantic_settings import BaseSettings
from typing import Optional


# C3：已知的不安全 SECRET_KEY 值（生产环境禁止使用）
_WEAK_SECRET_KEYS = {
    "your-secret-key-change-this-in-production",
    "change-me",
    "",
}

# S-02 修复：模块级标志，标记 SECRET_KEY 是否为运行时随机生成
_SECRET_KEY_IS_RANDOM = False
# 占位符默认值：未通过环境变量/.env 配置 SECRET_KEY 时使用此标记
_SECRET_KEY_SENTINEL = "__AUTO_GENERATED__"


def _generate_secret_key():
    """生成安全的随机密钥"""
    return secrets.token_urlsafe(32)


class Settings(BaseSettings):
    APP_NAME: str = "老年人用药管理系统"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # 路径前缀（Cloudflare 隧道子路径），本地直连设为空
    PATH_PREFIX: str = "/eating-medication/server"

    DATABASE_URL: str = "sqlite:///./data/elderly_care.db"

    # S-02 修复：默认使用占位符，未配置环境变量时在 model_post_init 中标记为随机生成
    SECRET_KEY: str = _SECRET_KEY_SENTINEL
    ALGORITHM: str = "HS256"
    # H7：缩短为 1 小时（原为 7 天），降低 token 泄露后的风险窗口
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    ZHIPUAI_API_KEY: Optional[str] = None
    ZHIPUAI_MODEL: str = "glm-4.7-flash"

    OCR_PROVIDER: Optional[str] = None
    OCR_API_KEY: Optional[str] = None
    OCR_SECRET_KEY: Optional[str] = None

    # CORS 允许的来源（逗号分隔），未配置则不启用 CORS
    ALLOWED_ORIGINS: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True

    def model_post_init(self, __context):
        """C3/S-02：初始化后校验配置

        - 若 SECRET_KEY 仍为占位符，说明未通过环境变量/.env 配置：
          DEBUG 模式下生成随机密钥以支持开发；生产模式拒绝启动。
        - 生产模式（DEBUG=False）禁止使用弱 SECRET_KEY 或随机生成的密钥。
        """
        global _SECRET_KEY_IS_RANDOM
        # S-02：检测是否未配置 SECRET_KEY（仍为占位符）
        if self.SECRET_KEY == _SECRET_KEY_SENTINEL:
            _SECRET_KEY_IS_RANDOM = True
            # DEBUG 模式下生成随机密钥以支持本地开发
            self.SECRET_KEY = _generate_secret_key()
        else:
            _SECRET_KEY_IS_RANDOM = False

        if not self.DEBUG:
            if _SECRET_KEY_IS_RANDOM:
                raise RuntimeError(
                    "生产环境（DEBUG=False）禁止使用运行时随机生成的 SECRET_KEY，"
                    "请在 .env 中配置固定的随机 SECRET_KEY"
                )
            if self.SECRET_KEY in _WEAK_SECRET_KEYS:
                raise RuntimeError(
                    "生产环境（DEBUG=False）禁止使用弱 SECRET_KEY，"
                    "请在 .env 中配置随机生成的 SECRET_KEY"
                )
        # DEBUG=True 时允许使用随机生成的密钥


settings = Settings()
