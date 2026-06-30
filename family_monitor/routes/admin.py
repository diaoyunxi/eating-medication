# -*- coding: utf-8 -*-
"""
管理员路由 - 仅admin用户可访问
"""

import os
import json
import logging
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from core import config
from core.auth import get_user_manager
from core.session import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


@router.get("/administrator/setting")
async def admin_settings(request: Request):
    """管理员设置页面"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        return RedirectResponse(url="/login", status_code=302)

    session_manager = get_session_manager(config.SECRET_KEY)
    session_data = session_manager.verify_session(session_token)
    if not session_data:
        return RedirectResponse(url="/login", status_code=302)

    username = session_data.get("username")
    user_manager = get_user_manager(config.DATA_DIR)
    if not user_manager.is_admin(username):
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        request,
        "admin_settings.html",
        {
            "app_name": config.APP_NAME,
            "username": username,
            "elderly_server_url": config.ELDERLY_SERVER_URL,
            "server_host": config.SERVER_HOST,
            "server_port": config.SERVER_PORT,
            "debug_mode": config.DEBUG,
            "secret_key": config.SECRET_KEY,
            "ssl_certfile": config.SSL_CERTFILE,
            "ssl_keyfile": config.SSL_KEYFILE,
            "ssl_ca_bundle": config.SSL_CA_BUNDLE,
        }
    )


@router.post("/administrator/setting/server")
async def update_server_config(
    request: Request,
    elderly_server_url: str = Form(""),
    server_host: str = Form("0.0.0.0"),
    server_port: int = Form(4430),
):
    """更新服务端连接配置"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        return JSONResponse({"success": False, "message": "未登录"}, status_code=401)

    session_manager = get_session_manager(config.SECRET_KEY)
    session_data = session_manager.verify_session(session_token)
    if not session_data:
        return JSONResponse({"success": False, "message": "会话过期"}, status_code=401)

    username = session_data.get("username")
    user_manager = get_user_manager(config.DATA_DIR)
    if not user_manager.is_admin(username):
        return JSONResponse({"success": False, "message": "无权限"}, status_code=403)

    config.ELDERLY_SERVER_URL = elderly_server_url
    config.SERVER_HOST = server_host
    config.SERVER_PORT = server_port
    config.save_config()

    logger.info(f"管理员 {username} 更新了服务端配置")
    return JSONResponse({"success": True, "message": "服务端配置已保存"})


@router.post("/administrator/setting/security")
async def update_security_config(
    request: Request,
    secret_key: str = Form(""),
    ssl_certfile: str = Form(""),
    ssl_keyfile: str = Form(""),
    ssl_ca_bundle: str = Form(""),
):
    """更新安全配置"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        return JSONResponse({"success": False, "message": "未登录"}, status_code=401)

    session_manager = get_session_manager(config.SECRET_KEY)
    session_data = session_manager.verify_session(session_token)
    if not session_data:
        return JSONResponse({"success": False, "message": "会话过期"}, status_code=401)

    username = session_data.get("username")
    user_manager = get_user_manager(config.DATA_DIR)
    if not user_manager.is_admin(username):
        return JSONResponse({"success": False, "message": "无权限"}, status_code=403)

    config.SECRET_KEY = secret_key
    config.SSL_CERTFILE = ssl_certfile
    config.SSL_KEYFILE = ssl_keyfile
    config.SSL_CA_BUNDLE = ssl_ca_bundle
    config.save_config()

    logger.info(f"管理员 {username} 更新了安全配置")
    return JSONResponse({"success": True, "message": "安全配置已保存"})


@router.post("/administrator/setting/advanced")
async def update_advanced_config(
    request: Request,
    debug_mode: bool = Form(False),
):
    """更新高级配置"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        return JSONResponse({"success": False, "message": "未登录"}, status_code=401)

    session_manager = get_session_manager(config.SECRET_KEY)
    session_data = session_manager.verify_session(session_token)
    if not session_data:
        return JSONResponse({"success": False, "message": "会话过期"}, status_code=401)

    username = session_data.get("username")
    user_manager = get_user_manager(config.DATA_DIR)
    if not user_manager.is_admin(username):
        return JSONResponse({"success": False, "message": "无权限"}, status_code=403)

    config.DEBUG = debug_mode
    config.save_config()

    logger.info(f"管理员 {username} 更新了高级配置")
    return JSONResponse({"success": True, "message": "高级配置已保存"})


admin_router = router
