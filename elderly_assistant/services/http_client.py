# -*- coding: utf-8 -*-
"""
HTTP 客户端模块
负责与服务器通信：设备注册、用药计划轮询、服药确认等
F1 修复：持久化并传递 device_token（X-Device-Token），与服务端 C5 机制对齐
"""
import os
import json
import requests
from services.device_id import get_device_id
from utils.logger import setup_logger

logger = setup_logger()

# device_token 持久化文件（与 device_id.txt 同目录）
_TOKEN_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "device_token.json"
)


def _load_device_token():
    """从本地文件加载已保存的 device_token"""
    try:
        if os.path.exists(_TOKEN_FILE):
            with open(_TOKEN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('device_token')
    except Exception as e:
        logger.warning(f"加载 device_token 失败: {e}")
    return None


def _save_device_token(token):
    """持久化 device_token 到本地文件"""
    try:
        os.makedirs(os.path.dirname(_TOKEN_FILE), exist_ok=True)
        with open(_TOKEN_FILE, 'w', encoding='utf-8') as f:
            json.dump({'device_token': token}, f, ensure_ascii=False)
        # 设置文件权限 0600，防止其他用户读取 token
        os.chmod(_TOKEN_FILE, 0o600)
    except Exception as e:
        logger.warning(f"保存 device_token 失败: {e}")


class HTTPClient:
    def __init__(self, config):
        self.config = config['server']
        self.base_url = self.config['base_url']
        self.timeout = self.config.get('timeout', 10)
        self.device_id = get_device_id()
        # F1：加载已保存的 device_token
        self.device_token = _load_device_token()

    def _headers(self):
        """返回携带设备标识与 token 的请求头"""
        headers = {"X-Device-ID": self.device_id}
        # F1：已注册设备附带 device_token
        if self.device_token:
            headers["X-Device-Token"] = self.device_token
        return headers

    def check_connection(self):
        """检查服务器连接状态"""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=3, headers=self._headers())
            return resp.status_code == 200
        except Exception as e:
            logger.debug(f"健康检查失败: {e}")
            return False

    def register_device(self, device_name=""):
        """向服务端注册本设备，保存返回的 device_token（F1 修复）"""
        url = f"{self.base_url}/api/v1/public/device/register"
        try:
            resp = requests.post(
                url,
                json={"device_id": self.device_id, "device_name": device_name},
                timeout=self.timeout,
                headers=self._headers()
            )
            if resp.status_code == 200:
                data = resp.json()
                # F1：服务端首次注册或 legacy 升级时会返回 device_token
                token = data.get('device_token')
                if token:
                    self.device_token = token
                    _save_device_token(token)
                    logger.info("设备注册成功，已保存 device_token")
                else:
                    logger.info("设备心跳上报成功")
                return True
            else:
                logger.warning(f"设备注册失败，状态码: {resp.status_code}")
                return False
        except Exception as e:
            logger.warning(f"设备注册请求异常: {e}")
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
            # F1：token 失效（401）时清除本地 token，下次注册重新获取
            if resp.status_code == 401:
                logger.warning("拉取用药计划鉴权失败，device_token 可能已失效")
                self.device_token = None
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
        from datetime import datetime
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
        with open(image_path, 'rb') as f:
            files = {'file': f}
            try:
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
            return resp.json()
        except Exception as e:
            logger.warning(f"发送聊天消息异常: {e}")
            return None

    def get_chat_messages(self, since_id=0):
        """获取聊天消息"""
        url = f"{self.base_url}/api/v1/public/device/message"
        try:
            resp = requests.get(url, timeout=self.timeout, headers=self._headers())
            return resp.json()
        except Exception as e:
            logger.warning(f"获取聊天消息异常: {e}")
            return []

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
