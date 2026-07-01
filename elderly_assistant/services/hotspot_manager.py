# -*- coding: utf-8 -*-
"""
热点管理模块
行空板M10专用：创建带 WPA2 加密的配置热点
- SSID: M10-Config
- 热点IP: 10.0.0.1
- 配网Web端口: 8088
- 密码: 启动时随机生成（WPA2）
"""
import subprocess
import time
import secrets
from utils.logger import setup_logger

logger = setup_logger()

# 默认热点参数
HOTSPOT_SSID = "M10-Config"
HOTSPOT_IP = "10.0.0.1"
HOTSPOT_WEB_PORT = 8088


class HotspotManager:
    """热点管理器"""

    def __init__(self, ssid=HOTSPOT_SSID, ip=HOTSPOT_IP, web_port=HOTSPOT_WEB_PORT):
        self.ssid = ssid
        self.ip = ip
        self.web_port = web_port
        self.is_running = False
        # 生成 8 字节随机密码（WPA2 要求至少 8 个字符，token_urlsafe(8) 约生成 11 个字符）
        self.password = secrets.token_urlsafe(8)

    def start_hotspot(self):
        """创建带 WPA2 加密的热点（使用 nmcli 命令，列表形式传参）"""
        try:
            # 先停止可能存在的同名连接
            subprocess.run(
                ["nmcli", "connection", "delete", self.ssid],
                capture_output=True, timeout=5
            )

            # 创建新的热点（带 WPA2 密码）
            # 使用列表形式传参，避免 shell 注入风险
            cmd = [
                "nmcli", "device", "wifi", "hotspot",
                "ssid", self.ssid,
                "band", "bg",
                "channel", "6",
                "password", self.password,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15, check=False
            )

            if result.returncode == 0:
                self.is_running = True
                logger.info(f"热点已创建: {self.ssid} (WPA2 加密)")
                # 启动时打印/显示热点密码，便于用户连接
                logger.info(f"热点密码: {self.password}")
                print(f"[热点] SSID: {self.ssid}  密码: {self.password}")
                logger.info(
                    f"用户连接后可访问 http://{self.ip}:{self.web_port} 进行配网"
                )
                return True
            else:
                logger.error(f"热点创建失败: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("热点创建超时")
            return False
        except Exception as e:
            logger.error(f"热点创建异常: {e}")
            return False

    def stop_hotspot(self):
        """停止热点"""
        try:
            subprocess.run(
                ["nmcli", "connection", "delete", self.ssid],
                capture_output=True, timeout=5
            )
            self.is_running = False
            logger.info("热点已停止")
            return True
        except Exception as e:
            logger.error(f"热点停止失败: {e}")
            return False

    def is_active(self):
        """检查热点是否活跃"""
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"],
                capture_output=True, text=True, timeout=5
            )
            return self.ssid in result.stdout
        except Exception:
            return False
