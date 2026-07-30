# -*- coding: utf-8 -*-
"""认证路由

子女端前端认证流程（方案C：全量改用 JWT，由 server 统一认证）：
1. 前端 AJAX 提交用户名/密码/Turnstile 令牌到本路由
2. 本路由转发到 server 的 /api/v1/auth/login（或 /register）进行验证
3. server 验证 Turnstile 人机验证 + 账号密码，返回 JWT
4. 本路由将 JWT 存入 HttpOnly cookie，返回 JSON 给前端跳转
5. 后续请求由 auth_middleware 转发 JWT 到 server /api/v1/users/me 验证
"""

import os
import httpx
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core.config import config
from common.server_client import BaseServerClient

router = APIRouter()

# 模板对象（用于渲染 login.html / register.html）
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
templates.env.cache = {}
# 注入路径前缀变量，供模板链接加前缀
templates.env.globals["prefix"] = config.PATH_PREFIX

# server API 基础路径前缀
_SERVER_API_BASE = "/api/v1"

# 路径前缀（用于 logout 重定向 URL 拼接）
_PATH_PREFIX = config.PATH_PREFIX.rstrip("/")


# 统一的服务端 HTTP 客户端（内部每次请求使用独立 httpx.AsyncClient）
_server_client = BaseServerClient(
    base_url=f"{config.ELDERLY_SERVER_URL.rstrip('/')}{_SERVER_API_BASE}",
    timeout=15.0,
)


def _server_url(path: str) -> str:
    """拼接 server API 完整 URL（用于 302 跳转目标，需完整地址）

    :param path: API 路径（如 /auth/login）
    :return: 完整 URL（如 https://xxx/api/v1/auth/login）
    """
    return f"{_server_client.base_url}{path}"


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


@router.get("/login")
async def login_page(request: Request):
    """登录页面：渲染 login.html 模板

    补回被误删的 GET /login 路由。
    前端 JS 检测到 Turnstile 不可用时降级为传统表单提交（后端兜底校验）。
    """
    return templates.TemplateResponse(
        request,
        "login.html",
        {"app_name": config.APP_NAME},
    )


@router.get("/register")
async def register_page(request: Request):
    """注册页面：渲染 register.html 模板

    第三方 OAuth 首次登录：server 回调重定向到本页并携带 oauth=1、provider、
    provider_name、prefill_username、prefill_name（以及邮箱冲突时的 bind_email），
    进入 OAuth 补全注册模式——预填昵称并提示绑定，隐藏 Turnstile。
    """
    oauth = request.query_params.get("oauth", "")
    provider = request.query_params.get("provider", "")
    provider_name = request.query_params.get("provider_name", "")
    prefill_username = request.query_params.get("prefill_username", "")
    prefill_name = request.query_params.get("prefill_name", "")
    bind_email = request.query_params.get("bind_email", "")

    oauth_mode = oauth == "1"

    return templates.TemplateResponse(
        request,
        "register.html",
        {
            "app_name": config.APP_NAME,
            "oauth_mode": oauth_mode,
            "oauth_provider": provider,
            "oauth_provider_name": provider_name,
            "prefill_username": prefill_username,
            "prefill_name": prefill_name,
            "bind_email": bind_email,
        },
    )


@router.get("/oauth/github/authorize")
async def oauth_github_authorize():
    """GitHub OAuth 授权入口

    302 跳转到 server 的 authorize 端点；由 server 签发 state 签名 cookie 并继续跳转 GitHub。
    """
    server_authorize = _server_url("/auth/oauth/github/authorize")
    return RedirectResponse(url=server_authorize, status_code=status.HTTP_302_FOUND)


@router.get("/oauth/github/enabled")
async def oauth_github_enabled():
    """前端用于判断 GitHub 登录按钮是否显示（代理 server 的 OAuth 配置）"""
    try:
        resp = await _server_client._execute("GET", "/auth/oauth/github/config")
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {"enabled": False}


@router.get("/oauth/gitee/authorize")
async def oauth_gitee_authorize():
    """Gitee OAuth 授权入口

    302 跳转到 server 的 authorize 端点；由 server 签发 state 签名 cookie 并继续跳转 Gitee。
    """
    server_authorize = _server_url("/auth/oauth/gitee/authorize")
    return RedirectResponse(url=server_authorize, status_code=status.HTTP_302_FOUND)


@router.get("/oauth/gitee/enabled")
async def oauth_gitee_enabled():
    """前端用于判断 Gitee 登录按钮是否显示（代理 server 的 OAuth 配置）"""
    try:
        resp = await _server_client._execute("GET", "/auth/oauth/gitee/config")
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {"enabled": False}


@router.post("/email/send-code")
async def email_send_code(request: Request):
    """邮箱验证码 - 发送：转发到 server /auth/email/send-code

    前端以 JSON 提交 {email, cf_turnstile_token}；返回 {success, message} 或 {success, error}。
    """
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            {"success": False, "error": "请求格式错误"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    email = (payload.get("email") or "").strip()
    turnstile_token = payload.get("cf_turnstile_token", "")

    if not email:
        return JSONResponse(
            {"success": False, "error": "请输入邮箱"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        resp = await _server_client._execute(
            "POST", "/auth/email/send-code",
            json_body={"email": email, "cf_turnstile_token": turnstile_token},
        )
    except httpx.RequestError:
        return JSONResponse(
            {"success": False, "error": "无法连接认证服务，请稍后重试"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    if resp.status_code == 200:
        data = resp.json()
        return JSONResponse({"success": True, "message": data.get("message", "验证码已发送")})
    err_msg = _parse_server_error(resp, "验证码发送失败，请稍后重试")
    return JSONResponse(
        {"success": False, "error": err_msg},
        status_code=resp.status_code if resp.status_code >= 400 else 500,
    )


@router.post("/email/code-login")
async def email_code_login(request: Request):
    """邮箱验证码 - 登录/自动注册：转发到 server /auth/email/code-login

    前端以 JSON 提交 {email, code, cf_turnstile_token}；
    成功时存 JWT cookie 并返回 {"success": true, "redirect": "/"}。
    """
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            {"success": False, "error": "请求格式错误"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    email = (payload.get("email") or "").strip()
    code = (payload.get("code") or "").strip()
    turnstile_token = payload.get("cf_turnstile_token", "")

    if not email or not code:
        return JSONResponse(
            {"success": False, "error": "请输入邮箱和验证码"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        resp = await _server_client._execute(
            "POST", "/auth/email/code-login",
            json_body={"email": email, "code": code, "cf_turnstile_token": turnstile_token},
        )
    except httpx.RequestError:
        return JSONResponse(
            {"success": False, "error": "无法连接认证服务，请稍后重试"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    if resp.status_code != 200:
        err_msg = _parse_server_error(resp, "登录失败，请检查验证码")
        return JSONResponse(
            {"success": False, "error": err_msg},
            status_code=resp.status_code if resp.status_code >= 400 else 500,
        )

    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    if not access_token:
        return JSONResponse(
            {"success": False, "error": "认证服务返回异常"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    redirect_url = f"{_PATH_PREFIX}/" if _PATH_PREFIX else "/"
    response = JSONResponse({"success": True, "redirect": redirect_url})
    return _set_jwt_cookie(response, access_token)


@router.post("/login")
async def post_login(request: Request):
    """登录：转发到 server /auth/login 验证，成功后存 JWT cookie

    :param request: 包含表单数据（username, password, cf-turnstile-response）
    :return: JSON {"success": true, "redirect": "/"} 或 {"success": false, "error": "..."}
    """
    form = await request.form()
    phone = form.get("phone", "").strip()
    password = form.get("password", "")
    turnstile_token = form.get("cf-turnstile-response", "")

    # 后端兜底校验（前端已校验）
    if not phone or not password:
        return JSONResponse(
            {"success": False, "error": "请输入手机号和密码"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # 转发到 server 进行 Turnstile 验证 + 账号密码校验
    try:
        resp = await _server_client._execute(
            "POST", "/auth/login",
            json_body={
                "phone": phone,
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
        err_msg = _parse_server_error(resp, "登录失败，请检查手机号和密码")
        return JSONResponse(
            {"success": False, "error": err_msg},
            status_code=resp.status_code if resp.status_code >= 400 else 500,
        )

    # 提取 JWT 并存入 HttpOnly cookie
    token_data = resp.json()
    # 已开启 TOTP 第二因子：密码正确但需再校验动态码，返回 MFA 挑战令牌
    if token_data.get("mfa_required"):
        return JSONResponse(
            {
                "success": True,
                "mfa_required": True,
                "mfa_token": token_data.get("mfa_token", ""),
            }
        )
    access_token = token_data.get("access_token", "")
    if not access_token:
        return JSONResponse(
            {"success": False, "error": "认证服务返回异常"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    # redirect 显式拼接 PATH_PREFIX，避免隧道子路径模式下跳转到根路径
    redirect_url = f"{_PATH_PREFIX}/" if _PATH_PREFIX else "/"
    response = JSONResponse({"success": True, "redirect": redirect_url})
    return _set_jwt_cookie(response, access_token)


@router.post("/register")
async def post_register(request: Request):
    """注册：转发到 server /auth/register，成功后存 JWT cookie 并自动登录

    子女端注册默认昵称（username）可选、role=family。

    :param request: 包含表单数据（username, password, confirm_password, cf-turnstile-response）
    :return: JSON {"success": true, "redirect": "/"} 或 {"success": false, "error": "..."}
    """
    form = await request.form()
    phone = form.get("phone", "").strip()
    nickname = form.get("username", "").strip()  # 昵称，可选
    password = form.get("password", "")
    confirm_password = form.get("confirm_password", "")
    turnstile_token = form.get("cf-turnstile-response", "")

    # 后端兜底校验
    if not phone or not password:
        return JSONResponse(
            {"success": False, "error": "请输入手机号和密码"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if password != confirm_password:
        return JSONResponse(
            {"success": False, "error": "两次输入的密码不一致"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # 第三方 OAuth 补全注册：携带 GitHub/Gitee 一次性身份 cookie（oauth_pending）时
    # 转发 oauth_token（server 侧跳过 Turnstile 人机验证）
    oauth_token = request.cookies.get("oauth_pending", "") or request.cookies.get("oauth_pending_gitee", "")

    # 转发到 server 进行 Turnstile 验证 + 注册
    try:
        json_body = {
            "phone": phone,
            "username": nickname or None,
            "password": password,
            "role": "family",       # 子女端注册默认角色为 family
            "cf_turnstile_token": turnstile_token,
        }
        if oauth_token:
            json_body["oauth_token"] = oauth_token
        resp = await _server_client._execute("POST", "/auth/register", json_body=json_body)
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
    login_redirect = f"{_PATH_PREFIX}/login" if _PATH_PREFIX else "/login"
    # 注册后引导绑定第二因子 / 通行密钥（注册时引导绑定）
    security_redirect = f"{_PATH_PREFIX}/security-setup" if _PATH_PREFIX else "/security-setup"
    if not access_token:
        # 注册成功但未返回 token，跳转登录页手动登录
        return JSONResponse({"success": True, "redirect": login_redirect})

    response = JSONResponse({"success": True, "redirect": security_redirect})
    response = _set_jwt_cookie(response, access_token)
    # OAuth 补全注册成功后清除对应平台的一次性身份 cookie，避免重复利用
    if oauth_token:
        if request.cookies.get("oauth_pending_gitee"):
            response.delete_cookie(key="oauth_pending_gitee", path="/")
        else:
            response.delete_cookie(key="oauth_pending", path="/")
    return response


async def _do_logout():
    """退出登录核心逻辑：清除 JWT cookie 并返回重定向响应

    显式拼接 PATH_PREFIX，避免隧道子路径模式下重定向到错误地址。
    原代码仅注册 GET /logout，但前端使用 POST 表单提交，
    导致 405 Method Not Allowed。现抽取公共逻辑，GET/POST 均可触发。
    """
    login_url = f"{_PATH_PREFIX}/login" if _PATH_PREFIX else "/login"
    response = RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token", path="/")
    return response


@router.get("/logout")
async def logout():
    """退出登录（GET 方式，兼容直接链接跳转）"""
    return await _do_logout()


@router.post("/logout")
async def logout_post():
    """退出登录（POST 方式，前端表单提交）

    前端登出按钮使用 POST 表单提交，但原代码仅注册 GET /logout，
    导致返回 405 Method Not Allowed。新增 POST 处理器修复此问题。
    """
    return await _do_logout()


def _parse_server_error(resp: httpx.Response, default_msg: str) -> str:
    """解析 server 返回的错误信息

    处理两种格式：
    1. FastAPI HTTPException: {"detail": "错误消息"}
    2. FastAPI 422 验证错误: {"detail": [{"loc": [...], "msg": "...", "type": "..."}]}

    :param resp: httpx 响应对象
    :param default_msg: 解析失败时的默认错误信息
    :return: 错误信息字符串
    """
    try:
        err_data = resp.json()
        detail = err_data.get("detail", default_msg)
        # 处理 FastAPI 422 验证错误（detail 是列表）
        if isinstance(detail, list):
            # 提取所有错误消息，用分号连接
            messages = []
            for item in detail:
                if isinstance(item, dict):
                    msg = item.get("msg", "")
                    loc = item.get("loc", [])
                    # 提取字段名（跳过 "body" 前缀）
                    field = ".".join(str(x) for x in loc if x != "body")
                    if field and msg:
                        messages.append(f"{field}: {msg}")
                    elif msg:
                        messages.append(msg)
            return "; ".join(messages) if messages else default_msg
        # 处理普通 HTTPException（detail 是字符串）
        if isinstance(detail, str):
            return detail
        return default_msg
    except Exception:
        return default_msg


# ==================== TOTP 第二因子 / WebAuthn Passkey 代理 ====================
def _auth_headers(request: Request) -> dict:
    """从 cookie 取出 JWT 并构造 Authorization 请求头（转发到 server 的需登录端点）"""
    token = request.cookies.get("access_token", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


@router.post("/totp/setup")
async def totp_setup(request: Request):
    """TOTP 密钥生成（需登录）：转发到 server /auth/totp/setup"""
    headers = _auth_headers(request)
    if not headers:
        return JSONResponse({"success": False, "error": "未登录"}, status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        resp = await _server_client._execute("POST", _server_url("/auth/totp/setup"), headers=headers)
    except httpx.RequestError:
        return JSONResponse({"success": False, "error": "无法连接认证服务，请稍后重试"}, status_code=status.HTTP_502_BAD_GATEWAY)
    return JSONResponse(resp.json(), status_code=resp.status_code)


@router.post("/totp/enable")
async def totp_enable(request: Request):
    """TOTP 启用（需登录）：转发到 server /auth/totp/enable"""
    headers = _auth_headers(request)
    if not headers:
        return JSONResponse({"success": False, "error": "未登录"}, status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        resp = await _server_client._execute("POST", _server_url("/auth/totp/enable"), json_body=body, headers=headers)
    except httpx.RequestError:
        return JSONResponse({"success": False, "error": "无法连接认证服务，请稍后重试"}, status_code=status.HTTP_502_BAD_GATEWAY)
    return JSONResponse(resp.json(), status_code=resp.status_code)


@router.post("/totp/disable")
async def totp_disable(request: Request):
    """TOTP 关闭（需登录）：转发到 server /auth/totp/disable"""
    headers = _auth_headers(request)
    if not headers:
        return JSONResponse({"success": False, "error": "未登录"}, status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        resp = await _server_client._execute("POST", _server_url("/auth/totp/disable"), json_body=body, headers=headers)
    except httpx.RequestError:
        return JSONResponse({"success": False, "error": "无法连接认证服务，请稍后重试"}, status_code=status.HTTP_502_BAD_GATEWAY)
    return JSONResponse(resp.json(), status_code=resp.status_code)


@router.post("/totp/verify")
async def totp_verify(request: Request):
    """TOTP 第二步验证（公开）：校验动态码后存 JWT cookie 并跳转"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        resp = await _server_client._execute("POST", _server_url("/auth/totp/verify"), json_body=body)
    except httpx.RequestError:
        return JSONResponse({"success": False, "error": "无法连接认证服务，请稍后重试"}, status_code=status.HTTP_502_BAD_GATEWAY)
    if resp.status_code != 200:
        err_msg = _parse_server_error(resp, "动态验证码错误")
        return JSONResponse(
            {"success": False, "error": err_msg},
            status_code=resp.status_code if resp.status_code >= 400 else 500,
        )
    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    if not access_token:
        return JSONResponse({"success": False, "error": "认证服务返回异常"}, status_code=status.HTTP_502_BAD_GATEWAY)
    redirect_url = f"{_PATH_PREFIX}/" if _PATH_PREFIX else "/"
    response = JSONResponse({"success": True, "redirect": redirect_url})
    return _set_jwt_cookie(response, access_token)


# ---- WebAuthn / Passkey ----
@router.post("/webauthn/register/options")
async def webauthn_register_options(request: Request):
    """通行密钥登记选项（需登录）：转发到 server /auth/webauthn/register/options"""
    headers = _auth_headers(request)
    if not headers:
        return JSONResponse({"success": False, "error": "未登录"}, status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        resp = await _server_client._execute("POST", _server_url("/auth/webauthn/register/options"), headers=headers)
    except httpx.RequestError:
        return JSONResponse({"success": False, "error": "无法连接认证服务，请稍后重试"}, status_code=status.HTTP_502_BAD_GATEWAY)
    return JSONResponse(resp.json(), status_code=resp.status_code)


@router.post("/webauthn/register")
async def webauthn_register(request: Request):
    """通行密钥登记提交（需登录）：转发到 server /auth/webauthn/register"""
    headers = _auth_headers(request)
    if not headers:
        return JSONResponse({"success": False, "error": "未登录"}, status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        resp = await _server_client._execute("POST", _server_url("/auth/webauthn/register"), json_body=body, headers=headers)
    except httpx.RequestError:
        return JSONResponse({"success": False, "error": "无法连接认证服务，请稍后重试"}, status_code=status.HTTP_502_BAD_GATEWAY)
    return JSONResponse(resp.json(), status_code=resp.status_code)


@router.post("/webauthn/login/options")
async def webauthn_login_options(request: Request):
    """无用户名登录断言选项（公开）：转发到 server /auth/webauthn/login/options"""
    try:
        resp = await _server_client._execute("POST", _server_url("/auth/webauthn/login/options"))
    except httpx.RequestError:
        return JSONResponse({"success": False, "error": "无法连接认证服务，请稍后重试"}, status_code=status.HTTP_502_BAD_GATEWAY)
    return JSONResponse(resp.json(), status_code=resp.status_code)


@router.post("/webauthn/login")
async def webauthn_login(request: Request):
    """无用户名通行密钥登录（公开）：校验后存 JWT cookie 并跳转"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        resp = await _server_client._execute("POST", _server_url("/auth/webauthn/login"), json_body=body)
    except httpx.RequestError:
        return JSONResponse({"success": False, "error": "无法连接认证服务，请稍后重试"}, status_code=status.HTTP_502_BAD_GATEWAY)
    if resp.status_code != 200:
        err_msg = _parse_server_error(resp, "通行密钥登录失败")
        return JSONResponse(
            {"success": False, "error": err_msg},
            status_code=resp.status_code if resp.status_code >= 400 else 500,
        )
    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    if not access_token:
        return JSONResponse({"success": False, "error": "认证服务返回异常"}, status_code=status.HTTP_502_BAD_GATEWAY)
    redirect_url = f"{_PATH_PREFIX}/" if _PATH_PREFIX else "/"
    response = JSONResponse({"success": True, "redirect": redirect_url})
    return _set_jwt_cookie(response, access_token)


@router.get("/webauthn/credentials")
async def webauthn_list_credentials(request: Request):
    """列出当前用户的通行密钥（需登录）"""
    headers = _auth_headers(request)
    if not headers:
        return JSONResponse({"success": False, "error": "未登录"}, status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        resp = await _server_client._execute("GET", _server_url("/auth/webauthn/credentials"), headers=headers)
    except httpx.RequestError:
        return JSONResponse({"success": False, "error": "无法连接认证服务，请稍后重试"}, status_code=status.HTTP_502_BAD_GATEWAY)
    return JSONResponse(resp.json(), status_code=resp.status_code)


@router.delete("/webauthn/credentials/{cred_id}")
async def webauthn_delete_credential(cred_id: str, request: Request):
    """删除指定通行密钥（需登录）"""
    headers = _auth_headers(request)
    if not headers:
        return JSONResponse({"success": False, "error": "未登录"}, status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        resp = await _server_client._execute("DELETE", _server_url(f"/auth/webauthn/credentials/{cred_id}"), headers=headers)
    except httpx.RequestError:
        return JSONResponse({"success": False, "error": "无法连接认证服务，请稍后重试"}, status_code=status.HTTP_502_BAD_GATEWAY)
    return JSONResponse(resp.json(), status_code=resp.status_code)


@router.get("/security-setup")
async def security_setup_page(request: Request):
    """安全设置页：引导绑定 TOTP 第二因子与通行密钥（需登录，由 auth_middleware 保护）"""
    token = request.cookies.get("access_token", "")
    context = {
        "app_name": config.APP_NAME,
        "mfa_enabled": False,
        "credentials": [],
        "username": "",
        "phone": "",
    }
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            me = await _server_client._execute("GET", _server_url("/users/me"), headers=headers)
            if me.status_code == 200:
                udata = me.json()
                context["username"] = udata.get("username", "")
                context["phone"] = udata.get("phone", "")
                context["mfa_enabled"] = bool(udata.get("mfa_enabled", False))
        except Exception:
            pass
        try:
            creds = await _server_client._execute("GET", _server_url("/auth/webauthn/credentials"), headers=headers)
            if creds.status_code == 200:
                context["credentials"] = creds.json()
        except Exception:
            pass
    return templates.TemplateResponse(request, "security_setup.html", context)
