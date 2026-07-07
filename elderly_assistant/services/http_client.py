# -*- coding: utf-8 -*-
"""
HTTP 客户端模块
负责与服务器通信：设备注册、用药计划轮询、服药确认等
仅通过 device_id 标识设备
"""
import requests
from datetime import datetime
from services.device_id import get_device_id
from utils.logger import setup_logger

logger = setup_logger()


class HTTPClient:
    def __init__(self, config):
        self.config = config['server']
        self.base_url = self.config['base_url']
        self.timeout = self.config.get('timeout', 10)
        self.device_id = get_device_id()

    def _headers(self):
        """返回携带设备标识的请求头"""
        return {"X-Device-ID": self.device_id}

    def check_connection(self):
        """检查服务器连接状态"""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=3, headers=self._headers())
            return resp.status_code == 200
        except Exception as e:
            logger.debug(f"健康检查失败: {e}")
            return False

    def register_device(self, device_name=""):
        """向服务端注册本设备"""
        url = f"{self.base_url}/api/v1/public/device/register"
        try:
            resp = requests.post(
                url,
                json={"device_id": self.device_id, "device_name": device_name},
                timeout=self.timeout,
                headers=self._headers()
            )
            if resp.status_code == 200:
                logger.info("设备注册/心跳上报成功")
                return True
            else:
                logger.warning(f"设备注册失败，状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.warning(f"设备注册请求异常: {e}")
            return False

    def send_heartbeat(self):
        """向服务端发送心跳上报（每30秒调用一次，独立于业务轮询）"""
        return self.register_device()

    def unregister_device(self):
        """向服务端发送主动下线通知

        设备正常退出（SIGINT/SIGTERM/进程关闭）时调用，
        服务器收到后会立即将设备标记为离线，
        避免子女端在心跳超时窗口内看到虚假的"在线"状态。
        注意：超时设为 3 秒，避免退出清理阻塞过久。
        """
        url = f"{self.base_url}/api/v1/public/device/offline"
        try:
            resp = requests.post(
                url,
                json={"device_id": self.device_id},
                timeout=3,
                headers=self._headers()
            )
            if resp.status_code == 200:
                logger.info("设备下线通知成功")
                return True
            logger.warning(f"设备下线通知失败，状态码: {resp.status_code}")
            return False
        except Exception as e:
            logger.warning(f"设备下线通知异常: {e}")
            return False

    def get_medication_schedule(self):
        """
        拉取本设备的用药计划（每分钟轮询调用）
        GET /api/v1/public/device/schedule/{device_id}
        返回 schedules 列表，每项包含 drug_name, dosage, time, frequency
        """
        url = f"{self.base_url}/api/v1/public/device/schedule/{self.device_id}"
        try:
            resp = requests.get(url, timeout=self.timeout, headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                return data.get('schedules', []) or []
            return []
        except Exception as e:
            logger.warning(f"拉取用药计划异常: {e}")
            return []

    def confirm_medication(self, drug_name, dosage, taken_at=None):
        """
        上报服药确认（可选）
        POST /api/v1/public/device/message
        message_type=medication
        """
        if taken_at is None:
            taken_at = datetime.now().isoformat()
        url = f"{self.base_url}/api/v1/public/device/message"
        data = {
            "device_id": self.device_id,
            "message_type": "medication",
            "content": f"已服用 {drug_name} {dosage}",
            "data": {
                "drug_name": drug_name,
                "dosage": dosage,
                "taken_at": taken_at,
            },
        }
        try:
            resp = requests.post(url, json=data, timeout=self.timeout, headers=self._headers())
            if resp.status_code == 200:
                return True
            logger.warning(f"上报服药确认失败，状态码: {resp.status_code}")
            return False
        except Exception as e:
            logger.warning(f"上报服药确认异常: {e}")
            return False

    def upload_image(self, image_path, endpoint=None):
        if endpoint is None:
            endpoint = self.config['upload_endpoint']
        url = f"{self.base_url}{endpoint}"
        try:
            with open(image_path, 'rb') as f:
                files = {'file': f}
                resp = requests.post(url, files=files, timeout=self.timeout, headers=self._headers())
                if resp.status_code == 200:
                    return True
                logger.warning(f"上传图片失败，状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.warning(f"上传图片异常: {e}")
            return False

    def send_emergency(self):
        """向服务端发送紧急消息"""
        url = f"{self.base_url}/api/v1/public/device/message"
        try:
            resp = requests.post(
                url,
                json={"device_id": self.device_id, "message_type": "emergency", "content": "紧急求助"},
                timeout=self.timeout,
                headers=self._headers()
            )
            if resp.status_code == 200:
                return True
            logger.warning(f"发送紧急消息失败，状态码: {resp.status_code}")
            return False
        except Exception as e:
            logger.warning(f"发送紧急消息异常: {e}")
            return False

    def send_chat_message(self, sender, message):
        """向服务端发送聊天消息（通过公开接口）"""
        url = f"{self.base_url}/api/v1/public/device/message"
        data = {
            "device_id": self.device_id,
            "message_type": "chat",
            "content": message,
            "data": {"sender": sender}
        }
        try:
            resp = requests.post(url, json=data, timeout=self.timeout, headers=self._headers())
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"发送聊天消息失败，状态码: {resp.status_code}")
            return None
        except Exception as e:
            logger.warning(f"发送聊天消息异常: {e}")
            return None

    def upload_medicine_photo(self, image_path):
        """上传药品照片"""
        return self.upload_image(image_path)

    def ask_ai(self, question):
        """向服务端 AI 提问"""
        url = f"{self.base_url}/api/v1/public/ai/ask"
        data = {"question": question, "device_id": self.device_id}
        try:
            resp = requests.post(url, json=data, timeout=self.timeout, headers=self._headers())
            if resp.status_code == 200:
                result = resp.json()
                return result.get('answer', '抱歉，AI 没有返回答案')
            else:
                return f'抱歉，AI 服务出错了 (状态码: {resp.status_code})'
        except Exception as e:
            return f'抱歉，AI 服务暂时不可用: {str(e)}'

    def get_device_id(self):
        """返回当前设备标识符"""
        return self.device_id
