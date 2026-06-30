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
        self._load_from_json()

        self.SERVER_HOST = os.getenv('SERVER_HOST', '0.0.0.0')
        self.SERVER_PORT = int(os.getenv('SERVER_PORT', '4430'))

        self.ELDERLY_SERVER_URL = os.getenv('ELDERLY_SERVER_URL', 'http://localhost:1059')

        self.API_KEY = os.getenv('API_KEY', '')

        self.DISPLAY_SETTINGS = {
            'theme': os.getenv('DISPLAY_THEME', 'light'),
            'color': os.getenv('DISPLAY_COLOR', 'purple'),
            'language': os.getenv('DISPLAY_LANGUAGE', 'zh-CN'),
            'animations': os.getenv('DISPLAY_ANIMATIONS', 'True').lower() == 'true',
            'compact': os.getenv('DISPLAY_COMPACT', 'False').lower() == 'true',
        }

        self.DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

        self.APP_NAME = os.getenv('APP_NAME', '子女守护中心')

        self.SECRET_KEY = os.getenv('SECRET_KEY', _generate_secret_key())

        self.STATIC_DIR = self.BASE_DIR / 'static'
        self.TEMPLATES_DIR = self.BASE_DIR / 'templates'

        self.DATA_DIR = self.BASE_DIR / 'data'
        self.DATA_DIR.mkdir(exist_ok=True)

        # SSL证书配置（支持.pem, .crt, .cer, .key 等格式）
        self.SSL_CERTFILE = os.getenv('SSL_CERTFILE', '')
        self.SSL_KEYFILE = os.getenv('SSL_KEYFILE', '')
        self.SSL_CA_BUNDLE = os.getenv('SSL_CA_BUNDLE', '')

    def _load_from_json(self):
        """从JSON配置文件加载配置"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:        
                    config_data = json.load(f)
                    for key, value in config_data.items():
                        os.environ[key] = str(value)
            except Exception as e:
                print(f"加载配置文件失败: {e}")

    def save_config(self):
        """保存当前配置到JSON文件"""
        config_data = {
            'ELDERLY_SERVER_URL': self.ELDERLY_SERVER_URL,
            'API_KEY': self.API_KEY,
            'SERVER_HOST': self.SERVER_HOST,
            'SERVER_PORT': self.SERVER_PORT,
            'DEBUG': str(self.DEBUG),
            'APP_NAME': self.APP_NAME,
            'SECRET_KEY': self.SECRET_KEY,
            'SSL_CERTFILE': self.SSL_CERTFILE,
            'SSL_KEYFILE': self.SSL_KEYFILE,
            'SSL_CA_BUNDLE': self.SSL_CA_BUNDLE,
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