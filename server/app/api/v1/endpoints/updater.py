#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新端点（可选 API Key 认证）。

挂载位置：main.py 中以 prefix=api_prefix 注册，完整路径为
    /eating-medication/server/api/v1/updater

- GET  /updater : 直接触发一次更新检查与安装（与 POST 行为一致）。
- POST /updater : 触发一次更新检查与安装。

认证机制：
- 若 server/.env 配置了 UPDATER_API_KEY，则请求须携带匹配的密钥
  （通过 X-Updater-Key 请求头或 ?key= 查询参数传递），否则返回 403。
- 若未配置 UPDATER_API_KEY，则允许无认证访问（向后兼容），
  但会在启动时打印警告日志提醒配置。

底层更新逻辑复用仓库根目录的 updater.py（安全自动更新 / SHA256 校验 / 保护文件）。
"""
import asyncio
import hmac
import logging
import os

from fastapi import APIRouter, Header, Query, HTTPException, status

# 复用根目录统一迁移的 updater.py（与 server/main.py / family_monitor/main.py 一致）
from updater import check_for_update

logger = logging.getLogger(__name__)

router = APIRouter()

# 从环境变量读取 API Key（首次导入时加载，避免反复读盘）
_UPDATER_API_KEY: str = os.environ.get("UPDATER_API_KEY", "").strip()

if not _UPDATER_API_KEY:
    logger.warning(
        "UPDATER_API_KEY 未配置：更新端点 (/updater) 允许无认证访问。"
        "生产环境建议在 server/.env 中设置 UPDATER_API_KEY 以防止未授权触发更新。"
    )


def _verify_updater_key(provided_key: str | None) -> None:
    """校验更新端点 API Key。

    未配置密钥时放行（向后兼容）；已配置时使用 hmac.compare_digest 做
    时间恒定比较，防止时序攻击。
    """
    if not _UPDATER_API_KEY:
        return  # 未配置密钥，允许无认证访问

    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="更新端点需要 API Key 认证（通过 X-Updater-Key 请求头或 ?key= 查询参数传递）",
        )

    if not hmac.compare_digest(provided_key, _UPDATER_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API Key 无效",
        )


@router.get("/updater")
async def updater_status(
    x_updater_key: str | None = Header(None, alias="X-Updater-Key"),
    key: str | None = Query(None, alias="key"),
):
    """触发更新检查与安装（需 API Key 认证，若已配置）。

    若远端存在更新版本且根目录 .env 的 AUTO_PULL=true，则下载完整发布包、
    做 SHA256 校验并安全复制到项目根目录（保留 .env / data / logs 等保护文件）。
    更新成功后自动重启相关 systemd 服务。

    :return: 更新信息字典（含 current_version / latest_version / update_available 等）
    """
    _verify_updater_key(x_updater_key or key)
    # check_for_update 含网络 IO 与文件复制，置于线程池避免阻塞事件循环
    return await asyncio.to_thread(check_for_update)


@router.post("/updater")
async def updater_trigger(
    x_updater_key: str | None = Header(None, alias="X-Updater-Key"),
    key: str | None = Query(None, alias="key"),
):
    """触发一次更新检查与安装（需 API Key 认证，若已配置）。

    行为与 GET /updater 完全一致，提供 POST 方法以便 CI 脚本区分语义。

    :return: 更新信息字典（含 current_version / latest_version / update_available 等）
    """
    _verify_updater_key(x_updater_key or key)
    # check_for_update 含网络 IO 与文件复制，置于线程池避免阻塞事件循环
    return await asyncio.to_thread(check_for_update)
