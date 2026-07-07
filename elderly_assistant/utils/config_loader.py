# -*- coding: utf-8 -*-
import yaml
import os

DEFAULT_CONFIG = {
    "server": {
        "base_url": "http://localhost:1059",
        "upload_endpoint": "/api/upload",
        "medication_log_endpoint": "/api/log",
        "emergency_endpoint": "/api/emergency",
        "chat_endpoint": "/api/chat",
        "method": "POST",
        "timeout": 10
    },
    "hotspot": {
        "ssid": "M10-Config",
        "ip": "10.0.0.1",
        "web_port": 8088
    },
    "reminder": {
        "poll_interval": 60,        # 用药计划轮询间隔（秒）
        "snooze_minutes": 5,        # 按钮B暂缓提醒的分钟数
        "buzzer_loop_interval": 3   # 蜂鸣器循环提醒间隔（秒）
    },
    "camera": {
        "connection": "i2c",
        "uart_tty": "/dev/ttyS1",
        "uart_baudrate": 115200,
        "save_path": "data/captures"
    }
}


def load_config(config_path="config.yaml"):
    """加载配置，如文件不存在或为空则返回默认配置"""
    if not os.path.exists(config_path):
        _save_default_config(config_path)
        return DEFAULT_CONFIG.copy()
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                _save_default_config(config_path)
                return DEFAULT_CONFIG.copy()
            config = yaml.safe_load(content)
            if config is None:
                _save_default_config(config_path)
                return DEFAULT_CONFIG.copy()
    except Exception:
        _save_default_config(config_path)
        return DEFAULT_CONFIG.copy()

    # 深度合并默认值，保证新字段出现
    merged = _deep_merge(DEFAULT_CONFIG.copy(), config)
    return merged


def save_config(config, config_path="config.yaml"):
    """保存配置到文件"""
    os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _save_default_config(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(DEFAULT_CONFIG, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _deep_merge(default, override):
    """深度合并字典"""
    result = default.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
