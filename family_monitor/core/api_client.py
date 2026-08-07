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
from collections import defaultdict
from datetime import datetime, timedelta
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

    @staticmethod
    def _extract_error(response) -> str:
        """从服务端非 200 响应中提取可读错误信息

        服务端 HTTPException 返回 ``{"detail": "..."}``，
        family_monitor BFF 返回 ``{"success": false, "message": "..."}``，
        其他情况回退为状态码。

        :param response: httpx.Response 对象
        :return: 可直返前端的错误文案
        """
        try:
            body = response.json()
            if isinstance(body, dict):
                # FastAPI HTTPException 格式
                detail = body.get("detail")
                if detail:
                    return str(detail)
                # BFF JSONResponse 格式
                message = body.get("message")
                if message:
                    return str(message)
        except Exception:
            pass
        return f"服务端返回状态码: {response.status_code}"

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
        product_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """设置/添加用药计划

        调用 POST /api/v1/public/device/medication_plan
        """
        if not self._device_id:
            return {"success": False, "error": "未绑定 M10 设备，请先在设置页面绑定设备后再添加用药计划"}

        # remaining_quantity 未指定时默认等于 total_quantity
        if remaining_quantity is None:
            remaining_quantity = total_quantity

        payload = {
            "device_id": self._device_id,
            "drug_name": drug_name,
            "dosage": dosage,
            "product_code": product_code,
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
                return {"success": False, "error": self._extract_error(response)}
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
                return {"success": False, "error": self._extract_error(response)}
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
        product_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """更新用药计划

        调用 PUT /api/v1/public/device/medication_plan/{plan_id}
        """
        if not self._device_id:
            return {"success": False, "error": "未绑定 M10 设备，请先在设置页面绑定设备后再更新用药计划"}

        if remaining_quantity is None:
            remaining_quantity = total_quantity

        payload = {
            "device_id": self._device_id,
            "drug_name": drug_name,
            "dosage": dosage,
            "product_code": product_code,
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
                return {"success": False, "error": self._extract_error(response)}
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
        """获取仪表板数据（基于真实提醒和记录计算，无虚假数据）"""
        try:
            reminders = await self.get_reminders()
            records = await self.get_medication_records()

            # ---- 摘要 ----
            total_reminders = len(reminders)
            active_reminders = len([r for r in reminders if r.get('enabled', True)])
            taken_today = len([r for r in reminders if r.get('taken_today', False)])
            pending_today = active_reminders - taken_today

            total_records = len(records)
            # status 字段: "taken" 表示已服药
            taken_records = len([r for r in records if r.get('status') == 'taken'])
            adherence_rate = int((taken_records / total_records * 100) if total_records > 0 else 0)

            # ---- 药品列表（从 plans 提取） ----
            medications = [
                {
                    'id': p.get('id'),
                    'name': p.get('drug_name', '未知药品'),
                    'dosage': p.get('dosage', ''),
                    'frequency': p.get('frequency', ''),
                    'schedule_times': p.get('schedule_times', []),
                    'total_quantity': p.get('total_quantity', 0),
                    'remaining_quantity': p.get('remaining_quantity', 0),
                    'unit': p.get('unit', ''),
                    'low_stock_threshold': p.get('low_stock_threshold', 0),
                }
                for p in reminders
            ]

            # ---- 构建 plan_id → drug_name 映射 ----
            plan_drug_map = {p.get('id'): p.get('drug_name', '未知药品') for p in reminders}

            # ---- 7天趋势：按日期分组统计 taken / missed / scheduled ----
            today = datetime.now().date()
            date_labels = []
            trend_taken = []
            trend_scheduled = []
            trend_missed = []

            for i in range(6, -1, -1):
                d = today - timedelta(days=i)
                date_labels.append(d.strftime('%m-%d'))
                day_taken = 0
                day_scheduled = 0
                day_missed = 0
                for r in records:
                    scheduled_str = r.get('scheduled_time', '')
                    if not scheduled_str:
                        continue
                    try:
                        scheduled_date = datetime.fromisoformat(scheduled_str).date()
                    except (ValueError, TypeError):
                        continue
                    if scheduled_date == d:
                        day_scheduled += 1
                        status = r.get('status', '')
                        if status == 'taken':
                            day_taken += 1
                        elif status == 'missed':
                            day_missed += 1
                # 未记录的也计入漏服
                day_missed += max(0, day_scheduled - day_taken - day_missed)
                trend_taken.append(day_taken)
                trend_scheduled.append(day_scheduled)
                trend_missed.append(day_missed)

            # ---- 按药品统计服药次数 ----
            drug_stats = defaultdict(lambda: {'taken': 0, 'missed': 0, 'total': 0})
            for r in records:
                plan_id = r.get('plan_id')
                drug_name = plan_drug_map.get(plan_id, '未知药品')
                drug_stats[drug_name]['total'] += 1
                if r.get('status') == 'taken':
                    drug_stats[drug_name]['taken'] += 1
                elif r.get('status') == 'missed':
                    drug_stats[drug_name]['missed'] += 1

            # ---- 日历热力图数据：按日期统计服药次数 ----
            calendar_data = []
            cal_by_date = defaultdict(int)
            for r in records:
                taken_str = r.get('taken_time', '')
                if not taken_str:
                    scheduled_str = r.get('scheduled_time', '')
                    if scheduled_str:
                        taken_str = scheduled_str
                if taken_str:
                    try:
                        cal_date = datetime.fromisoformat(taken_str).strftime('%Y-%m-%d')
                        if r.get('status') == 'taken':
                            cal_by_date[cal_date] += 1
                    except (ValueError, TypeError):
                        continue
            for date_str, count in cal_by_date.items():
                calendar_data.append([date_str, count])

            # ---- 药品 × 星期 热力矩阵 ----
            weekday_labels = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            drug_names_list = [m['name'] for m in medications] if medications else []
            heat_matrix = []
            if drug_names_list:
                for di, dname in enumerate(drug_names_list):
                    for wi in range(7):
                        count = 0
                        for r in records:
                            if plan_drug_map.get(r.get('plan_id')) != dname:
                                continue
                            scheduled_str = r.get('scheduled_time', '')
                            if not scheduled_str:
                                continue
                            try:
                                scheduled_date = datetime.fromisoformat(scheduled_str)
                            except (ValueError, TypeError):
                                continue
                            if scheduled_date.weekday() == wi and r.get('status') == 'taken':
                                count += 1
                        heat_matrix.append([di, wi, count])

            # ---- 甘特图：各药品服药时段 ----
            gantt_data = []
            for m in medications:
                times = m.get('schedule_times', [])
                for t_str in times:
                    try:
                        hour = int(t_str.split(':')[0])
                        gantt_data.append({
                            'name': m['name'],
                            'start': hour,
                            'end': hour + 1
                        })
                    except (ValueError, IndexError):
                        continue

            # ---- funnel 漏斗数据 ----
            funnel_data = [
                {'value': total_records, 'name': '总记录'},
                {'value': taken_records, 'name': '已服药'},
                {'value': total_records - taken_records, 'name': '未服药'},
            ]

            # ---- 近期活动（从 records 构建） ----
            recent_activities = []
            for r in records[:5]:
                drug_name = plan_drug_map.get(r.get('plan_id'), '未知药品')
                status = r.get('status', '')
                action = '已服用' if status == 'taken' else ('漏服' if status == 'missed' else '待服')
                time_str = r.get('taken_time') or r.get('scheduled_time') or ''
                recent_activities.append({
                    'id': r.get('id'),
                    'type': 'medication',
                    'action': action,
                    'name': drug_name,
                    'time': time_str,
                    'icon': '💊'
                })

            # ---- 即将到来的提醒 ----
            upcoming = []
            for p in reminders[:5]:
                times = p.get('schedule_times', [])
                upcoming.append({
                    'id': p.get('id'),
                    'name': p.get('drug_name', '未知药品'),
                    'time': ', '.join(times) if times else p.get('frequency', ''),
                    'status': 'pending'
                })

            return {
                'summary': {
                    'total_reminders': total_reminders,
                    'active_reminders': active_reminders,
                    'taken_today': taken_today,
                    'pending_today': pending_today,
                    'adherence_rate': adherence_rate,
                    'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                },
                'upcoming_reminders': upcoming,
                'recent_activities': recent_activities,
                'medications': medications,
                'chart_data': {
                    'days': date_labels,
                    'taken': trend_taken,
                    'scheduled': trend_scheduled,
                    'missed': trend_missed,
                    'drug_stats': dict(drug_stats),
                    'calendar': calendar_data,
                    'heat_matrix': heat_matrix,
                    'drug_names': drug_names_list,
                    'gantt': gantt_data,
                    'funnel': funnel_data,
                }
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
            'chart_data': {},
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
