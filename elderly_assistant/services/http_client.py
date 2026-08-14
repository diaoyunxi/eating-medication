# -*- coding: utf-8 -*-
"""
HTTP 客户端模块
负责与服务器通信：设备注册、用药计划轮询、服药确认等
通过 device_id + device_token 标识和认证设备
"""
import logging
import os
import time
from datetime import datetime

import requests
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    ConnectTimeout,
    ReadTimeout,
    Timeout,
)

from services.device_id import get_device_id
from services.schedule_cache import load_schedules, save_schedules

logger = logging.getLogger("ElderlyAssistant")

# device_token 持久化文件路径
_TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "device_token.txt")

# === 偶发（瞬时）网络抖动的重试配置 ===
# 仅针对「连接层/传输层」的瞬时错误做重试，业务 4xx/5xx 不重试。
# 指数退避避免请求洪峰，缓解 #38「偶发服务端连接失败」（网络本身正常）的误报。
_MAX_CONNECT_RETRIES = 3
_RETRY_BACKOFF = 0.3  # 实际退避 = backoff * (2 ** 第几次重试)
# 连接/读取超时分设：健康检查等场景连接超时设短，避免阻塞过久
_CONNECT_TIMEOUT = 5
_READ_TIMEOUT = 10


def _load_device_token():
    """从本地文件加载设备令牌"""
    try:
        if os.path.exists(_TOKEN_FILE):
            with open(_TOKEN_FILE, 'r') as f:
                token = f.read().strip()
                if token:
                    return token
    except Exception as e:
        logger.warning(f"加载 device_token 失败: {e}")
    return None


def _save_device_token(token):
    """持久化设备令牌到本地文件"""
    try:
        os.makedirs(os.path.dirname(_TOKEN_FILE), exist_ok=True)
        with open(_TOKEN_FILE, 'w') as f:
            f.write(token)
        os.chmod(_TOKEN_FILE, 0o600)
        logger.info("device_token 已保存到本地")
    except Exception as e:
        logger.warning(f"保存 device_token 失败: {e}")


class HTTPClient:
    def __init__(self, config):
        # 安全取值，避免 config 缺少 server 键时构造崩溃
        server_cfg = config.get('server') or {}
        self.config = server_cfg
        self.base_url = server_cfg.get('base_url', '')
        if not self.base_url:
            raise ValueError("配置缺少 server.base_url，请检查 .env（SERVER_BASE_URL）")
        self.timeout = server_cfg.get('timeout', 10)
        self.device_id = get_device_id()
        # 加载持久化的 device_token
        self.device_token = _load_device_token()

    def _headers(self):
        """返回携带设备标识和令牌的请求头"""
        headers = {"X-Device-ID": self.device_id}
        if self.device_token:
            headers["X-Device-Token"] = self.device_token
        return headers

    @staticmethod
    def _mask_headers(headers):
        """复制请求头并脱敏设备令牌，便于日志展示而不泄露凭证。"""
        safe = {}
        for k, v in (headers or {}).items():
            if k.lower() == "x-device-token":
                v = f"{str(v)[:6]}****" if v else "****"
            safe[k] = v
        return safe

    @staticmethod
    def _redact_body(body):
        """请求体脱敏：image_base64 仅保留长度摘要，其余原样展示。"""
        if not isinstance(body, dict):
            return body
        safe = {}
        for k, v in body.items():
            if k == "image_base64":
                safe[k] = f"<base64 图片, 共 {len(str(v))} 字节>"
            else:
                safe[k] = v
        return safe

    @staticmethod
    def _is_transient_error(exc) -> bool:
        """判断是否为「瞬时」连接/传输层错误，可安全重试。

        仅包含网络层抖动（连接被重置、对端断开、DNS/连接超时、读取超时、
        代理错误等），业务层 HTTP 状态码（4xx/5xx）不在此列，由调用方按业务处理。
        """
        from requests.exceptions import (
            ConnectionError as _ConnErr,
            ConnectTimeout as _ConnTO,
            ReadTimeout as _ReadTO,
            Timeout as _TO,
            ChunkedEncodingError as _Chunked,
            ProxyError as _Proxy,
        )
        return isinstance(exc, (_ConnErr, _ConnTO, _ReadTO, _TO, _Chunked, _Proxy))

    def _request(self, method, url, *, log_level=logging.INFO, retries=_MAX_CONNECT_RETRIES,
                 **kwargs):
        """统一 HTTP 请求入口：记录每一次请求与响应的完整详情（含心跳/二哈上报等）。

        覆盖所有对外请求（注册/心跳/下线/拉计划/服药确认/图片上传/人脸上报/紧急/聊天/AI）。
        敏感处理：设备令牌仅保留前 6 位；图片 base64 仅记录字节数，不落盘原始数据。

        对瞬时网络错误（连接被重置/对端断开/超时等）做指数退避重试，
        缓解 #38「偶发服务端连接失败」：网络本身正常时，单次抖动不应被判定为断线。
        """
        req_headers = kwargs.get("headers") or {}
        safe_headers = self._mask_headers(req_headers)
        safe_body = self._redact_body(kwargs.get("json"))
        logger.log(log_level, "[HTTP请求] %s %s | 请求头=%s | 请求体=%s",
                   method, url, safe_headers, safe_body)
        last_exc = None
        for attempt in range(retries + 1):
            try:
                resp = requests.request(method, url, **kwargs)
                break
            except Exception as e:  # noqa: BLE001 - 需捕获 requests 全部传输层异常
                last_exc = e
                if attempt < retries and self._is_transient_error(e):
                    backoff = _RETRY_BACKOFF * (2 ** attempt)
                    logger.log(log_level,
                               "[HTTP请求] %s %s 瞬时网络错误(第%d次)，%.2fs 后重试: %s",
                               method, url, attempt + 1, backoff, e)
                    time.sleep(backoff)
                    continue
                logger.log(log_level, "[HTTP请求] %s %s 发送异常: %s", method, url, e)
                raise
        try:
            resp_text = resp.text or ""
        except Exception:
            resp_text = ""
        if resp_text and len(resp_text) > 500:
            resp_text = resp_text[:500] + f"...(截断, 共 {len(resp_text)} 字节)"
        elapsed_ms = getattr(resp, "elapsed", None)
        elapsed_ms = elapsed_ms.total_seconds() * 1000 if elapsed_ms else 0
        logger.log(log_level, "[HTTP响应] %s %s -> 状态码=%s 耗时=%.0fms | 响应体=%s",
                   method, url, resp.status_code, elapsed_ms, resp_text)
        return resp

    def check_connection(self):
        """检查服务器连接状态。

        仅在连接状态（通/断）发生变化时记录日志，避免持续离线时主循环每 10 秒
        重复刷屏；恢复联网时记录「已恢复」便于运维确认。各类异常分别给出可读原因，
        非 requests 异常保留完整堆栈。

        采用连接/读取超时分设，并对瞬时网络错误做重试（见 _request），
        避免单次网络抖动被误判为「服务端连接失败」（#38）。
        """
        try:
            resp = self._request(
                "GET", f"{self.base_url}/health",
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
                headers=self._headers(), log_level=logging.DEBUG,
            )
            connected = resp.status_code == 200
            err = None
            is_request_err = False
        except (RequestsConnectionError, Timeout) as e:
            connected = False
            err = f"服务端不可达: {e}"
            is_request_err = True
        except requests.RequestException as e:
            connected = False
            err = f"健康检查请求异常: {e}"
            is_request_err = True
        except Exception as e:
            connected = False
            err = str(e)
            is_request_err = False

        # 仅在状态变化时记录，避免离线期间重复告警；首次检测记录初始状态
        last = getattr(self, "_last_connected", None)
        if connected != last:
            if last is None:
                if connected:
                    logger.info("服务端连接正常")
                elif is_request_err:
                    logger.warning("服务端连接失败: %s", err)
                else:
                    logger.warning("服务端连接失败（非请求类异常）: %s", err, exc_info=True)
            elif connected:
                logger.info("服务端连接已恢复")
            elif is_request_err:
                logger.warning("服务端连接失败: %s", err)
            else:
                logger.warning("服务端连接失败（非请求类异常）: %s", err, exc_info=True)
            self._last_connected = connected
        return connected

    def register_device(self, device_name=""):
        """向服务端注册本设备

        新设备注册时服务端返回 device_token，
        需持久化保存并在后续请求中携带。
        """
        url = f"{self.base_url}/api/v1/public/device/register"
        try:
            resp = self._request(
                "POST",
                url,
                json={"device_id": self.device_id, "device_name": device_name},
                timeout=self.timeout,
                headers=self._headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                # 新设备注册时服务端返回 device_token，需保存
                token = data.get("device_token")
                if token:
                    self.device_token = token
                    _save_device_token(token)
                    logger.info("设备注册成功，device_token 已保存")
                else:
                    logger.info("设备心跳上报成功")
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
            resp = self._request(
                "POST",
                url,
                json={"device_id": self.device_id},
                timeout=3,
                headers=self._headers(),
            )
            if resp.status_code == 200:
                logger.info("设备下线通知成功")
                # 服务端可能在设备本地令牌缺失时重新签发令牌，需持久化，
                # 使后续需鉴权的请求恢复正常（修复设备下线通知 HTTP 403 问题）
                try:
                    payload = resp.json()
                    reissued = payload.get("device_token") if isinstance(payload, dict) else None
                    if reissued:
                        _save_device_token(reissued)
                        logger.info("已持久化服务端重新签发的设备令牌")
                except Exception:
                    pass
                return True
            logger.warning(f"设备下线通知失败，状态码: {resp.status_code}")
            return False
        except Exception as e:
            logger.warning(f"设备下线通知异常: {e}")
            return False

    @staticmethod
    def _fallback_schedules(reason):
        """网络路径失败时回退本地缓存。

        :return: 本地缓存的计划列表；无缓存时返回 None，表示"本次拉取结果未知"，
                 由 MedicationPoller 保留上一轮内存缓存，避免误清空导致漏提醒
        """
        cached = load_schedules()
        if cached:
            logger.info(f"网络不可用（{reason}），回退本地用药计划缓存 {len(cached)} 条")
            return cached
        logger.warning(f"网络不可用（{reason}）且无本地缓存，保留内存中的既有计划")
        return None

    def get_medication_schedule(self):
        """
        拉取本设备的用药计划（由 MedicationPoller 定时调用）
        GET /api/v1/public/device/schedule/{device_id}
        返回 schedules 列表，每项包含 plan_id, drug_name, dosage, product_code, time, frequency

        有网优先走网络：请求成功后写入本地缓存；请求失败/异常时回退读取本地缓存，
        保证断网期间提醒与扫码查询不中断。
        :return: 计划列表；网络失败且无本地缓存时返回 None（表示结果未知）
        """
        url = f"{self.base_url}/api/v1/public/device/schedule/{self.device_id}"
        try:
            resp = self._request("GET", url, timeout=self.timeout, headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                # 校验响应类型，避免非 dict 响应调用 .get 崩溃
                if isinstance(data, dict):
                    schedules = data.get('schedules', []) or []
                elif isinstance(data, list):
                    schedules = data
                else:
                    logger.warning(f"用药计划响应格式异常: {type(data)}")
                    return self._fallback_schedules("响应格式异常")
                # 校验 schedules 内部结构：必须是列表且每项均为 dict，避免下游
                # s.get(...) 在收到 {"schedules": "invalid"} 或对象时异常
                if not isinstance(schedules, list) or not all(
                    isinstance(item, dict) for item in schedules
                ):
                    logger.warning("用药计划 schedules 字段格式异常")
                    return self._fallback_schedules("schedules 字段格式异常")
                # 网络拉取成功（含服务端返回空列表）即刷新本地缓存
                save_schedules(schedules)
                return schedules
            logger.warning(f"拉取用药计划失败，状态码: {resp.status_code}")
            return self._fallback_schedules(f"HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"拉取用药计划异常: {e}")
            return self._fallback_schedules(str(e))

    def confirm_medication(self, drug_name, dosage, taken_at=None, items=None):
        """
        上报服药确认（可选）
        POST /api/v1/public/device/message
        message_type=medication
        items: 可选，列表，每项含 plan_id/drug_name/dosage/scheduled_time(HH:MM)，用于服务端精确落库
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
                "items": items or [],
            },
        }
        try:
            resp = self._request("POST", url, json=data, timeout=self.timeout, headers=self._headers())
            if resp.status_code == 200:
                return True
            logger.warning(f"上报服药确认失败，状态码: {resp.status_code}")
            return False
        except Exception as e:
            logger.warning(f"上报服药确认异常: {e}")
            return False

    def upload_image(self, image_path, endpoint=None, plan_id=None, scheduled_time=None, elderly_id=None):
        # 图片以 base64 编码放入 JSON 上传（避免 multipart 在大文件/代理下不稳定）
        if endpoint is None:
            endpoint = self.config.get('upload_endpoint', '/api/v1/public/device/upload')
        import base64
        try:
            with open(image_path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            logger.warning(f"读取图片失败: {e}")
            return False
        url = f"{self.base_url}{endpoint}"
        payload = {
            "device_id": self.device_id,
            "image_base64": f"data:image/jpeg;base64,{b64}",
            "plan_id": plan_id,
            "scheduled_time": scheduled_time,
            # 多老人：照片归属的老人 ID（由拍照前身份识别确定），缺省回退设备主体
            "elderly_id": elderly_id,
        }
        try:
            resp = self._request(
                "POST",
                url,
                json=payload,
                timeout=self.timeout,
                headers=self._headers(),
            )
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
            resp = self._request(
                "POST",
                url,
                json={"device_id": self.device_id, "message_type": "emergency", "content": "紧急求助"},
                timeout=self.timeout,
                headers=self._headers(),
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
            resp = self._request("POST", url, json=data, timeout=self.timeout, headers=self._headers())
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"发送聊天消息失败，状态码: {resp.status_code}")
            return None
        except Exception as e:
            logger.warning(f"发送聊天消息异常: {e}")
            return None

    def upload_medicine_photo(self, image_path, plan_id=None, scheduled_time=None):
        """上传药品照片"""
        return self.upload_image(image_path, plan_id=plan_id, scheduled_time=scheduled_time)

    def ask_ai(self, question):
        """向服务端 AI 提问"""
        url = f"{self.base_url}/api/v1/public/ai/ask"
        data = {"question": question, "device_id": self.device_id}
        try:
            resp = self._request("POST", url, json=data, timeout=self.timeout, headers=self._headers())
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
