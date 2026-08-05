# -*- coding: utf-8 -*-
"""
消息路由
增加 /chat/history BFF 代理接口，从服务端获取聊天历史
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from core import config, elderly_client
from routes.web_helpers import templates, require_login, login_redirect, unauthorized_json

router = APIRouter()





@router.get("/chat")
async def chat(request: Request):
    """消息页面
    传入 current_user 和 elderly_id 供模板使用"""
    if not require_login(request):
        return login_redirect()
    user = getattr(request.state, 'user', None) or ''
    user_id = getattr(request.state, 'user_id', None)
    elderly_id = ''
    # 从已绑定的设备获取 elderly_id
    if user:
        bound = elderly_client.get_bound_device()
        if bound:
            elderly_id = bound.get('device_id', '')

    # 从认证中间件获取当前登录用户的数字 ID，
    # 前端用于与服务端 sender_id 比较以判定消息方向。
    # 原代码硬编码 current_user_id = None，导致所有消息方向显示错误。
    current_user_id = user_id

    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "current_user": user,
            "current_user_id": current_user_id,
            "elderly_id": elderly_id,
            "server_url": config.ELDERLY_SERVER_URL,
            "prefix": config.PATH_PREFIX,
        }
    )


@router.get("/chat/history")
async def chat_history(request: Request, limit: int = 50):
    """BFF 代理聊天历史接口"""
    if not require_login(request):
        return unauthorized_json()
    # 边界校验：限制 1~200，防止过大查询拖慢服务
    limit = max(1, min(limit, 200))
    messages = await elderly_client.get_chat_history(limit=limit)
    return JSONResponse(content={"success": True, "messages": messages})
