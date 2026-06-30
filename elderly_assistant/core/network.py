# -*- coding: utf-8 -*-
import socket
import time
from utils.logger import setup_logger

class NetworkManager:
    """网络状态检测器，支持在线/离线判断"""

    def __init__(self, config):
        self.config = config.get('network', {})
        self.logger = setup_logger()
        self.online = False
        self.test_host = self.config.get('ping_host', '8.8.8.8')
        self.test_port = 53  # DNS 端口，一般不会被墙

    def check_online(self):
        """检测互联网连通性（使用 socket 连接公共 DNS）"""
        try:
            socket.setdefaulttimeout(3)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((self.test_host, self.test_port))
            sock.close()
            self.online = True
            return True
        except Exception:
            self.online = False
            return False

    def is_online(self):
        """返回当前缓存的在线状态（需先调用 check_online 更新）"""
        return self.online

    def wait_until_online(self, timeout=30, check_interval=2):
        """阻塞等待网络恢复，可用于离线时挂起操作"""
        start = time.time()
        while time.time() - start < timeout:
            if self.check_online():
                return True
            time.sleep(check_interval)
        return False
