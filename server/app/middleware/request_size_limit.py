# -*- coding: utf-8 -*-
"""请求体大小限制中间件（BUG-M06：防止超大请求体导致资源耗尽/DoS）。

仅依据 Content-Length 预检；超出上限直接返回 413，避免进入业务层。
chunked 无 Content-Length 的请求无法在此预检，依赖上游（反向代理/边缘）限制。
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# 最大请求体：1MB（base64 图片等已足够；超出即拒绝）
MAX_CONTENT_LENGTH = 1 * 1024 * 1024

_BODY_METHODS = ("POST", "PUT", "PATCH", "DELETE")


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method in _BODY_METHODS:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > MAX_CONTENT_LENGTH:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "请求体过大"},
                )
        return await call_next(request)
