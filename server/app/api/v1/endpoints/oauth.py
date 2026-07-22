# -*- coding: utf-8 -*-
"""GitHub OAuth 登录端点

流程：
1. GET /oauth/github/authorize
   - 服务端生成随机 state，签发为签名 HttpOnly cookie（防 CSRF）
   - 302 跳转到 GitHub 授权页（携带 client_id / redirect_uri / scope / state）
2. GitHub 回调 GET /oauth/github/callback?code=xxx&state=yyy
   - 校验 state cookie 与回调 state 一致
   - 用 code + client_secret 换取 GitHub access_token
   - 拉取 GitHub 用户信息（read:user）
   - 已绑定 github_id -> 直接写 access_token cookie 并 302 跳 family 首页
   - 未绑定 -> 签发短期 oauth_pending cookie，302 跳 family 注册页补全信息
"""

import logging
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_db
from app.core.security import (
    create_access_token,
    create_oauth_pending_token,
    create_oauth_state_token,
    verify_oauth_pending_token,
    verify_oauth_state_token,
)
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

# 与 auth.py 共用 /auth 前缀，最终路径为 /api/v1/auth/oauth/github/...
router = APIRouter(prefix="/auth", tags=["OAuth 登录"])

_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_API_USER = "https://api.github.com/user"
_OAUTH_SCOPE = "read:user"
_STATE_COOKIE = "oauth_state"
_PENDING_COOKIE = "oauth_pending"
# 生产环境（DEBUG=false）下 cookie 强制 Secure；开发环境允许非 HTTPS
_COOKIE_SECURE = not settings.DEBUG


def _cookie_kwargs(max_age: int) -> dict:
    """返回统一的 OAuth cookie 参数"""
    return {
        "httponly": True,
        "secure": _COOKIE_SECURE,
        "samesite": "lax",
        "max_age": max_age,
        "path": "/",
    }


@router.get("/oauth/github/config")
def github_oauth_config():
    """前端用于判断 GitHub 登录按钮是否显示"""
    return {"enabled": bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET)}


@router.get("/oauth/github/authorize")
def github_authorize():
    """GitHub OAuth 授权入口：签发 state 签名 cookie 并重定向到 GitHub"""
    if not settings.GITHUB_CLIENT_ID:
        return JSONResponse(status_code=400, content={"detail": "GitHub OAuth 未配置"})

    import secrets
    state = secrets.token_urlsafe(24)
    state_token = create_oauth_state_token(state)

    github_params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_OAUTH_CALLBACK_URL,
        "scope": _OAUTH_SCOPE,
        "state": state,
        "allow_signup": "true",
    }
    github_url = f"{_GITHUB_AUTHORIZE_URL}?{urlencode(github_params)}"
    response = RedirectResponse(url=github_url, status_code=302)
    response.set_cookie(key=_STATE_COOKIE, value=state_token, **_cookie_kwargs(600))
    return response


@router.get("/oauth/github/callback")
def github_callback(code: str = None, state: str = None, request: Request = None, db: Session = Depends(get_db)):
    """GitHub OAuth 回调：换 token -> 查用户 -> 登录或引导补全注册"""
    family_login = f"{settings.FAMILY_WEB_URL}/login"

    # 校验 state（防 CSRF）
    state_token = request.cookies.get(_STATE_COOKIE)
    expected_state = verify_oauth_state_token(state_token) if state_token else None
    if not state or not expected_state or state != expected_state:
        logger.warning("GitHub OAuth state 校验失败")
        return _clear_and_redirect(_STATE_COOKIE, f"{family_login}?error=oauth_state")

    if not code:
        return _clear_and_redirect(_STATE_COOKIE, f"{family_login}?error=oauth_code")

    # 用 code 换 GitHub access_token
    try:
        token_resp = httpx.post(
            _GITHUB_TOKEN_URL,
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": settings.GITHUB_OAUTH_CALLBACK_URL,
            },
            headers={"Accept": "application/json"},
            timeout=10,
        )
        token_json = token_resp.json()
        access_token = token_json.get("access_token")
        if not access_token:
            logger.error(f"GitHub 换 token 失败: {token_json}")
            return _clear_and_redirect(_STATE_COOKIE, f"{family_login}?error=oauth_token")
    except Exception as e:
        logger.error(f"GitHub OAuth 换取 access_token 异常: {e}")
        return _clear_and_redirect(_STATE_COOKIE, f"{family_login}?error=oauth_fail")

    # 拉取 GitHub 用户信息
    try:
        user_resp = httpx.get(
            _GITHUB_API_USER,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=10,
        )
        gh = user_resp.json()
        github_id = gh.get("id")
        github_login = gh.get("login") or ""
        github_name = gh.get("name") or github_login
        github_avatar = gh.get("avatar_url")
    except Exception as e:
        logger.error(f"GitHub OAuth 拉取用户信息异常: {e}")
        return _clear_and_redirect(_STATE_COOKIE, f"{family_login}?error=oauth_fail")

    # 已绑定 -> 直接登录
    existing = AuthService.get_by_github_id(db, github_id)
    if existing:
        jwt_token = create_access_token(data={"sub": existing.id})
        response = _clear_and_redirect(_STATE_COOKIE, f"{settings.FAMILY_WEB_URL}/")
        response.set_cookie(
            key="access_token",
            value=jwt_token,
            **_cookie_kwargs(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
        )
        return response

    # 首次登录 -> 签发 oauth_pending 令牌并跳转到 family 注册页补全信息
    pending = create_oauth_pending_token(github_id, github_login, github_name, github_avatar)
    register_url = (
        f"{settings.FAMILY_WEB_URL}/register"
        f"?gh_login={quote(github_login)}&gh_name={quote(github_name or '')}"
    )
    response = _clear_and_redirect(_STATE_COOKIE, register_url)
    response.set_cookie(key=_PENDING_COOKIE, value=pending, **_cookie_kwargs(900))
    return response


def _clear_and_redirect(cookie_key: str, url: str) -> RedirectResponse:
    """构造 302 重定向并删除指定 cookie"""
    response = RedirectResponse(url=url, status_code=302)
    response.delete_cookie(key=cookie_key, path="/")
    return response
