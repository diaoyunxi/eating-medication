# -*- coding: utf-8 -*-
"""
老人端API客户端 - 支持 device_id 绑定
HTTPS 连接由系统默认 SSL 上下文验证（Cloudflare 隧道公网证书）。
device_id 在拼接 URL 时使用 urllib.parse.quote 编码，防止特殊字符注入。

本模块基于 common.server_client.BaseServerClient 实现：统一了 httpx 客户端的创建、
SSL 上下文、认证头合并与 URL 拼接，消除了原先散落的重复请求代码。
"""

import json
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

from core.config import config
from common.server_client import BaseServerClient, encode_device_id


# 历史兼容别名：保持 test_family_api_client 等既有引用可用
_encode_device_id = encode_device_id


class ElderlyAPIClient(BaseServerClient):
    """老人端API客户端"""

    def __init__(self):
        super().__init__(base_url=config.ELDERLY_SERVER_URL, timeout=10.0)
        self._device_id = self._load_bound_device_id()
        self._device_token = self._load_device_token()

    def _auth_headers(self) -> Dict[str, str]:
        """返回携带设备ID和设备令牌的请求头"""
        headers = {}
        if self._device_id:
            headers["X-Device-ID"] = self._device_id
        # 移除无效的 X-Device-Secret（server 端从未校验此头）
        # 改为发送 X-Device-Token（server 端实际校验的设备令牌）
        if self._device_token:
            headers["X-Device-Token"] = self._device_token
        return headers

    def _load_bound_device_id(self) -> Optional[str]:
        """加载已绑定的设备ID"""
        device_file = config.DATA_DIR / "bound_device.json"
        if device_file.exists():
            try:
                with open(device_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('device_id')
            except Exception:
                pass
        return None

    def _load_device_token(self) -> Optional[str]:
        """加载已绑定的设备令牌"""
        device_file = config.DATA_DIR / "bound_device.json"
        if device_file.exists():
            try:
                with open(device_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('device_token')
            except Exception:
                pass
        return None

    def save_bound_device(self, device_id: str, device_name: str = "", device_token: str = ""):
        """保存绑定的设备ID和令牌

        当 device_token 为空时保留已有 token，防止重新绑定覆盖。
        """
        device_file = config.DATA_DIR / "bound_device.json"
        # 若未传入新 token，保留已有的 token（防止重新绑定时覆盖丢失）
        if not device_token:
            device_token = self._device_token or ""
        data = {
            'device_id': device_id,
            'device_name': device_name,
            'device_token': device_token,
            'bound_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(device_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.chmod(device_file, 0o600)
        self._device_id = device_id
        self._device_token = device_token if device_token else None

    def get_bound_device(self) -> Optional[Dict[str, str]]:
        """获取已绑定的设备信息"""
        device_file = config.DATA_DIR / "bound_device.json"
        if device_file.exists():
            try:
                with open(device_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def clear_bound_device(self):
        """解绑设备

        原代码仅清除 _device_id，未清除 _device_token，
        导致解绑后设备令牌仍残留内存中，后续请求仍携带旧 token。
        """
        device_file = config.DATA_DIR / "bound_device.json"
        if device_file.exists():
            device_file.unlink()
        self._device_id = None
        self._device_token = None

    async def register_device(self, device_id: str, device_name: str = "") -> Dict[str, Any]:
        """向服务端注册/绑定设备"""
        try:
            response = await self._execute(
                "POST", "/api/v1/public/device/register",
                json_body={"device_id": device_id, "device_name": device_name},
            )
            if response.status_code == 200:
                resp_data = response.json()
                # 透传 device_token（仅新设备返回）
                token = resp_data.get("device_token", "")
                self.save_bound_device(device_id, device_name, token)
                return {"success": True, "data": resp_data}
            else:
                return {"success": False, "error": f"状态码: {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def check_device(self, device_id: str) -> Dict[str, Any]:
        """检查设备是否已在服务端注册

        调用 GET /api/v1/public/device/check/{device_id}
        返回 {exists, device_id, device_name, created_at}
        """
        try:
            encoded_id = _encode_device_id(device_id)
            response = await self._execute("GET", f"/api/v1/public/device/check/{encoded_id}")
            if response.status_code == 200:
                data = response.json()
                return {"success": True, "data": data}
            else:
                return {"success": False, "error": f"状态码: {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_device_plans(self) -> List[Dict[str, Any]]:
        """获取当前绑定设备的所有用药计划

        调用 GET /api/v1/public/device/plans/{self._device_id}
        """
        if not self._device_id:
            return []
        try:
            encoded_id = _encode_device_id(self._device_id)
            response = await self._execute("GET", f"/api/v1/public/device/plans/{encoded_id}")
            if response.status_code == 200:
                data = response.json()
                # 服务端返回 {device_id, plans: [...]}
                if isinstance(data, dict):
                    return data.get('plans', []) or []
                return data or []
            return []
        except Exception:
            return []

    async def set_medication_plan(
        self,
        drug_name: str,
        dosage: str,
        schedule_times: List[str],
        frequency: str = "daily",
        total_quantity: int = 0,
        remaining_quantity: Optional[int] = None,
        unit: str = "片",
        low_stock_threshold: int = 5,
    ) -> Dict[str, Any]:
        """设置/添加用药计划

        调用 POST /api/v1/public/device/medication_plan
        """
        if not self._device_id:
            return {"success": False, "error": "未绑定设备，请先绑定设备"}

        # remaining_quantity 未指定时默认等于 total_quantity
        if remaining_quantity is None:
            remaining_quantity = total_quantity

        payload = {
            "device_id": self._device_id,
            "drug_name": drug_name,
            "dosage": dosage,
            "frequency": frequency,
            "schedule_times": schedule_times,
            "total_quantity": total_quantity,
            "remaining_quantity": remaining_quantity,
            "unit": unit,
            "low_stock_threshold": low_stock_threshold,
        }
        try:
            response = await self._execute(
                "POST", "/api/v1/public/device/medication_plan", json_body=payload
            )
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            else:
                return {"success": False, "error": f"状态码: {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def delete_medication_plan(self, plan_id: int) -> Dict[str, Any]:
        """删除用药计划

        调用 DELETE /api/v1/public/device/medication_plan/{plan_id}
        """
        try:
            response = await self._execute(
                "DELETE", f"/api/v1/public/device/medication_plan/{plan_id}"
            )
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            else:
                return {"success": False, "error": f"状态码: {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def update_medication_plan(
        self,
        plan_id: int,
        drug_name: str,
        dosage: str,
        schedule_times: List[str],
        frequency: str = "daily",
        total_quantity: int = 0,
        remaining_quantity: Optional[int] = None,
        unit: str = "片",
        low_stock_threshold: int = 5,
    ) -> Dict[str, Any]:
        """更新用药计划

        调用 PUT /api/v1/public/device/medication_plan/{plan_id}
        """
        if not self._device_id:
            return {"success": False, "error": "未绑定设备，请先绑定设备"}

        if remaining_quantity is None:
            remaining_quantity = total_quantity

        payload = {
            "device_id": self._device_id,
            "drug_name": drug_name,
            "dosage": dosage,
            "frequency": frequency,
            "schedule_times": schedule_times,
            "total_quantity": total_quantity,
            "remaining_quantity": remaining_quantity,
            "unit": unit,
            "low_stock_threshold": low_stock_threshold,
        }
        try:
            response = await self._execute(
                "PUT", f"/api/v1/public/device/medication_plan/{plan_id}", json_body=payload
            )
            if response.status_code == 200:
                return {"success": True, "data": response.json()}
            else:
                return {"success": False, "error": f"状态码: {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_device_info(self) -> Dict[str, Any]:
        """从服务端获取老人端设备信息"""
        if not self._device_id:
            return {
                'connected': False,
                'device_id': None,
                'device_name': '未绑定设备',
                'status': '未绑定'
            }

        try:
            encoded_id = _encode_device_id(self._device_id)
            response = await self._execute("GET", f"/api/v1/public/device/status/{encoded_id}")
            if response.status_code == 200:
                data = response.json()
                # 根据服务端返回的 is_online 判断真实在线状态
                is_online = data.get('is_online', False)
                return {
                    'connected': is_online,
                    'device_id': data.get('device_id'),
                    'device_name': data.get('device_name'),
                    'role': data.get('role'),
                    'created_at': data.get('created_at'),
                    'total_plans': data.get('total_plans', 0),
                    'total_records': data.get('total_records', 0),
                    'status': data.get('status', 'offline'),
                    'last_heartbeat': data.get('last_heartbeat'),
                    'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
            return {
                'connected': False,
                'device_id': self._device_id,
                'device_name': '设备离线',
                'status': 'offline'
            }
        except Exception:
            return {
                'connected': False,
                'device_id': self._device_id,
                'device_name': '设备离线',
                'status': 'offline'
            }

    async def get_reminders(self) -> List[Dict[str, Any]]:
        """获取提醒列表（改用公开接口 /device/plans）"""
        if not self._device_id:
            return []
        try:
            encoded_id = _encode_device_id(self._device_id)
            response = await self._execute("GET", f"/api/v1/public/device/plans/{encoded_id}")
            if response.status_code == 200:
                data = response.json()
                return data.get('plans', []) or []
            return []
        except Exception:
            pass
        return []

    async def get_medication_records(self) -> List[Dict[str, Any]]:
        """获取用药记录（改用公开接口 /device/records）"""
        if not self._device_id:
            return []
        try:
            encoded_id = _encode_device_id(self._device_id)
            response = await self._execute("GET", f"/api/v1/public/device/records/{encoded_id}")
            if response.status_code == 200:
                data = response.json()
                return data.get('records', []) or []
            return []
        except Exception:
            pass
        return []

    async def get_dashboard_data(self) -> Dict[str, Any]:
        """获取仪表板数据"""
        try:
            reminders = await self.get_reminders()
            records = await self.get_medication_records()

            total_reminders = len(reminders)
            active_reminders = len([r for r in reminders if r.get('enabled', True)])
            taken_today = len([r for r in reminders if r.get('taken_today', False)])
            pending_today = active_reminders - taken_today

            total_records = len(records)
            confirmed_records = len([r for r in records if r.get('confirmed', False)])
            adherence_rate = int((confirmed_records / total_records * 100) if total_records > 0 else 0)

            return {
                'summary': {
                    'total_reminders': total_reminders,
                    'active_reminders': active_reminders,
                    'taken_today': taken_today,
                    'pending_today': pending_today,
                    'adherence_rate': adherence_rate,
                    'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                },
                'upcoming_reminders': [
                    {'id': r.get('id'), 'name': r.get('name'), 'time': r.get('time'), 'status': 'pending'}
                    for r in reminders[:5] if r.get('enabled', True)
                ],
                'recent_activities': [
                    {'id': r.get('id'), 'type': 'medication', 'action': '已服用',
                     'name': r.get('medication_name'), 'time': r.get('taken_at'), 'icon': '💊'}
                    for r in records[:5]
                ],
                'chart_data': [],
                'medications': []
            }
        except Exception:
            pass

        return {
            'summary': {
                'total_reminders': 0, 'active_reminders': 0,
                'taken_today': 0, 'pending_today': 0,
                'adherence_rate': 0,
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            },
            'upcoming_reminders': [],
            'recent_activities': [],
            'chart_data': [],
            'medications': []
        }

    async def get_chat_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取聊天历史（通过公开接口获取）"""
        if not self._device_id:
            return []
        try:
            encoded_id = _encode_device_id(self._device_id)
            response = await self._execute(
                "GET", f"/api/v1/public/device/chat_history/{encoded_id}",
                params={"limit": limit},
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('messages', []) or []
            return []
        except Exception:
            pass
        return []

    async def get_server_status(self) -> Dict[str, Any]:
        """获取服务器状态"""
        is_connected = await self.check_connection()
        bound = self.get_bound_device()
        return {
            'connected': is_connected,
            'url': self.base_url,
            'device_id': bound.get('device_id') if bound else None,
            'device_name': bound.get('device_name', '') if bound else '',
            'last_check': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }


# 全局客户端实例
elderly_client = ElderlyAPIClient()
