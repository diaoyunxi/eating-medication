# -*- coding: utf-8 -*-
"""
认证路由模块
处理用户注册、登录和登出
包含 CSRF 防护、cookie 安全标志、登录限流
"""

import time
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from core import config
from core.auth import get_user_manager
from core.session import get_session_manager, verify_csrf
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
# 注入路径前缀变量，供模板链接加前缀
templates.env.globals["prefix"] = config.PATH_PREFIX

# 登录限流：内存 dict，记录每 IP 的登录尝试时间戳
_login_attempts: dict[str, list[float]] = {}


def _check_login_rate_limit(client_ip: str) -> bool:
    """检查登录限流：每分钟每 IP 最多 5 次登录尝试"""
    now = time.time()
    if client_ip not in _login_attempts:
        _login_attempts[client_ip] = []
    # 清理超过 60 秒的记录
    _login_attempts[client_ip] = [t for t in _login_attempts[client_ip] if now - t < 60]
    if len(_login_attempts[client_ip]) >= 5:
        return False
    _login_attempts[client_ip].append(now)
    return True


@router.get("/login")
async def get_login(request: Request):
    """登录页面"""
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
        }
    )


@router.post("/login")
async def post_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
):
    """处理登录请求"""
    # CSRF 校验
    cookie_token = request.cookies.get("csrf_token", "")
    if not cookie_token or csrf_token != cookie_token:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "app_name": config.APP_NAME, "error": "CSRF 校验失败，请刷新页面重试"},
            status_code=403,
        )

    # 登录限流
    client_ip = request.client.host if request.client else "unknown"
    if not _check_login_rate_limit(client_ip):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "app_name": config.APP_NAME, "error": "登录尝试过于频繁，请稍后再试"},
            status_code=429,
        )

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
            samesite="strict",
            secure=config.COOKIE_SECURE,
        )
        return response
    else:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "app_name": config.APP_NAME,
                "error": message
            }
        )


@router.get("/register")
async def get_register(request: Request):
    """注册页面"""
    return templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "app_name": config.APP_NAME,
        }
    )


@router.post("/register")
async def post_register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(...),
):
    """处理注册请求"""
    # CSRF 校验
    cookie_token = request.cookies.get("csrf_token", "")
    if not cookie_token or csrf_token != cookie_token:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "app_name": config.APP_NAME, "error": "CSRF 校验失败，请刷新页面重试"},
            status_code=403,
        )

    user_manager = get_user_manager(config.DATA_DIR)

    success, message = user_manager.register_user(username, password, confirm_password)
    if success:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "app_name": config.APP_NAME,
                "success": message
            }
        )
    else:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "app_name": config.APP_NAME,
                "error": message,
                "username": username
            }
        )


@router.get("/logout")
async def logout(request: Request):
    """处理登出请求：先使会话失效，再删除 cookie"""
    session_manager = get_session_manager(config.SECRET_KEY)
    # 从 cookie 读取 token 并使会话失效
    token = request.cookies.get("session_token")
    if token:
        session_manager.invalidate_session(token)

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key="session_token")
    response.delete_cookie(key="csrf_token")
    return response
