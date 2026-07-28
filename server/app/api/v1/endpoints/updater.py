#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新信息端点（供 family 前端轮询展示版本与更新状态，供 CI 部署后触发自更新）。

挂载位置：main.py 中以 prefix=api_prefix 注册，完整路径为
    /eating-medication/server/api/v1/updater

- GET  /updater : 返回当前/最新版本与更新状态（get_update_info），无副作用，
                  供 family_monitor 前端每 5 分钟轮询展示版本徽章。
- POST /updater : 触发一次更新检查（若启用自动更新(AUTO_PULL)则拉取并安装新版本），
                  供 CI 在发布后调用（curl -fsS -X POST .../api/v1/updater）触发自更新。

底层更新逻辑复用仓库根目录的 updater.py（安全自动更新 / SHA256 校验 / 保护文件）。
"""
import asyncio
import logging

from fastapi import APIRouter

# 复用根目录统一迁移的 updater.py（与 server/main.py / family_monitor/main.py 一致）
from updater import get_update_info, check_for_update

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/updater")
async def updater_status():
    """返回结构化更新信息，供 family 前端轮询展示版本与更新状态。

    无副作用：仅检查远端最新版本号并比对，不会下载或安装。
    """
    return get_update_info()


@router.post("/updater")
async def updater_trigger():
    """触发一次更新检查与安装。

    若远端存在更新版本且根目录 .env 的 AUTO_PULL=true，则下载完整发布包、
    做 SHA256 校验并安全复制到项目根目录（保留 .env / data / logs 等保护文件）。
    供 CI 在发布后调用，使正在运行的服务器自行拉取新版本。
    """
    # check_for_update 含网络 IO 与文件复制，置于线程池避免阻塞事件循环
    return await asyncio.to_thread(check_for_update)
