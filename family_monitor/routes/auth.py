# -*- coding: utf-8 -*-
"""
认证路由模块
处理用户注册、登录和登出
包含 cookie 安全标志、登录限流
"""

import time
import json
import fcntl
from pathlib import Path
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

# 登录限流：基于文件持久化（data/login_attempts.json）+ fcntl 排他锁，
# 支持多 worker/多进程共享限流计数，避免内存 dict 在多进程下失效
_ATTEMPTS_FILE = Path(__file__).resolve().parent.parent / "data" / "login_attempts.json"


def _check_login_rate_limit(client_ip: str) -> bool:
    """检查登录限流：每分钟每 IP 最多 5 次登录尝试（文件持久化 + fcntl 锁，支持多进程）"""
    now = time.time()
    _ATTEMPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        # 'a+' 保证文件不存在时自动创建
        with open(_ATTEMPTS_FILE, 'a+', encoding='utf-8') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                raw = f.read()
                data = json.loads(raw) if raw.strip() else {}
            except (json.JSONDecodeError, ValueError):
                data = {}
            # 仅保留 60 秒内的尝试记录
            attempts = [t for t in data.get(client_ip, []) if now - t < 60]
            if len(attempts) >= 5:
                allowed = False
            else:
                attempts.append(now)
                allowed = True
            data[client_ip] = attempts
            f.seek(0)
            f.truncate()
            json.dump(data, f, ensure_ascii=False)
            return allowed
    except Exception as e:
        # 限流文件读写异常时放行，避免因限流故障阻断正常登录
        logger.warning(f"登录限流文件读写失败，本次放行: {e}")
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
):
    """处理登录请求"""
    # 登录限流（优先读取反向代理真实 IP）
    client_ip = (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
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
):
    """处理注册请求"""
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
    """处理登出请求：POST，先使会话失效，再删除 cookie"""
    session_token = request.cookies.get("session_token")
    if session_token:
        session_manager = get_session_manager(config.SECRET_KEY)
        session_manager.invalidate_session(session_token)

    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="session_token")
    return response
