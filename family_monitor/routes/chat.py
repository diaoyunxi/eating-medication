# -*- coding: utf-8 -*-
"""
消息路由
"""

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from core import config

router = APIRouter()
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
# 禁用 Jinja2 缓存以避免网络驱动器上的缓存问题
templates.env.cache = {}
# 注入路径前缀变量，供模板链接加前缀
templates.env.globals["prefix"] = config.PATH_PREFIX


@router.get("/chat")
async def chat(request: Request):
    """消息页面"""
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "app_name": config.APP_NAME
        }
    )
