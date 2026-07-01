# -*- coding: utf-8 -*-
"""配置管理模块 - 完善版"""

import os
import secrets
import json
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv


def _generate_secret_key():
    """生成安全的随机密钥"""
    return secrets.token_urlsafe(32)


class Config:
    """配置管理类"""

    def __init__(self):
        self.BASE_DIR = Path(__file__).resolve().parent.parent

        env_path = self.BASE_DIR / '.env'
        if env_path.exists():
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

        # 路径前缀（Cloudflare 隧道子路径），本地直连设为空
        self.PATH_PREFIX = os.getenv('PATH_PREFIX', self._config_data.get('PATH_PREFIX', '/eating-medication/family')).rstrip('/')

        self.DISPLAY_SETTINGS = {
            'theme': os.getenv('DISPLAY_THEME', self._config_data.get('DISPLAY_THEME', 'light')),
            'color': os.getenv('DISPLAY_COLOR', self._config_data.get('DISPLAY_COLOR', 'purple')),
            'language': os.getenv('DISPLAY_LANGUAGE', self._config_data.get('DISPLAY_LANGUAGE', 'zh-CN')),
            'animations': (os.getenv('DISPLAY_ANIMATIONS', str(self._config_data.get('DISPLAY_ANIMATIONS', 'True')))).lower() == 'true',
            'compact': (os.getenv('DISPLAY_COMPACT', str(self._config_data.get('DISPLAY_COMPACT', 'False')))).lower() == 'true',
        }

        self.DEBUG = os.getenv('DEBUG', str(self._config_data.get('DEBUG', 'False'))).lower() == 'true'

        self.APP_NAME = os.getenv('APP_NAME', self._config_data.get('APP_NAME', '子女守护中心'))

        # SECRET_KEY：优先从环境变量读取，其次从配置文件，均为空则生成临时密钥
        # 注意：SECRET_KEY 仅通过 .env 配置，不应写入 config.json
        secret_key = os.getenv('SECRET_KEY') or self._config_data.get('SECRET_KEY', '')
        if not secret_key:
            secret_key = _generate_secret_key()
            print("⚠️ SECRET_KEY 未配置，已生成临时密钥，重启后会话将失效。请通过 .env 配置 SECRET_KEY")
        self.SECRET_KEY = secret_key

        # CORS 允许的来源（逗号分隔），默认仅允许本地
        allowed_origins_env = os.getenv(
            'ALLOWED_ORIGINS',
            'http://localhost:4430,http://127.0.0.1:4430'
        )
        self.ALLOWED_ORIGINS = [o.strip() for o in allowed_origins_env.split(',') if o.strip()]

        # Cookie secure 标志：默认启用，本地 HTTP 调试时可设为 false
        self.COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'true').lower() == 'true'

        # 是否为生产环境（生产环境禁止通过 Web 修改 DEBUG）
        self.PRODUCTION = os.getenv('PRODUCTION', 'false').lower() == 'true'

        self.STATIC_DIR = self.BASE_DIR / 'static'
        self.TEMPLATES_DIR = self.BASE_DIR / 'templates'

        self.DATA_DIR = self.BASE_DIR / 'data'
        self.DATA_DIR.mkdir(exist_ok=True)

    def _load_from_json(self):
        """从JSON配置文件加载配置到内部字典（不写回 os.environ）"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self._config_data = json.load(f)
            except Exception as e:
                print(f"加载配置文件失败: {e}")
                self._config_data = {}
        else:
            self._config_data = {}

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
