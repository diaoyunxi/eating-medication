# -*- coding: utf-8 -*-
"""配置管理模块 - 完善版"""

import os
import secrets
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _generate_secret_key():
    """生成安全的随机密钥"""
    return secrets.token_urlsafe(32)


class Config:
    """配置管理类"""

    def __init__(self):
        self.BASE_DIR = Path(__file__).resolve().parent.parent

        env_path = self.BASE_DIR / '.env'
        # 首次运行无 .env 时自动生成（含随机 SECRET_KEY + DEBUG=true），开箱即用
        # .env 已在 .gitignore 中，不会上传到仓库
        if not env_path.exists():
            self._generate_default_env(env_path)
        load_dotenv(env_path)

        self.config_file = self.BASE_DIR / 'config.json'
        self._config_data = {}
        self._load_from_json()

        # 配置优先级：环境变量 > config.json > 默认值
        self.SERVER_HOST = os.getenv('SERVER_HOST', self._config_data.get('SERVER_HOST', '0.0.0.0'))
        self.SERVER_PORT = int(os.getenv('SERVER_PORT', str(self._config_data.get('SERVER_PORT', 4430))))

        # 老人端（服务端）地址，默认走 Cloudflare 隧道公网域名
        self.ELDERLY_SERVER_URL = os.getenv(
            'ELDERLY_SERVER_URL',
            self._config_data.get('ELDERLY_SERVER_URL', 'https://my-website.ccwu.cc/eating-medication/server')
        )

        # 路径前缀（Cloudflare 隧道子路径），本地直连默认为空
        self.PATH_PREFIX = os.getenv('PATH_PREFIX', self._config_data.get('PATH_PREFIX', '')).rstrip('/')

        self.DISPLAY_SETTINGS = {
            'theme': os.getenv('DISPLAY_THEME', self._config_data.get('DISPLAY_THEME', 'light')),
            'color': os.getenv('DISPLAY_COLOR', self._config_data.get('DISPLAY_COLOR', 'purple')),
            'language': os.getenv('DISPLAY_LANGUAGE', self._config_data.get('DISPLAY_LANGUAGE', 'zh-CN')),
            'animations': (os.getenv('DISPLAY_ANIMATIONS', str(self._config_data.get('DISPLAY_ANIMATIONS', 'True')))).lower() == 'true',
            'compact': (os.getenv('DISPLAY_COMPACT', str(self._config_data.get('DISPLAY_COMPACT', 'False')))).lower() == 'true',
        }

        self.DEBUG = os.getenv('DEBUG', str(self._config_data.get('DEBUG', 'False'))).lower() == 'true'

        self.APP_NAME = os.getenv('APP_NAME', self._config_data.get('APP_NAME', '子女守护中心'))

        # SECRET_KEY：优先从环境变量读取，其次从配置文件
        # 注意：SECRET_KEY 仅通过 .env 配置，不应写入 config.json
        secret_key = os.getenv('SECRET_KEY') or self._config_data.get('SECRET_KEY', '')
        if not secret_key:
            # 生产环境（PRODUCTION=true）或非调试模式（DEBUG=false）必须显式配置 SECRET_KEY，拒绝启动
            is_production = os.getenv('PRODUCTION', 'false').lower() == 'true'
            if is_production or not self.DEBUG:
                raise RuntimeError(
                    "SECRET_KEY 未配置：生产/非调试环境拒绝以降级密钥启动，"
                    "请通过 .env 设置 SECRET_KEY。"
                )
            # 仅 DEBUG=true 的开发环境允许降级，使用 logger.warning 而非 print
            secret_key = _generate_secret_key()
            logger.warning(
                "SECRET_KEY 未配置，已生成临时密钥，重启后会话将失效。"
                "请通过 .env 配置 SECRET_KEY。"
            )
        self.SECRET_KEY = secret_key

        # 设备共享密钥：用于后端 API 调用时注入 X-Device-Secret header 做服务端鉴权
        # 未配置时保持兼容（不发送该 header）
        self.DEVICE_SECRET = os.getenv('DEVICE_SECRET', '')

        # Cloudflare Turnstile 站点密钥（前端展示人机验证组件用）
        # 未配置时前端 Turnstile 组件无法渲染，需在 .env 中填入你的 Site Key
        self.TURNSTILE_SITE_KEY = os.getenv('TURNSTILE_SITE_KEY', self._config_data.get('TURNSTILE_SITE_KEY', ''))

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
        """首次运行时自动生成 .env 文件（含随机 SECRET_KEY + DEBUG=true）

        开箱即用设计：用户克隆后可直接 python3 main.py 启动，无需手动配置。
        生成的 .env 包含：
        - SECRET_KEY：随机生成的安全密钥（secrets.token_urlsafe(32)）
        - DEBUG=true：开发模式，允许本地 HTTP 调试
        .env 已在 .gitignore 中忽略，不会上传到仓库。
        生产部署时请手动修改 DEBUG=false 并按需调整 SECRET_KEY。
        """
        secret_key = _generate_secret_key()
        # 生成「完整」.env 模板：包含全部可被读取的环境变量（v2.10.2 起）。
        # 说明：SERVER_PORT / ELDERLY_SERVER_URL / PATH_PREFIX / APP_NAME / DISPLAY_*
        # 由 config.json 管理（Web 设置页可改），为避免 .env 覆盖导致设置页失效，
        # 这里以注释形式列出，如需用 .env 强制覆盖可取消注释填写。
        env_content = (
            f"# 自动生成的环境配置文件（首次运行，v2.10.2 起已包含全部可配置字段）\n"
            f"# 生产部署时请将 DEBUG 改为 false，COOKIE_SECURE 改为 true\n\n"
            f"# ===== 安全 =====\n"
            f"# 会话签名密钥（已随机生成，请勿泄露）\n"
            f"SECRET_KEY={secret_key}\n"
            f"# 调试模式：本地开发设为 true，生产环境设为 false\n"
            f"DEBUG=true\n"
            f"# Cookie secure 标志：本地 HTTP 调试必须为 false，否则浏览器不保存 cookie\n"
            f"COOKIE_SECURE=false\n"
            f"# 是否为生产环境（生产环境禁止通过 Web 修改 DEBUG）\n"
            f"PRODUCTION=false\n\n"
            f"# ===== Cloudflare Turnstile 站点密钥 =====\n"
            f"# 前端展示人机验证组件用，必填；留空则前端验证组件无法渲染\n"
            f"TURNSTILE_SITE_KEY=\n\n"
            f"# ===== 设备共享密钥 =====\n"
            f"# 调用后端 API 时的服务端鉴权（X-Device-Secret），留空则兼容旧版不发送\n"
            f"DEVICE_SECRET=\n\n"
            f"# ===== CORS 跨域白名单 =====\n"
            f"# 留空则默认仅允许本机；生产环境建议填前端可访问的来源，逗号分隔\n"
            f"ALLOWED_ORIGINS=http://localhost:4430,http://127.0.0.1:4430\n\n"
            f"# ===== 服务监听 =====\n"
            f"SERVER_HOST=0.0.0.0\n\n"
            f"# 以下字段由 config.json 管理（Web 设置页可改），如需用 .env 覆盖可取消注释填写：\n"
            f"# SERVER_PORT=4430\n"
            f"# ELDERLY_SERVER_URL=https://my-website.ccwu.cc/eating-medication/server\n"
            f"# PATH_PREFIX=\n"
            f"# APP_NAME=子女守护中心\n"
            f"# DISPLAY_THEME=light\n"
            f"# DISPLAY_COLOR=purple\n"
            f"# DISPLAY_LANGUAGE=zh-CN\n"
            f"# DISPLAY_ANIMATIONS=True\n"
            f"# DISPLAY_COMPACT=False\n"
        )
        try:
            env_path.write_text(env_content, encoding='utf-8')
            # 设置文件权限为 600，仅所有者可读写（保护密钥）
            os.chmod(env_path, 0o600)
            logger.info(f"首次运行：已自动生成 {env_path}（含随机 SECRET_KEY，DEBUG=true）")
            logger.warning("生产部署时请将 .env 中 DEBUG 改为 false")
        except Exception as e:
            logger.warning(f"自动生成 .env 失败: {e}，将使用临时密钥启动")

    def _load_from_json(self):
        """从JSON配置文件加载配置到内部字典（不写回 os.environ）。
        首次运行（文件不存在）时自动生成适合本地运行的配置文件，无需手动复制模板。"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self._config_data = json.load(f)
            except Exception as e:
                logger.warning(f"加载配置文件失败: {e}，使用默认配置")
                self._config_data = {}
        else:
            # 首次运行：自动生成适合本地直连的配置文件
            logger.info(f"首次运行：配置文件不存在，自动生成 {self.config_file}")
            self._config_data = {
                'SERVER_HOST': '0.0.0.0',
                'SERVER_PORT': 4430,
                'ELDERLY_SERVER_URL': 'https://my-website.ccwu.cc/eating-medication/server',
                # 本地直连为空字符串；Cloudflare 隧道子路径部署时改为 /eating-medication/family
                'PATH_PREFIX': '',
                'APP_NAME': '子女守护中心',
                'DEBUG': 'False',
            }
            try:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(self._config_data, f, indent=2, ensure_ascii=False)
                logger.info(f"已自动生成配置文件: {self.config_file}（本地直连模式，PATH_PREFIX 为空）")
            except Exception as e:
                logger.warning(f"自动生成配置文件失败: {e}，使用内存默认配置")

    def save_config(self):
        """保存当前配置到JSON文件
        注意：SECRET_KEY 不写入 config.json，仅通过 .env 配置"""
        config_data = {
            'ELDERLY_SERVER_URL': self.ELDERLY_SERVER_URL,
            'SERVER_HOST': self.SERVER_HOST,
            'SERVER_PORT': self.SERVER_PORT,
            'DEBUG': str(self.DEBUG),
            'APP_NAME': self.APP_NAME,
            'PATH_PREFIX': self.PATH_PREFIX,
            'DISPLAY_THEME': self.DISPLAY_SETTINGS.get('theme', 'light'),
            'DISPLAY_COLOR': self.DISPLAY_SETTINGS.get('color', 'purple'),
            'DISPLAY_LANGUAGE': self.DISPLAY_SETTINGS.get('language', 'zh-CN'),
            'DISPLAY_ANIMATIONS': str(self.DISPLAY_SETTINGS.get('animations', True)),
            'DISPLAY_COMPACT': str(self.DISPLAY_SETTINGS.get('compact', False)),
        }

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"保存配置文件失败: {e}")
            return False


# 全局配置实例
config = Config()
