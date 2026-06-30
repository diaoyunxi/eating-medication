# -*- coding: utf-8 -*-
"""
热点管理模块
行空板M10专用：创建无密码配置热点
- SSID: M10-Config（无密码）
- 热点IP: 10.0.0.1
- 配网Web端口: 8088
"""
import subprocess
import time
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

    def start_hotspot(self):
        """创建无密码热点（使用 nmcli 命令）"""
        try:
            # 先停止可能存在的同名连接
            subprocess.run(
                ["nmcli", "connection", "delete", self.ssid],
                capture_output=True, timeout=5
            )

            # 创建新的热点（无密码）
            # 通过 nmcli 创建 hotspot，并指定 SSID、频段、信道
            cmd = (
                f'nmcli device wifi hotspot '
                f'ssid "{self.ssid}" '
                f'band bg '
                f'channel 6'
            )
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=15
            )

            if result.returncode == 0:
                self.is_running = True
                logger.info(f"热点已创建: {self.ssid} (无密码)")
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
