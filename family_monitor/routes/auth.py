# -*- coding: utf-8 -*-
"""
认证路由模块
处理用户注册、登录和登出
包含 CSRF 防护、cookie 安全标志、登录限流
"""

import time
import secrets
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from core import config
from core.auth import get_user_manager
from core.session import get_session_manager
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
    # 清理超过 60 秒的记录
    recent = [t for t in _login_attempts.get(client_ip, []) if now - t < 60]
    # 修复内存泄漏：列表为空则删除该 key，避免 dict 累积空列表
    if not recent:
        _login_attempts.pop(client_ip, None)
    if len(recent) >= 5:
        _login_attempts[client_ip] = recent
        return False
    recent.append(now)
    _login_attempts[client_ip] = recent
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
    # CSRF 校验（H-2 修复：常量时间比较）
    cookie_token = request.cookies.get("csrf_token", "")
    if not cookie_token or not secrets.compare_digest(csrf_token, cookie_token):
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
    # CSRF 校验（H-2 修复：常量时间比较）
    cookie_token = request.cookies.get("csrf_token", "")
    if not cookie_token or not secrets.compare_digest(csrf_token, cookie_token):
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


@router.post("/logout")
async def logout(request: Request):
    """处理登出请求：POST + CSRF 校验，先使会话失效，再删除 cookie"""
    csrf_token = request.headers.get("X-CSRF-Token")
    cookie_token = request.cookies.get("csrf_token")
    if not csrf_token or not cookie_token or not secrets.compare_digest(csrf_token, cookie_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid")
    session_token = request.cookies.get("session_token")
    if session_token:
        session_manager = get_session_manager(config.SECRET_KEY)
        session_manager.invalidate_session(session_token)

    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="session_token")
    response.delete_cookie(key="csrf_token")
    return response
