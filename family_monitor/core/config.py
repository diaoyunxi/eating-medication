# -*- coding: utf-8 -*-
"""配置管理模块 - 单一 .env 配置源

所有配置（含安全密钥与运行时项）统一从 family_monitor/.env 读取。
首次运行无 .env 时自动生成完整模板（含随机 SECRET_KEY），开箱即用。
.env 已在 .gitignore 中忽略，不会上传到仓库。

【配置统一说明】
本模块历史上同时存在 .env 与 config.json 两套配置且大面积重叠，
现已统一为单一 .env 配置源，消除「同一字段两处可配、优先级不可预测」的混乱。
"""

import os
import sys
import secrets
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _generate_secret_key():
    """生成安全的随机密钥"""
    return secrets.token_urlsafe(32)


class Config:
    """配置管理类（单一 .env 配置源）"""

    def __init__(self):
        self.BASE_DIR = Path(__file__).resolve().parent.parent
        self.env_path = self.BASE_DIR / '.env'
        # 首次运行无 .env 时自动生成（含随机 SECRET_KEY + 全部字段），开箱即用
        # .env 已在 .gitignore 中忽略，不会上传到仓库
        if not self.env_path.exists():
            self._generate_default_env(self.env_path)
        load_dotenv(self.env_path)

        # ===== 服务监听 =====
        self.SERVER_HOST = os.getenv('SERVER_HOST', '0.0.0.0')
        self.SERVER_PORT = int(os.getenv('SERVER_PORT', '4430'))

        # 老人端（服务端）地址，默认走 Cloudflare 隧道公网域名
        self.ELDERLY_SERVER_URL = os.getenv(
            'ELDERLY_SERVER_URL',
            'https://my-website.ccwu.cc/eating-medication/server'
        )

        # 路径前缀（Cloudflare 隧道子路径），本地直连默认为空
        self.PATH_PREFIX = os.getenv('PATH_PREFIX', '').rstrip('/')

        # ===== 显示设置 =====
        self.DISPLAY_SETTINGS = {
            'theme': os.getenv('DISPLAY_THEME', 'light'),
            'color': os.getenv('DISPLAY_COLOR', 'purple'),
            'language': os.getenv('DISPLAY_LANGUAGE', 'zh-CN'),
            'animations': os.getenv('DISPLAY_ANIMATIONS', 'True').lower() == 'true',
            'compact': os.getenv('DISPLAY_COMPACT', 'False').lower() == 'true',
        }

        self.DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
        self.APP_NAME = os.getenv('APP_NAME', '子女守护中心')

        # ===== 安全 =====
        # 标记是否为运行时随机生成的临时密钥，供 validate_mandatory_config 判断是否拒绝启动
        is_production = os.getenv('PRODUCTION', 'false').lower() == 'true'
        secret_key = os.getenv('SECRET_KEY', '')
        if not secret_key:
            self._secret_key_is_random = True
            # 开发环境允许降级生成临时密钥；生产环境缺失交由校验统一报错退出
            secret_key = _generate_secret_key()
            if self.DEBUG and not is_production:
                logger.warning(
                    "SECRET_KEY 未配置，已生成临时密钥（开发环境），重启后会话将失效。"
                    "请通过 .env 配置 SECRET_KEY。"
                )
            else:
                logger.warning(
                    "SECRET_KEY 未配置（生产/非调试环境），将在启动校验时拒绝启动，请先配置 SECRET_KEY。"
                )
        else:
            self._secret_key_is_random = False
        self.SECRET_KEY = secret_key

        # 设备共享密钥：用于后端 API 调用时注入 X-Device-Secret header 做服务端鉴权
        # 未配置时保持兼容（不发送该 header）
        self.DEVICE_SECRET = os.getenv('DEVICE_SECRET', '')

        # Cloudflare Turnstile 站点密钥（前端展示人机验证组件用）
        # 未配置时前端 Turnstile 组件无法渲染，需在 .env 中填入你的 Site Key
        self.TURNSTILE_SITE_KEY = os.getenv('TURNSTILE_SITE_KEY', '')

        # CORS 允许的来源（逗号分隔），默认仅允许本地
        allowed_origins_env = os.getenv(
            'ALLOWED_ORIGINS',
            'http://localhost:4430,http://127.0.0.1:4430'
        )
        self.ALLOWED_ORIGINS = [o.strip() for o in allowed_origins_env.split(',') if o.strip()]

        # Cookie secure 标志：DEBUG=true（本地 HTTP 开发）默认关闭，生产环境（HTTPS）默认开启
        # 避免本地 HTTP 调试时浏览器丢弃带 Secure 标志的 cookie 导致登录失败
        self.COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'false' if self.DEBUG else 'true').lower() == 'true'

        # 是否为生产环境（生产环境禁止通过 Web 修改 DEBUG）
        self.PRODUCTION = os.getenv('PRODUCTION', 'false').lower() == 'true'

        self.STATIC_DIR = self.BASE_DIR / 'static'
        self.TEMPLATES_DIR = self.BASE_DIR / 'templates'

        self.DATA_DIR = self.BASE_DIR / 'data'
        self.DATA_DIR.mkdir(exist_ok=True)

    def _generate_default_env(self, env_path: Path):
        """首次运行时自动生成完整 .env 文件（含全部可配置字段 + 随机 SECRET_KEY）

        开箱即用设计：用户克隆后可直接 python3 main.py 启动，无需手动配置。
        生成的 .env 包含全部字段（安全项 + 运行时项），单一配置源。
        .env 已在 .gitignore 中忽略，不会上传到仓库。
        生产部署时请手动修改 DEBUG=false 并按需调整 SECRET_KEY。
        """
        secret_key = _generate_secret_key()
        env_content = (
            f"# 自动生成的环境配置文件（首次运行，已包含全部可配置字段）\n"
            f"# 生产部署时请将 DEBUG 改为 false，COOKIE_SECURE 改为 true\n\n"
            f"# ===== 服务监听 =====\n"
            f"SERVER_HOST=0.0.0.0\n"
            f"SERVER_PORT=4430\n\n"
            f"# ===== 老人端（服务端）地址 =====\n"
            f"# 服务端 API 基址，默认走 Cloudflare 隧道公网域名\n"
            f"ELDERLY_SERVER_URL=https://my-website.ccwu.cc/eating-medication/server\n\n"
            f"# ===== 路径前缀 =====\n"
            f"# Cloudflare 隧道子路径，本地直连设为空\n"
            f"PATH_PREFIX=/eating-medication/family\n\n"
            f"# ===== 应用 =====\n"
            f"APP_NAME=子女守护中心\n"
            f"# 调试模式：本地开发设为 true，生产环境设为 false\n"
            f"DEBUG=true\n"
            f"# Cookie secure 标志：本地 HTTP 调试必须为 false，否则浏览器不保存 cookie\n"
            f"COOKIE_SECURE=false\n"
            f"# 是否为生产环境（生产环境禁止通过 Web 修改 DEBUG）\n"
            f"PRODUCTION=false\n\n"
            f"# ===== 安全 =====\n"
            f"# 会话签名密钥（已随机生成，请勿泄露）\n"
            f"SECRET_KEY={secret_key}\n"
            f"# 设备共享密钥：调用后端 API 时的服务端鉴权（X-Device-Secret），留空则兼容旧版不发送\n"
            f"DEVICE_SECRET=\n\n"
            f"# ===== Cloudflare Turnstile 站点密钥 =====\n"
            f"# 前端展示人机验证组件用，必填；留空则前端验证组件无法渲染\n"
            f"TURNSTILE_SITE_KEY=\n\n"
            f"# ===== CORS 跨域白名单 =====\n"
            f"# 留空则默认仅允许本机；生产环境建议填前端可访问的来源，逗号分隔\n"
            f"ALLOWED_ORIGINS=http://localhost:4430,http://127.0.0.1:4430\n\n"
            f"# ===== 显示设置 =====\n"
            f"DISPLAY_THEME=light\n"
            f"DISPLAY_COLOR=purple\n"
            f"DISPLAY_LANGUAGE=zh-CN\n"
            f"DISPLAY_ANIMATIONS=True\n"
            f"DISPLAY_COMPACT=False\n"
        )
        try:
            env_path.write_text(env_content, encoding='utf-8')
            # 设置文件权限为 600，仅所有者可读写（保护密钥）
            os.chmod(env_path, 0o600)
            logger.info(f"首次运行：已自动生成 {env_path}（含随机 SECRET_KEY，DEBUG=true）")
            logger.warning("生产部署时请将 .env 中 DEBUG 改为 false")
        except Exception as e:
            logger.warning(f"自动生成 .env 失败: {e}，将使用临时密钥启动")

    def save_config(self):
        """保存当前运行时可改配置到 .env

        仅写入非敏感、可热改字段；密钥类字段（SECRET_KEY/COOKIE_SECURE/
        PRODUCTION/DEVICE_SECRET/ALLOWED_ORIGINS/SERVER_HOST）保留 .env 原值不动，
        避免 Web 误改密钥或监听地址。
        """
        new_values = {
            'SERVER_PORT': str(self.SERVER_PORT),
            'ELDERLY_SERVER_URL': self.ELDERLY_SERVER_URL,
            'PATH_PREFIX': self.PATH_PREFIX,
            'APP_NAME': self.APP_NAME,
            'DISPLAY_THEME': self.DISPLAY_SETTINGS.get('theme', 'light'),
            'DISPLAY_COLOR': self.DISPLAY_SETTINGS.get('color', 'purple'),
            'DISPLAY_LANGUAGE': self.DISPLAY_SETTINGS.get('language', 'zh-CN'),
            'DISPLAY_ANIMATIONS': str(self.DISPLAY_SETTINGS.get('animations', True)),
            'DISPLAY_COMPACT': str(self.DISPLAY_SETTINGS.get('compact', False)),
            'TURNSTILE_SITE_KEY': self.TURNSTILE_SITE_KEY,
        }
        try:
            self._update_env_file(new_values)
            return True
        except Exception as e:
            print(f"保存配置文件失败: {e}")
            return False

    def _update_env_file(self, updates: dict):
        """就地更新 .env 中指定字段，保留其它字段与注释不变

        :param updates: {字段名: 新值}
        """
        lines = []
        if self.env_path.exists():
            lines = self.env_path.read_text(encoding='utf-8').splitlines()
        existing = {}
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or '=' not in stripped:
                continue
            k, _ = stripped.split('=', 1)
            existing[k.strip()] = i
        for key, value in updates.items():
            if key in existing:
                lines[existing[key]] = f"{key}={value}"
            else:
                lines.append(f"{key}={value}")
        self.env_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def validate_mandatory_config():
    """集中校验 family_monitor『最基本必填』配置；缺失或非法则打印清晰提示并结束进程。

    可选外部服务（Cloudflare Turnstile 站点密钥、GitHub/Gitee OAuth、后端探测等）
    缺失由各自逻辑降级（隐藏按钮/跳过验证），不在此强制校验。

    校验范围：
      - SECRET_KEY：生产环境（PRODUCTION=true 或 DEBUG=false）必须显式配置，禁止随机生成密钥
      - APP_NAME：应用名称禁止为空
      - PATH_PREFIX：路径前缀，允许为空（本地直连）；若非空须以 '/' 开头
    """
    errors = []
    is_production = os.getenv('PRODUCTION', 'false').lower() == 'true'
    if is_production or not config.DEBUG:
        if getattr(config, '_secret_key_is_random', False):
            errors.append(
                "SECRET_KEY 未配置：生产/非调试环境拒绝以未配置密钥启动。"
                "请在 family_monitor/.env 设置 SECRET_KEY 后重启。"
            )
    if not config.APP_NAME or not config.APP_NAME.strip():
        errors.append(
            "APP_NAME 未配置：请在 family_monitor/.env 设置应用名称"
            "（如 APP_NAME=子女守护中心）。"
        )
    path_prefix = (config.PATH_PREFIX or "").strip()
    if path_prefix and not path_prefix.startswith("/"):
        errors.append(
            f"PATH_PREFIX 配置非法：'{path_prefix}' 若非空必须以 '/' 开头，"
            "请在 family_monitor/.env 修正。"
        )
    if errors:
        print("=" * 64)
        print("【family_monitor 配置校验失败】以下必填配置缺失或非法，服务无法启动：")
        for _err in errors:
            print(f"  - {_err}")
        print("=" * 64)
        sys.exit(1)


# 全局配置实例
config = Config()
