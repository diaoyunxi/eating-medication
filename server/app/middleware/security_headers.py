# -*- coding: utf-8 -*-
"""安全响应头中间件（BUG-M01 / BUG-L01 / BUG-L02）。

- 补充 Content-Security-Policy 等安全响应头（M01）。
- 移除已废弃/不推荐的响应头（L01: X-XSS-Protection、L02: Expect-CT）。
  注：这两类头若由边缘层（Cloudflare）附加，应用层无法移除，需在边缘配置关闭；
  此处仅对应用层可能写入的同名响应头做清理。
"""
from starlette.middleware.base import BaseHTTPMiddleware

# 本服务为纯 JSON API，禁止页面内嵌与混合内容，收敛来源
CSP_POLICY = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "connect-src 'self'"
)

# 已废弃/不推荐的安全头，若响应上存在则移除
_DEPRECATED_HEADERS = ("x-xss-protection", "expect-ct")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        for h in _DEPRECATED_HEADERS:
            # MutableHeaders 没有 pop 方法，用 __delitem__ + 容错替代
            try:
                del response.headers[h]
            except KeyError:
                pass
        return response
