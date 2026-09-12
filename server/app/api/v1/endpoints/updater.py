#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新端点（访问即触发更新检查与安装）。

挂载位置：main.py 中以 prefix=api_prefix 注册，完整路径为
    /eating-medication/server/api/v1/updater

- GET  /updater : 只读检查更新（不下载、不安装、不重启服务）。
- POST /updater : 触发一次更新检查与安装，必须携带 X-Update-Token 头
  （令牌配置于项目根目录 .env 的 UPDATE_TOKEN）；未配置令牌时拒绝触发，
  避免公网无鉴权端点被利用为重启循环 / 磁盘消耗 DoS。

底层更新逻辑复用仓库根目录的 updater.py（安全自动更新 / SHA256 校验 / 保护文件）。
"""
import asyncio
import logging
import secrets

from fastapi import APIRouter, Header, HTTPException

# 复用根目录统一迁移的 updater.py（与 server/main.py / family_monitor/main.py 一致）
from updater import check_for_update, _load_update_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/updater")
async def updater_status():
    """只读查询更新状态（不触发下载与安装，可安全公开）。

    仅检查远端是否存在新版本并返回版本信息，不下载发布包、不重启服务。

    :return: 更新信息字典（含 current_version / latest_version / update_available 等）
    """
    # 只读检查：auto_pull=False 仅提示、不下载不安装
    return await asyncio.to_thread(check_for_update, auto_pull=False)


@router.post("/updater")
async def updater_trigger(
    x_update_token: str = Header(default="", alias="X-Update-Token"),
):
    """触发一次更新检查与安装（需 X-Update-Token 鉴权）。

    仅当请求头 X-Update-Token 与根目录 .env 的 UPDATE_TOKEN 一致时才执行；
    未配置 UPDATE_TOKEN 时拒绝触发（防止公网无鉴权触发更新造成
    重启循环 / 全量备份磁盘消耗 / GitHub API 配额耗尽等 DoS 风险）。

    :return: 更新信息字典（含 current_version / latest_version / update_available 等）
    """
    expected = _load_update_token()
    if not expected:
        raise HTTPException(
            status_code=403,
            detail="远程触发更新未启用：请在项目根目录 .env 配置 UPDATE_TOKEN 后重试",
        )
    if not secrets.compare_digest(expected.encode(), x_update_token.encode()):
        raise HTTPException(status_code=403, detail="X-Update-Token 无效")
    return await asyncio.to_thread(check_for_update, auto_pull=True)
