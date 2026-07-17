# -*- coding: utf-8 -*-
"""认证路由

子女端前端认证流程（方案C：全量改用 JWT，由 server 统一认证）：
1. 前端 AJAX 提交用户名/密码/Turnstile 令牌到本路由
2. 本路由转发到 server 的 /api/v1/auth/login（或 /register）进行验证
3. server 验证 Turnstile 人机验证 + 账号密码，返回 JWT
4. 本路由将 JWT 存入 HttpOnly cookie，返回 JSON 给前端跳转
5. 后续请求由 auth_middleware 转发 JWT 到 server /api/v1/users/me 验证
"""

import httpx
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from core.config import config

router = APIRouter()

# server API 基础路径前缀
_SERVER_API_BASE = "/api/v1"


def _server_url(path: str) -> str:
    """拼接 server API 完整 URL

    :param path: API 路径（如 /auth/login）
    :return: 完整 URL（如 https://xxx/api/v1/auth/login）
    """
    base = config.ELDERLY_SERVER_URL.rstrip("/")
    return f"{base}{_SERVER_API_BASE}{path}"


def _set_jwt_cookie(response: JSONResponse, access_token: str) -> JSONResponse:
    """将 JWT 写入 HttpOnly cookie

    :param response: 待附加 cookie 的响应对象
    :param access_token: server 返回的 JWT
    :return: 带 cookie 的响应对象
    """
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        max_age=3600,  # 与 server JWT 过期时间一致（1 小时）
        path="/",
    )
    return response


@router.get("/turnstile/site-key")
async def get_turnstile_site_key():
    """返回 Cloudflare Turnstile 站点密钥供前端渲染人机验证组件

    Site Key 非敏感信息（本就暴露在前端），但按需求统一从 .env 读取，
    避免硬编码在模板中。
    """
    return {"site_key": config.TURNSTILE_SITE_KEY}


@router.post("/login")
async def post_login(request: Request):
    """登录：转发到 server /auth/login 验证，成功后存 JWT cookie

    :param request: 包含表单数据（username, password, cf-turnstile-response）
    :return: JSON {"success": true, "redirect": "/"} 或 {"success": false, "error": "..."}
    """
    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password", "")
    turnstile_token = form.get("cf-turnstile-response", "")

    # 后端兜底校验（前端已校验）
    if not username or not password:
        return JSONResponse(
            {"success": False, "error": "请输入用户名和密码"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # 转发到 server 进行 Turnstile 验证 + 账号密码校验
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _server_url("/auth/login"),
                json={
                    "username": username,
                    "password": password,
                    "cf_turnstile_token": turnstile_token,
                },
            )
    except httpx.RequestError:
        return JSONResponse(
            {"success": False, "error": "无法连接认证服务，请稍后重试"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    # server 返回非 200 表示登录失败
    if resp.status_code != 200:
        err_msg = _parse_server_error(resp, "登录失败，请检查用户名和密码")
        return JSONResponse(
            {"success": False, "error": err_msg},
            status_code=resp.status_code if resp.status_code >= 400 else 500,
        )

    # 提取 JWT 并存入 HttpOnly cookie
    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    if not access_token:
        return JSONResponse(
            {"success": False, "error": "认证服务返回异常"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    response = JSONResponse({"success": True, "redirect": "/"})
    return _set_jwt_cookie(response, access_token)


@router.post("/register")
async def post_register(request: Request):
    """注册：转发到 server /auth/register，成功后存 JWT cookie 并自动登录

    子女端注册默认 full_name=username、role=family。

    :param request: 包含表单数据（username, password, confirm_password, cf-turnstile-response）
    :return: JSON {"success": true, "redirect": "/"} 或 {"success": false, "error": "..."}
    """
    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password", "")
    confirm_password = form.get("confirm_password", "")
    turnstile_token = form.get("cf-turnstile-response", "")

    # 后端兜底校验
    if not username or not password:
        return JSONResponse(
            {"success": False, "error": "请输入用户名和密码"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if password != confirm_password:
        return JSONResponse(
            {"success": False, "error": "两次输入的密码不一致"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # 转发到 server 进行 Turnstile 验证 + 注册
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _server_url("/auth/register"),
                json={
                    "username": username,
                    "password": password,
                    "full_name": username,  # 子女端注册默认 full_name 为用户名
                    "role": "family",       # 子女端注册默认角色为 family
                    "phone": None,
                    "cf_turnstile_token": turnstile_token,
                },
            )
    except httpx.RequestError:
        return JSONResponse(
            {"success": False, "error": "无法连接认证服务，请稍后重试"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    # server 返回非 201 表示注册失败
    if resp.status_code != 201:
        err_msg = _parse_server_error(resp, "注册失败，请稍后重试")
        return JSONResponse(
            {"success": False, "error": err_msg},
            status_code=resp.status_code if resp.status_code >= 400 else 500,
        )

    # 注册成功，提取 JWT 并存 cookie（自动登录）
    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    if not access_token:
        # 注册成功但未返回 token，跳转登录页手动登录
        return JSONResponse({"success": True, "redirect": "/login"})

    response = JSONResponse({"success": True, "redirect": "/"})
    return _set_jwt_cookie(response, access_token)


@router.get("/logout")
async def logout():
    """退出登录：清除 JWT cookie 并跳转登录页"""
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token", path="/")
    return response


def _parse_server_error(resp: httpx.Response, default_msg: str) -> str:
    """解析 server 返回的错误信息

    :param resp: httpx 响应对象
    :param default_msg: 解析失败时的默认错误信息
    :return: 错误信息字符串
    """
    try:
        err_data = resp.json()
        # FastAPI HTTPException 返回 {"detail": "..."} 格式
        return err_data.get("detail", default_msg)
    except Exception:
        return default_msg
