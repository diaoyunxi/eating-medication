# -*- coding: utf-8 -*-
"""请求工具函数（含可信代理校验，防伪造代理头绕过限流）"""
import ipaddress
import logging
from functools import lru_cache
from typing import List, Optional

from fastapi import Request

logger = logging.getLogger(__name__)

# Cloudflare 官方回源 IP 段（IPv4/IPv6，2026-09 权威列表）。
# 官方实时列表：https://www.cloudflare.com/ips-v4 与 https://www.cloudflare.com/ips-v6
_CLOUDFLARE_IPV4_NETS = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
]
_CLOUDFLARE_IPV6_NETS = [
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32",
    "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32",
]


def _parse_trusted_proxies(raw: str) -> List[ipaddress._BaseNetwork]:
    """解析 TRUSTED_PROXIES 配置为网段列表。

    支持逗号分隔的 IP / CIDR，以及关键字 ``cloudflare``（内置官方回源段）。
    解析失败的项目跳过并告警，不阻断启动。
    """
    nets: List[ipaddress._BaseNetwork] = []
    if not raw:
        return nets
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        if item.lower() == "cloudflare":
            nets += [ipaddress.ip_network(n) for n in (_CLOUDFLARE_IPV4_NETS + _CLOUDFLARE_IPV6_NETS)]
            continue
        try:
            if "/" in item:
                nets.append(ipaddress.ip_network(item, strict=False))
            else:
                # 单 IP 视为 /32 或 /128
                addr = ipaddress.ip_address(item)
                nets.append(ipaddress.ip_network(f"{addr}/{addr.max_prefixlen}"))
        except ValueError:
            logger.warning(f"忽略无效的 TRUSTED_PROXIES 项: {item}")
    return nets


def _is_trusted_proxy(remote_ip: Optional[str], nets: List[ipaddress._BaseNetwork]) -> bool:
    """判断直连 IP 是否命中可信代理白名单。"""
    if not remote_ip or not nets:
        return False
    try:
        addr = ipaddress.ip_address(remote_ip.split("%")[0])
    except ValueError:
        return False
    return any(addr in net for net in nets)


@lru_cache(maxsize=1)
def _trusted_networks() -> List[ipaddress._BaseNetwork]:
    """读取 settings.TRUSTED_PROXIES 并解析为网段列表（进程内缓存）。

    配置变更需重启生效；lru_cache 避免每个请求重复解析。
    """
    from app.core.config import settings
    return _parse_trusted_proxies(settings.TRUSTED_PROXIES)


def get_client_ip(request: Request) -> str:
    """获取真实客户端 IP（仅信任已配置的可信反向代理头）。

    安全模型（修复 P3-1：伪造 X-Forwarded-For / CF-Connecting-IP 绕过限流）：
    - 默认（未配置 TRUSTED_PROXIES）：完全不信任代理头，一律返回直连 IP；
      此时若部署在 Cloudflare 后，所有用户共享回源出口 IP，限流按出口 IP
      聚合（偏严但安全）。建议在 .env 配置 TRUSTED_PROXIES=cloudflare 或
      显式回源 CIDR 以获得精确限流与审计 IP。
    - 已配置且直连 IP 命中白名单：优先取 CF-Connecting-IP，其次取
      X-Forwarded-For 首项（仅取第一个，避免被攻击者拼接伪造）。
    - 直连 IP 不命中白名单：仍返回直连 IP，忽略一切代理头。

    :param request: FastAPI 请求对象
    :return: 真实客户端 IP 字符串
    """
    remote_ip = request.client.host if request.client else None
    nets = _trusted_networks()
    if not _is_trusted_proxy(remote_ip, nets):
        return remote_ip or "unknown"

    # 直连来源为可信代理：取真实客户端 IP
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        # 取 XFF 首项（最左为原始客户端），后续项可被伪造拼接
        return xff.split(",")[0].strip()
    return remote_ip
