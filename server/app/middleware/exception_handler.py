# -*- coding: utf-8 -*-
import json
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging
from app.core.exceptions import BusinessError

logger = logging.getLogger(__name__)

# M18：需要脱敏的请求体字段（子串匹配，不区分大小写）
_SENSITIVE_FIELDS = ("password", "token", "authorization")


def _redact_request_body(body_bytes: bytes) -> str:
    """M18：脱敏请求体中的敏感字段后返回可读文本"""
    if not body_bytes:
        return ""
    body_text = body_bytes.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(body_text)
        if isinstance(parsed, dict):
            for key in list(parsed.keys()):
                if any(s in key.lower() for s in _SENSITIVE_FIELDS):
                    parsed[key] = "***REDACTED***"
            body_text = json.dumps(parsed, ensure_ascii=False)
    except Exception:
        pass
    return body_text


def add_exception_handlers(app: FastAPI):
    """注册全局异常处理器"""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """处理 FastAPI/Starlette 原生 HTTPException"""
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(BusinessError)
    async def business_exception_handler(request: Request, exc: BusinessError):
        """处理自定义业务异常"""
        logger.warning(f"业务异常: {exc.message} (code={exc.code})")
        return JSONResponse(
            status_code=exc.code,
            content={"detail": exc.message},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """处理所有未捕获的异常"""
        # M18：脱敏请求体中的敏感字段后再记录
        try:
            body_bytes = await request.body()
        except Exception:
            body_bytes = b""
        body_text = _redact_request_body(body_bytes)
        logger.exception(f"未捕获的异常: {exc} | 请求体: {body_text}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "服务器内部错误，请稍后重试"},
        )
