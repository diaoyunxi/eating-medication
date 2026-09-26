#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新端点（访问即触发更新检查与安装，无需鉴权）。

挂载位置：main.py 中以 prefix=api_prefix 注册，完整路径为
    /eating-medication/server/api/v1/updater

- GET  /updater : 直接触发一次更新检查与安装（与 POST 行为一致）。
- POST /updater : 触发一次更新检查与安装。

两个方法行为完全相同：若远端存在更新版本且根目录 .env 的 AUTO_PULL=true，
则下载完整发布包、做 SHA256 校验并安全复制到项目根目录
（保留 .env / data / logs 等保护文件），更新成功后自动重启服务。

无需鉴权：便于 CI / 部署脚本 / 浏览器直接访问触发自更新。

底层更新逻辑复用仓库根目录的 updater.py（安全自动更新 / SHA256 校验 / 保护文件）。
"""
import asyncio
import logging

from fastapi import APIRouter

# 复用根目录统一迁移的 updater.py（与 server/main.py / family_monitor/main.py 一致）
from updater import check_for_update

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/updater")
async def updater_status():
    """访问即触发更新检查与安装（无需鉴权）。

    若远端存在更新版本且根目录 .env 的 AUTO_PULL=true，则下载完整发布包、
    做 SHA256 校验并安全复制到项目根目录（保留 .env / data / logs 等保护文件）。
    更新成功后自动重启相关 systemd 服务。

    :return: 更新信息字典（含 current_version / latest_version / update_available 等）
    """
    # check_for_update 含网络 IO 与文件复制，置于线程池避免阻塞事件循环
    return await asyncio.to_thread(check_for_update)


@router.post("/updater")
async def updater_trigger():
    """触发一次更新检查与安装（无需鉴权）。

    行为与 GET /updater 完全一致，提供 POST 方法以便 CI 脚本区分语义。

    :return: 更新信息字典（含 current_version / latest_version / update_available 等）
    """
    # check_for_update 含网络 IO 与文件复制，置于线程池避免阻塞事件循环
    return await asyncio.to_thread(check_for_update)
