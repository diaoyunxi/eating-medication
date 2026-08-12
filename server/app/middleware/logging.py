# -*- coding: utf-8 -*-
import time
import logging
import json
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings

# 使用独立的 logger 而不是 uvicorn.access
logger = logging.getLogger("app.access")

# 敏感路径——这些路径不记录请求体
SENSITIVE_PATHS = {"/auth/login", "/auth/register", "/device/register"}

# 请求体中需要脱敏的字段名（子串匹配，不区分大小写）
SENSITIVE_FIELDS = ("password", "token", "secret_key", "api_key", "authorization")


def _redact_body(body: str) -> str:
    """对请求体中的敏感字段值脱敏"""
    try:
        parsed = json.loads(body)
    except Exception:
        return body
    if isinstance(parsed, dict):
        changed = False
        for key in list(parsed.keys()):
            if any(s in key.lower() for s in SENSITIVE_FIELDS):
                parsed[key] = "***REDACTED***"
                changed = True
        if changed:
            return json.dumps(parsed, ensure_ascii=False, indent=2)
    return body


class LoggingMiddleware(BaseHTTPMiddleware):
    """详细记录每个请求的信息（敏感信息脱敏，仅 DEBUG 模式记录请求体）"""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # 获取客户端信息
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        # 记录请求开始
        logger.info(
            f"📥 新请求 - {request.method} {request.url.path} "
            f"来自: {client_ip} - UA: {user_agent}"
        )

        # 仅在 DEBUG 模式下记录请求体；但绝不能直接 ``await request.body()`` 后原样
        # ``call_next(request)`` —— 那样会消费请求体流。在多层 BaseHTTPMiddleware
        # （含 fb35676 新增的 path_prefix_middleware 函数式中间件）叠加时，下游路由用
        # Pydantic 解析 ``req: XxxIn`` 会拿到空 body，导致所有 POST 请求返回 400，
        # 且 body 流被提前耗尽后下游会卡在等待，表现为 10s+ 超时（生产环境 DEBUG=true
        # 时尤为明显，GET 无 body 故正常）。
        # 正确做法：读取一次后将 body 通过「重放 receive」重建 Request 再下发，
        # 既保留 DEBUG 请求体日志，又不破坏下游对 body 的解析。
        if settings.DEBUG and request.method in ("POST", "PUT", "PATCH"):
            content_type = request.headers.get("content-type", "")
            # 剥离 API 前缀以匹配敏感路径
            normalized_path = request.url.path
            prefix = settings.API_V1_PREFIX
            if prefix and normalized_path.startswith(prefix):
                normalized_path = normalized_path[len(prefix):]
            # 对于文件上传(multipart/form-data)，只记录元信息，不尝试解码二进制数据
            if "multipart/form-data" in content_type or "application/octet-stream" in content_type:
                logger.info("📦 文件上传请求，不记录二进制内容")
            elif normalized_path in SENSITIVE_PATHS:
                logger.info("🔒 敏感路径，不记录请求体")
            else:
                # 对于文本请求，尝试读取和解析（读取后即重放，避免消费流）
                try:
                    body_bytes = await request.body()
                    if body_bytes:
                        request_body = body_bytes.decode("utf-8", errors="replace")
                        request_body = _redact_body(request_body)
                        logger.info(f"📦 请求体:\n{request_body}")
                    # 关键修复：用已读取的 body 重建 receive 并重放给下游路由，
                    # 否则下游 Pydantic 解析会读到空 body（返回 400）甚至卡死。
                    captured = body_bytes

                    async def _replay_receive():
                        return {
                            "type": "http.request",
                            "body": captured,
                            "more_body": False,
                        }

                    request = Request(request.scope, receive=_replay_receive)
                except Exception as e:
                    logger.debug(f"读取请求体失败: {e}")

        # 处理请求
        response = await call_next(request)

        process_time = time.time() - start_time

        # 按状态码分级记录响应：4xx/5xx 为 ERROR，3xx 为 WARNING，2xx 为 INFO
        # 便于在生产日志中快速定位客户端错误（如 404/405/401）与服务端异常
        sc = response.status_code
        if sc >= 500:
            level = logging.ERROR
            status_emoji = "❌"
        elif sc >= 400:
            level = logging.ERROR
            status_emoji = "⚠️"
        elif sc >= 300:
            level = logging.WARNING
            status_emoji = "↪️"
        else:
            level = logging.INFO
            status_emoji = "✅"
        logger.log(
            level,
            f"{status_emoji} 响应完成 - {request.method} {request.url.path} "
            f"status={response.status_code} "
            f"duration={process_time:.3f}s"
        )

        # 注：不再向客户端暴露 X-Process-Time（BUG-M07，避免泄露服务器处理耗时）
        return response
