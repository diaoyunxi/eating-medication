# -*- coding: utf-8 -*-
"""配置加载模块 - 单一 .env 配置源（统一为扁平 .env）

所有老人端配置统一从 elderly_assistant/.env 读取（与 server / family_monitor 一致），
不再使用 config.yaml。首次运行无 .env 时自动生成完整模板（含全部字段默认值）。

【配置统一说明】
历史上使用 config.yaml（嵌套结构），存在大量死配置（ai.*、server.*_endpoint、
server.method）与幽灵字段（paths.log_dir、speech.*）。现已统一为扁平 .env 并删除
所有死配置/幽灵字段，仅保留实际生效的字段：

- server   : base_url / upload_endpoint / timeout / heartbeat_interval
- hotspot  : ssid / ip / web_port
- reminder : poll_interval / snooze_minutes / buzzer_loop_interval
- camera   : connection / uart_tty / uart_baudrate / save_path

为兼容既有代码的字典访问方式（config.get('server', {}).get('base_url')），本模块
将扁平 .env 键组装为嵌套字典返回；同时提供 save_server_url() 供配网 Web 服务改写
服务器地址（写入 SERVER_BASE_URL）。
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger("ElderlyAssistant")

BASE_DIR = Path(__file__).resolve().parent.parent  # elderly_assistant/
ENV_PATH = BASE_DIR / ".env"

# 默认配置（嵌套结构，分组与历史 config.yaml 兼容的访问路径）
DEFAULT_CONFIG = {
    "server": {
        "base_url": "http://localhost:1059",
        "upload_endpoint": "/api/upload",
        "timeout": 10,
        "heartbeat_interval": 30,
    },
    "hotspot": {
        "ssid": "M10-Config",
        "ip": "10.0.0.1",
        "web_port": 8088,
    },
    "reminder": {
        "poll_interval": 60,
        "snooze_minutes": 5,
        "buzzer_loop_interval": 3,
        "long_press_sec": 1.5,
    },
    "camera": {
        "connection": "i2c",
        "uart_tty": "/dev/ttyS1",
        "uart_baudrate": 115200,
        "save_path": "data/captures",
    },
}

# 扁平 .env 键 → (嵌套分组, 嵌套键, 类型) 映射；唯一事实来源
_ENV_LEAVES = [
    ("SERVER_BASE_URL", "server", "base_url", str),
    ("SERVER_UPLOAD_ENDPOINT", "server", "upload_endpoint", str),
    ("SERVER_TIMEOUT", "server", "timeout", int),
    ("HEARTBEAT_INTERVAL", "server", "heartbeat_interval", int),
    ("HOTSPOT_SSID", "hotspot", "ssid", str),
    ("HOTSPOT_IP", "hotspot", "ip", str),
    ("HOTSPOT_WEB_PORT", "hotspot", "web_port", int),
    ("POLL_INTERVAL", "reminder", "poll_interval", int),
    ("SNOOZE_MINUTES", "reminder", "snooze_minutes", int),
    ("BUZZER_LOOP_INTERVAL", "reminder", "buzzer_loop_interval", int),
    ("LONG_PRESS_SEC", "reminder", "long_press_sec", float),
    ("CAMERA_CONNECTION", "camera", "connection", str),
    ("CAMERA_UART_TTY", "camera", "uart_tty", str),
    ("CAMERA_UART_BAUDRATE", "camera", "uart_baudrate", int),
    ("CAMERA_SAVE_PATH", "camera", "save_path", str),
]

# .env 模板（首运行自动生成）
_ENV_TEMPLATE = (
    "# 老人端配置（扁平 .env，与 server / family_monitor 统一）\n"
    "# 首次运行自动生成，可手动修改；修改后重启生效\n\n"
    "# ===== 服务端地址 =====\n"
    "SERVER_BASE_URL=http://localhost:1059\n"
    "SERVER_UPLOAD_ENDPOINT=/api/upload\n"
    "SERVER_TIMEOUT=10\n"
    "HEARTBEAT_INTERVAL=30\n\n"
    "# ===== 热点配网 =====\n"
    "HOTSPOT_SSID=M10-Config\n"
    "HOTSPOT_IP=10.0.0.1\n"
    "HOTSPOT_WEB_PORT=8088\n\n"
    "# ===== 提醒 =====\n"
    "POLL_INTERVAL=60\n"
    "SNOOZE_MINUTES=5\n"
    "BUZZER_LOOP_INTERVAL=3\n"
    "LONG_PRESS_SEC=1.5\n\n"
    "# ===== 摄像头 =====\n"
    "CAMERA_CONNECTION=i2c\n"
    "CAMERA_UART_TTY=/dev/ttyS1\n"
    "CAMERA_UART_BAUDRATE=115200\n"
    "CAMERA_SAVE_PATH=data/captures\n"
)


def _ensure_env_template():
    """首次运行无 .env 时自动生成完整模板（开箱即用），已存在则不覆盖。"""
    try:
        if ensure_env_template(ENV_PATH, _ENV_TEMPLATE):
            logger.info(f"首次运行：已自动生成 {ENV_PATH}（含全部默认配置项）")
    except Exception as e:
        logger.warning(f"自动生成 .env 模板失败: {e}")


def _coerce(value, typ):
    """将字符串配置值按目标类型转换；失败时回退默认值（调用方提供）。"""
    if typ is int:
        try:
            return int(str(value).strip())
        except (ValueError, TypeError):
            return 0
    return str(value).strip()


def load_config(config_path=ENV_PATH):
    """加载配置，组装为嵌套字典（扁平 .env → 嵌套结构）。

    - 首次运行无 .env 时自动生成模板
    - 以 DEFAULT_CONFIG 为基础，用 .env 中的扁平键覆盖对应嵌套字段
    - 返回深拷贝，避免外部修改污染源默认值
    """
    import copy

    _ensure_env_template()
    load_dotenv(config_path)

    config = copy.deepcopy(DEFAULT_CONFIG)
    for env_key, group, key, typ in _ENV_LEAVES:
        raw = os.getenv(env_key)
        if raw is None or raw.strip() == "":
            continue
        if typ is int:
            # 整数转换失败时保留默认值，避免崩溃
            try:
                config[group][key] = int(raw.strip())
            except (ValueError, TypeError):
                logger.warning(f"配置 {env_key}={raw!r} 不是整数，保留默认值 {config[group][key]}")
        elif typ is float:
            # 浮点（如长按阈值）转换失败时保留默认值，避免崩溃
            try:
                config[group][key] = float(raw.strip())
            except (ValueError, TypeError):
                logger.warning(f"配置 {env_key}={raw!r} 不是数字，保留默认值 {config[group][key]}")
        else:
            config[group][key] = raw.strip()
    return config


def save_server_url(server_url, config_path=ENV_PATH):
    """保存服务器地址到 .env（改写 SERVER_BASE_URL 字段）。

    复用 common.envfile.update_env_fields，保留文件中其它字段与注释不变；
    wifi_config.WiFiConfigManager.save_server_url 亦委托本函数，故一并受益。

    :return: True 表示保存成功
    """
    server_url = (server_url or "").strip()
    try:
        from common.envfile import update_env_fields, ensure_env_template
        update_env_fields(config_path, {"SERVER_BASE_URL": server_url})
        logger.info(f"已保存服务器地址: {server_url}")
        return True
    except Exception as e:
        logger.error(f"保存服务器地址失败: {e}")
        return False
