# -*- coding: utf-8 -*-
"""
管理员路由 - 仅admin用户可访问
注意：SECRET_KEY 仅通过 .env 配置，不提供 Web 修改入口
DEBUG 在生产环境（PRODUCTION=true）下禁止通过 Web 修改
"""

import logging
import secrets
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from core import config
from core.auth import get_user_manager
from core.session import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
# 注入路径前缀变量，供模板链接加前缀
templates.env.globals["prefix"] = config.PATH_PREFIX

# P0-4 修复：admin 路由内重定向显式拼接 PATH_PREFIX
_PREFIX = config.PATH_PREFIX
_LOGIN_URL = f"{_PREFIX}/login" if _PREFIX else "/login"
_HOME_URL = f"{_PREFIX}/" if _PREFIX else "/"


@router.get("/administrator/setting")
async def admin_settings(request: Request):
    """管理员设置页面"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        return RedirectResponse(url=_LOGIN_URL, status_code=302)

    session_manager = get_session_manager(config.SECRET_KEY)
    session_data = session_manager.verify_session(session_token)
    if not session_data:
        return RedirectResponse(url=_LOGIN_URL, status_code=302)

    username = session_data.get("username")
    user_manager = get_user_manager(config.DATA_DIR)
    if not user_manager.is_admin(username):
        return RedirectResponse(url=_HOME_URL, status_code=302)

    return templates.TemplateResponse(
        "admin_settings.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
            "username": username,
            "elderly_server_url": config.ELDERLY_SERVER_URL,
            "server_host": config.SERVER_HOST,
            "server_port": config.SERVER_PORT,
            "debug_mode": config.DEBUG,
            # SECRET_KEY 仅通过 .env 配置，不传入模板上下文
        }
    )


@router.post("/administrator/setting/server")
async def update_server_config(
    request: Request,
    elderly_server_url: str = Form(""),
    server_host: str = Form("0.0.0.0"),
    server_port: int = Form(4430),
    csrf_token: str = Form(...),
):
    """更新服务端连接配置"""
    # CSRF 校验（H-2 修复：常量时间比较）
    cookie_token = request.cookies.get("csrf_token", "")
    if not cookie_token or not secrets.compare_digest(csrf_token, cookie_token):
        return JSONResponse({"success": False, "message": "CSRF 校验失败"}, status_code=403)

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


@router.post("/administrator/setting/advanced")
async def update_advanced_config(
    request: Request,
    csrf_token: str = Form(...),
    debug_mode: str = Form(None),
):
    """更新高级配置
    注意：DEBUG 在生产环境（PRODUCTION=true）下禁止通过 Web 修改，仅通过 .env 配置。
    非生产环境下允许通过 Web 修改 DEBUG 配置。"""
    # CSRF 校验（H-2 修复：常量时间比较）
    cookie_token = request.cookies.get("csrf_token", "")
    if not cookie_token or not secrets.compare_digest(csrf_token, cookie_token):
        return JSONResponse({"success": False, "message": "CSRF 校验失败"}, status_code=403)

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

    # DEBUG 不可通过 Web 修改，生产环境强制 False
    if config.PRODUCTION:
        logger.warning(f"管理员 {username} 尝试在生产环境修改 DEBUG，已拒绝")
        return JSONResponse({"success": False, "message": "生产环境不允许修改调试模式"}, status_code=403)

    # 实际保存 DEBUG 配置（非生产环境允许通过 Web 修改）
    if debug_mode is not None:
        config.DEBUG = debug_mode.lower() == "true"
        config.save_config()

    logger.info(f"管理员 {username} 更新了高级配置")
    return JSONResponse({"success": True, "message": "高级配置已保存"})


admin_router = router
