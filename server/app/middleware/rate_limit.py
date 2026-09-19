# -*- coding: utf-8 -*-
"""基于客户端 IP 的简易速率限制中间件（BUG-H02 / BUG-H03）。

对登录、注册、TOTP 校验、验证码、OAuth 授权、公开 AI 聊天等敏感路径做
固定窗口限流，缓解暴力破解与刷接口。

说明：内存限流仅在单进程内有效；多 worker / 多实例部署时各进程独立计数，
仅提供单机防护。生产环境应改用 Redis 等共享存储做集中限流。
"""
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings

# 限流规则：剥离 API 前缀后的路径 -> (最大次数, 窗口秒数)
RATE_LIMIT_RULES = {
    "/auth/login": (10, 60),
    "/auth/register": (5, 60),
    "/auth/totp/verify": (5, 60),
    "/auth/email/send-code": (5, 60),
    "/auth/bind-phone": (5, 60),
    "/auth/oauth/github/authorize": (10, 60),
    "/auth/oauth/gitee/authorize": (10, 60),
    "/ai/chat/public": (10, 60),
}

# 客户端 IP -> 路径 -> deque[时间戳]
_store = defaultdict(lambda: defaultdict(deque))


def _client_ip(request) -> str:
    """优先取 X-Forwarded-For（Cloudflare 隧道/反代场景），否则取直连 IP。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # 放行 CORS 预检（OPTIONS），避免影响跨域协商
        if request.method == "OPTIONS":
            return await call_next(request)
        prefix = settings.API_V1_PREFIX.rstrip("/")
        path = request.url.path
        if prefix and path.startswith(prefix):
            path = path[len(prefix):]
        rule = RATE_LIMIT_RULES.get(path)
        if rule:
            max_count, window = rule
            ip = _client_ip(request)
            now = time.time()
            dq = _store[ip][path]
            while dq and dq[0] <= now - window:
                dq.popleft()
            if len(dq) >= max_count:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后再试"},
                    headers={"Retry-After": str(window)},
                )
            dq.append(now)
        return await call_next(request)
