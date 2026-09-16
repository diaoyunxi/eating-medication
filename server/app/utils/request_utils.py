# -*- coding: utf-8 -*-
"""请求工具函数"""
from fastapi import Request

# 可信代理 IP 集合：仅当直连 IP 在此集合内时才信任代理头。
# 与 rate_limit.py 保持一致的安全模型。
_TRUSTED_PROXIES: set[str] = {"127.0.0.1", "::1", "localhost"}


def _init_trusted_proxies():
    """从 settings 读取 TRUSTED_PROXIES 环境变量并合并到默认集合。"""
    try:
        from app.core.config import settings
        raw = getattr(settings, "TRUSTED_PROXIES", "") or ""
        for entry in raw.split(","):
            entry = entry.strip()
            if entry:
                _TRUSTED_PROXIES.add(entry)
    except Exception:  # noqa: BLE001
        pass


_init_trusted_proxies()


def get_client_ip(request: Request) -> str:
    """获取真实客户端 IP（防 XFF 欺骗）

    安全模型：
    - 直连 IP 在 _TRUSTED_PROXIES 中 → 依次尝试 CF-Connecting-IP、X-Forwarded-For
    - 直连 IP 不在可信列表 → 直接使用 request.client.host（忽略所有代理头）

    反向代理（Cloudflare 隧道）部署时，需将代理 IP 加入 TRUSTED_PROXIES 环境变量。

    :param request: FastAPI 请求对象
    :return: 真实客户端 IP 字符串
    """
    direct_ip = request.client.host if request.client else "unknown"

    if direct_ip not in _TRUSTED_PROXIES:
        return direct_ip

    # 可信代理：优先 Cloudflare CF-Connecting-IP（最可靠）
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    # 回退 X-Forwarded-For（取第一个 IP）
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    # 最终回退 request.client.host
    return direct_ip
