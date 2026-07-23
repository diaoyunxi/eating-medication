# -*- coding: utf-8 -*-
import os
import re
import secrets
import logging
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional

logger = logging.getLogger(__name__)


# 已知的不安全 SECRET_KEY 值（生产环境禁止使用）
_WEAK_SECRET_KEYS = {
    "your-secret-key-change-this-in-production",
    "change-me",
    "",
}

# 模块级标志，标记 SECRET_KEY 是否为运行时随机生成
_SECRET_KEY_IS_RANDOM = False
# 占位符默认值：未通过环境变量/.env 配置 SECRET_KEY 时使用此标记
_SECRET_KEY_SENTINEL = "__AUTO_GENERATED__"


def _generate_secret_key():
    """生成安全的随机密钥"""
    return secrets.token_urlsafe(32)


def _write_full_env(env_path: Path, secret_key: str):
    """写入「完整」.env 模板：包含全部可被读取的环境变量。

    必填项留空并加注释说明；有默认值的给出默认值，降低上手成本。
    """
    env_content = (
        f"# 自动生成的环境配置文件（首次运行，已包含全部可配置字段）\n"
        f"# 生产部署时请将 DEBUG 改为 false，并填入以下必填项（留空的行需补充）\n\n"
        f"# ===== 基础 =====\n"
        f"APP_NAME=老年人用药管理系统\n"
        f"# 调试模式：本地开发设为 true，生产环境设为 false\n"
        f"DEBUG=true\n"
        f"# API 路由前缀（一般无需修改）\n"
        f"API_V1_PREFIX=/api/v1\n"
        f"# 路径前缀（Cloudflare 隧道子路径）；本地直连设为空，隧道部署须与隧道路由一致\n"
        f"PATH_PREFIX=/eating-medication/server\n"
        f"# 数据库地址（SQLite 默认即可，可改为 mysql:// 等）\n"
        f"DATABASE_URL=sqlite:///./data/elderly_care.db\n\n"
        f"# ===== 安全 =====\n"
        f"# 会话签名密钥（已随机生成，请勿泄露；生产环境建议使用固定值并妥善保管）\n"
        f"SECRET_KEY={secret_key}\n"
        f"ALGORITHM=HS256\n"
        f"# 访问令牌有效期（分钟）\n"
        f"ACCESS_TOKEN_EXPIRE_MINUTES=60\n\n"
        f"# ===== Cloudflare Turnstile 人机验证 =====\n"
        f"# 后端 siteverify 校验用的密钥（Secret Key），必填；生产环境缺失将拒绝全部登录/注册\n"
        f"# 须与 family_monitor/.env 的 TURNSTILE_SITE_KEY 来自同一 Turnstile 站点\n"
        f"# 获取地址：https://dash.cloudflare.com/  -> Turnstile -> 你的站点 -> Keys\n"
        f"TURNSTILE_SECRET_KEY=\n\n"
        f"# ===== 智谱 AI 对话 =====\n"
        f"# 留空则 AI 对话功能不可用；申请地址：https://open.bigmodel.cn/\n"
        f"ZHIPUAI_API_KEY=\n"
        f"ZHIPUAI_MODEL=glm-4.7-flash\n\n"
        f"# ===== 图片 OCR 识别 =====\n"
        f"# OCR_PROVIDER 留空则图片识别功能不可用；可选 baidu / tencent / aliyun\n"
        f"OCR_PROVIDER=\n"
        f"OCR_API_KEY=\n"
        f"OCR_SECRET_KEY=\n\n"
        f"# ===== CORS 跨域白名单 =====\n"
        f"# 生产环境必填，填前端（family_monitor）访问域名，逗号分隔；留空则跨域请求被拒绝\n"
        f"ALLOWED_ORIGINS=\n\n"
        f"# ===== GitHub OAuth 登录 =====\n"
        f"# 不配置 GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET 时前端隐藏 GitHub 登录按钮\n"
        f"# 申请地址：https://github.com/settings/developers -> New OAuth App\n"
        f"# 回调地址须与 GITHUB_OAUTH_CALLBACK_URL 完全一致\n"
        f"GITHUB_CLIENT_ID=\n"
        f"GITHUB_CLIENT_SECRET=\n"
        f"GITHUB_OAUTH_CALLBACK_URL=https://my-website.ccwu.cc/eating-medication/server/api/v1/auth/oauth/github/callback\n"
        f"# family_monitor 前端地址（OAuth 回调后 302 跳转用）\n"
        f"FAMILY_WEB_URL=https://my-website.ccwu.cc/eating-medication/family\n"
    )
    env_path.write_text(env_content, encoding='utf-8')
    os.chmod(env_path, 0o600)


# 已存在 .env 但需要补齐的「必填 / 重要」字段：键 -> (注释行列表, 默认值)
# 这些字段在旧版「精简 .env」中缺失（如 Cloudflare Turnstile、GitHub OAuth 等）。
_BACKFILL_FIELDS = [
    ("TURNSTILE_SECRET_KEY", [
        "# ===== Cloudflare Turnstile 人机验证 =====",
        "# 后端 siteverify 校验用的密钥（Secret Key），必填；生产环境缺失将拒绝全部登录/注册",
        "# 须与 family_monitor/.env 的 TURNSTILE_SITE_KEY 来自同一 Turnstile 站点",
        "# 获取地址：https://dash.cloudflare.com/  -> Turnstile -> 你的站点 -> Keys",
    ], ""),
    ("ZHIPUAI_API_KEY", [
        "# ===== 智谱 AI 对话 =====",
        "# 留空则 AI 对话功能不可用；申请地址：https://open.bigmodel.cn/",
    ], ""),
    ("ZHIPUAI_MODEL", ["# 智谱 AI 模型"], "glm-4.7-flash"),
    ("OCR_PROVIDER", [
        "# ===== 图片 OCR 识别 =====",
        "# OCR_PROVIDER 留空则图片识别功能不可用；可选 baidu / tencent / aliyun",
    ], ""),
    ("OCR_API_KEY", [], ""),
    ("OCR_SECRET_KEY", [], ""),
    ("GITHUB_CLIENT_ID", [
        "# ===== GitHub OAuth 登录 =====",
        "# 不配置 GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET 时前端隐藏 GitHub 登录按钮",
        "# 申请地址：https://github.com/settings/developers -> New OAuth App",
    ], ""),
    ("GITHUB_CLIENT_SECRET", [], ""),
    ("GITHUB_OAUTH_CALLBACK_URL", [],
     "https://my-website.ccwu.cc/eating-medication/server/api/v1/auth/oauth/github/callback"),
    ("FAMILY_WEB_URL", ["# family_monitor 前端地址（OAuth 回调后 302 跳转用）"],
     "https://my-website.ccwu.cc/eating-medication/family"),
]


def _backfill_env_fields(env_path: Path):
    """为已存在的 .env 补齐缺失的必填字段，避免旧版精简模板缺少关键字段。

    仅追加缺失的字段行（保留已有配置），不会覆盖用户已填写的值。
    """
    try:
        content = env_path.read_text(encoding='utf-8')
    except Exception as e:
        logger.warning(f"读取已有 .env 失败，跳过补齐: {e}")
        return

    missing = [
        (key, comments, default)
        for key, comments, default in _BACKFILL_FIELDS
        if not re.search(rf'^\s*{re.escape(key)}\s*=', content, re.MULTILINE)
    ]
    if not missing:
        return

    lines = ["\n# ===== 自动补齐的必填字段（原 .env 缺失，已追加；按需填写后重启生效） ====="]
    for key, comments, default in missing:
        lines.extend(comments)
        lines.append(f"{key}={default}")

    try:
        with env_path.open('a', encoding='utf-8') as f:
            f.write("\n" + "\n".join(lines) + "\n")
        logger.warning(
            f"已为 {env_path} 补齐缺失字段：{', '.join(k for k, _, _ in missing)}"
        )
    except Exception as e:
        logger.warning(f"补齐 .env 字段失败: {e}")


def _ensure_default_env():
    """确保 .env 存在且包含全部必填字段。

    - 首次运行无 .env：写入完整模板（含随机 SECRET_KEY + DEBUG=true），开箱即用。
    - 已存在但缺失关键字段（如 Cloudflare Turnstile、GitHub OAuth）：自动补齐，
      修复旧版「精简 .env」导致必填字段缺失的问题。

    .env 已在 .gitignore 中忽略，不会上传到仓库。生产部署时请手动修改 DEBUG=false。
    """
    # .env 位于 server/ 目录（与 server/app/main.py 同级，即 BASE_DIR）
    env_path = Path(__file__).resolve().parent.parent.parent / '.env'
    if not env_path.exists():
        # 首次运行：写入完整模板
        secret_key = _generate_secret_key()
        try:
            _write_full_env(env_path, secret_key)
            logger.info(f"首次运行：已自动生成 {env_path}（含随机 SECRET_KEY，DEBUG=true）")
            logger.warning("生产部署时请将 .env 中 DEBUG 改为 false")
        except Exception as e:
            logger.warning(f"自动生成 .env 失败: {e}")
    else:
        # 已存在：补齐缺失的必填字段
        _backfill_env_fields(env_path)


# 模块加载时确保 .env 存在且字段完整
_ensure_default_env()


class Settings(BaseSettings):
    APP_NAME: str = "老年人用药管理系统"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # 路径前缀（Cloudflare 隧道子路径），本地直连设为空
    PATH_PREFIX: str = "/eating-medication/server"

    DATABASE_URL: str = "sqlite:///./data/elderly_care.db"

    # 默认使用占位符，未配置环境变量时在 model_post_init 中标记为随机生成
    SECRET_KEY: str = _SECRET_KEY_SENTINEL
    ALGORITHM: str = "HS256"
    # 缩短为 1 小时（原为 7 天），降低 token 泄露后的风险窗口
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Cloudflare Turnstile 密钥（用于后端 siteverify 验证）
    # 未配置时跳过 Turnstile 校验（开发环境兼容，生产环境必须配置）
    TURNSTILE_SECRET_KEY: Optional[str] = None

    ZHIPUAI_API_KEY: Optional[str] = None
    ZHIPUAI_MODEL: str = "glm-4.7-flash"

    OCR_PROVIDER: Optional[str] = None
    OCR_API_KEY: Optional[str] = None
    OCR_SECRET_KEY: Optional[str] = None

    # CORS 允许的来源（逗号分隔），未配置则不启用 CORS
    ALLOWED_ORIGINS: str = ""

    # ===== GitHub OAuth 登录配置 =====
    # 未配置 GITHUB_CLIENT_ID 时，前端隐藏 GitHub 登录按钮
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None
    # GitHub OAuth 回调 URL（须与 GitHub 后台 "Authorization callback URL" 完全一致；
    # 一个 GitHub OAuth App 仅允许配置一个固定回调地址）
    GITHUB_OAUTH_CALLBACK_URL: str = "https://my-website.ccwu.cc/eating-medication/server/api/v1/auth/oauth/github/callback"
    # family_monitor 前端地址（OAuth 回调验证成功后 302 跳转用，与 Cloudflare 隧道子路径一致）
    FAMILY_WEB_URL: str = "https://my-website.ccwu.cc/eating-medication/family"

    class Config:
        env_file = ".env"
        case_sensitive = True

    def model_post_init(self, __context):
        """初始化后校验配置

        - 若 SECRET_KEY 仍为占位符，说明未通过环境变量/.env 配置：
          DEBUG 模式下生成随机密钥以支持开发；生产模式拒绝启动。
        - 生产模式（DEBUG=False）禁止使用弱 SECRET_KEY 或随机生成的密钥。
        """
        global _SECRET_KEY_IS_RANDOM
        # 检测是否未配置 SECRET_KEY（仍为占位符）
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
