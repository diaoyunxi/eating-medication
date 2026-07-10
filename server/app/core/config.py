# -*- coding: utf-8 -*-
import os
import secrets
import logging
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional

logger = logging.getLogger(__name__)


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


def _ensure_default_env():
    """首次运行无 .env 时自动生成（含随机 SECRET_KEY + DEBUG=true），开箱即用

    在 Settings 实例化前调用，确保 pydantic_settings 能加载到 .env。
    .env 已在 .gitignore 中忽略，不会上传到仓库。
    生产部署时请手动修改 DEBUG=false。
    """
    # .env 位于 server/ 目录（与 server/app/main.py 同级，即 BASE_DIR）
    env_path = Path(__file__).resolve().parent.parent.parent / '.env'
    if env_path.exists():
        return
    secret_key = _generate_secret_key()
    env_content = (
        f"# 自动生成的环境配置文件（首次运行）\n"
        f"# 生产部署时请将 DEBUG 改为 false\n\n"
        f"# 会话签名密钥（已随机生成，请勿泄露）\n"
        f"SECRET_KEY={secret_key}\n\n"
        f"# 调试模式：本地开发设为 true，生产环境设为 false\n"
        f"DEBUG=true\n"
    )
    try:
        env_path.write_text(env_content, encoding='utf-8')
        os.chmod(env_path, 0o600)
        logger.info(f"首次运行：已自动生成 {env_path}（含随机 SECRET_KEY，DEBUG=true）")
        logger.warning("生产部署时请将 .env 中 DEBUG 改为 false")
    except Exception as e:
        logger.warning(f"自动生成 .env 失败: {e}")


# 模块加载时确保 .env 存在
_ensure_default_env()


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
