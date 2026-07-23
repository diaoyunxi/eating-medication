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

        # 仅在 DEBUG 模式下记录请求体，且敏感路径不记录
        if settings.DEBUG and request.method in ["POST", "PUT", "PATCH"]:
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
                # 对于文本请求，尝试读取和解析
                try:
                    body_bytes = await request.body()
                    if body_bytes:
                        request_body = body_bytes.decode("utf-8", errors="replace")
                        request_body = _redact_body(request_body)
                        logger.info(f"📦 请求体:\n{request_body}")
                except Exception as e:
                    logger.debug(f"读取请求体失败: {e}")

        # 处理请求
        response = await call_next(request)

        process_time = time.time() - start_time

        # 记录响应
        status_emoji = "✅" if 200 <= response.status_code < 300 else "⚠️" if 400 <= response.status_code < 500 else "❌"
        logger.info(
            f"{status_emoji} 响应完成 - {request.method} {request.url.path} "
            f"status={response.status_code} "
            f"duration={process_time:.3f}s"
        )

        response.headers["X-Process-Time"] = str(process_time)
        return response
