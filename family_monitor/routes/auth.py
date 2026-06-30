# -*- coding: utf-8 -*-
"""
认证路由模块
处理用户注册、登录和登出
"""

from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from core import config
from core.auth import get_user_manager
from core.session import get_session_manager
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


@router.get("/login")
async def get_login(request: Request):
    """登录页面"""
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "app_name": config.APP_NAME
        }
    )


@router.post("/login")
async def post_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    """处理登录请求"""
    user_manager = get_user_manager(config.DATA_DIR)
    session_manager = get_session_manager(config.SECRET_KEY)

    success, message = user_manager.authenticate_user(username, password)

    if success:
        response = RedirectResponse(url="/", status_code=302)
        token = session_manager.create_session(username)
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            max_age=86400 * 7,
            samesite="lax"
        )
        return response
    else:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "app_name": config.APP_NAME,
                "error": message
            }
        )


@router.get("/register")
async def get_register(request: Request):
    """注册页面"""
    return templates.TemplateResponse(
        request,
        "register.html",
        {
            "app_name": config.APP_NAME
        }
    )


@router.post("/register")
async def post_register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    """处理注册请求"""
    user_manager = get_user_manager(config.DATA_DIR)

    success, message = user_manager.register_user(username, password, confirm_password)
    if success:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "app_name": config.APP_NAME,
                "success": message
            }
        )
    else:
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "app_name": config.APP_NAME,
                "error": message,
                "username": username
            }
        )


@router.get("/logout")
async def logout(request: Request):
    """处理登出请求"""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key="session_token")
    return response