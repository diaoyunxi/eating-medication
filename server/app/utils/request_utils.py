# -*- coding: utf-8 -*-
"""请求工具函数"""
from fastapi import Request


def get_client_ip(request: Request) -> str:
    """获取真实客户端 IP（安全修复中危5）

    反向代理（Cloudflare 隧道）部署时，request.client.host 是代理 IP，
    需从 X-Forwarded-For 或 CF-Connecting-IP 头获取真实客户端 IP。

    :param request: FastAPI 请求对象
    :return: 真实客户端 IP 字符串
    """
    # 优先 Cloudflare CF-Connecting-IP（最可靠）
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    # 回退 X-Forwarded-For（取第一个 IP）
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    # 最终回退 request.client.host
    return request.client.host if request.client else "unknown"
