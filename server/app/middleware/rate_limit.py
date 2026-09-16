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

# 可信代理 IP 集合：仅当直连 IP 在此集合内时，才信任 X-Forwarded-For 等代理头。
# 默认仅信任本地回环地址（适用于应用与反代同机部署的场景）。
# 生产环境若经 Cloudflare 隧道或外部反代，应将代理 IP / 网段加入此集合，
# 或通过环境变量 TRUSTED_PROXIES 配置（逗号分隔）。
_TRUSTED_PROXIES: set[str] = {"127.0.0.1", "::1", "localhost"}


def _init_trusted_proxies():
    """从 settings 读取 TRUSTED_PROXIES 环境变量并合并到默认集合。"""
    raw = getattr(settings, "TRUSTED_PROXIES", "") or ""
    for entry in raw.split(","):
        entry = entry.strip()
        if entry:
            _TRUSTED_PROXIES.add(entry)


_init_trusted_proxies()

# 客户端 IP -> 路径 -> deque[时间戳]
_store = defaultdict(lambda: defaultdict(deque))


def _client_ip(request) -> str:
    """获取客户端真实 IP，仅当直连来源为可信代理时才信任代理头。

    安全模型：
    - 直连 IP 在 _TRUSTED_PROXIES 中 → 依次尝试 CF-Connecting-IP、X-Forwarded-For
    - 直连 IP 不在可信列表 → 直接使用 request.client.host（忽略所有代理头）

    此设计防止攻击者在未经反代的情况下伪造 XFF 头绕过限流。
    """
    direct_ip = request.client.host if request.client else "unknown"

    if direct_ip not in _TRUSTED_PROXIES:
        return direct_ip

    # 可信代理：优先 Cloudflare CF-Connecting-IP
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()

    # 回退 X-Forwarded-For（取最左侧，即原始客户端 IP）
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()

    return direct_ip


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
