# -*- coding: utf-8 -*-
"""OAuth 第三方登录（GitHub / Gitee）基于 fastapi-oauth20 重构

本模块使用 fastapi-oauth20 提供的 GitHubOAuth20 / GiteeOAuth20 客户端完成
authorization_code 换取 access_token，并借助 FastAPIOAuth20 回调依赖处理 code 换 token。

两种平台流程与重构前完全一致：
  authorize 设 state cookie 并 302 跳转授权页 -> 用户同意后回调本服务 callback
  -> 换 token -> 拉用户信息 -> 已绑定则直接签发 JWT 登录，
  未绑定则签发短期 pending 令牌（写入 HttpOnly cookie）并跳转 family_monitor 注册页补全。

业务侧（state 校验、pending 令牌、账号绑定/登录、302 跳转目标）保持不变，
仅将「构造授权地址 / code 换 token / 拉用户信息」三段 OAuth 机械流程委托给 fastapi-oauth20。
"""
import secrets
import logging
from typing import Any, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from fastapi_oauth20 import (
    GitHubOAuth20,
    GiteeOAuth20,
    FastAPIOAuth20,
    OAuth20AuthorizeCallbackError,
)
from fastapi_oauth20.errors import GetUserInfoError

from app.core.database import get_db
from app.core.config import settings
from app.core.security import (
    create_oauth_state_token,
    verify_oauth_state_token,
    create_oauth_pending_token,
    create_access_token,
)
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)
router = APIRouter()


# ===================== Gitee 兼容客户端 =====================
class GiteeOAuth20Compat(GiteeOAuth20):
    """Gitee 兼容子类。

    fastapi-oauth20 基类 get_userinfo 默认使用 ``Authorization: Bearer <token>``，
    而 Gitee 开放 API 实际支持的是 ``Authorization: token <token>``（历史约定）。
    覆盖 get_userinfo 以保留原有可用的鉴权头，避免重构后 Gitee 拉取用户信息失败。
    """

    async def get_userinfo(self, access_token: str) -> dict[str, Any]:
        headers = {"Authorization": f"token {access_token}"}
        async with httpx.AsyncClient(headers=headers) as client:
            response = await client.get(self.userinfo_endpoint)
            self.raise_httpx_oauth20_errors(response)
            return self.get_json_result(response, err_class=GetUserInfoError)


# ===================== fastapi-oauth20 客户端与回调处理器 =====================
# 仅当配置了 client_id / client_secret 时才实例化，避免缺少配置时模块导入报错。
# FastAPIOAuth20 是 FastAPI 依赖，回调时通过 handler(request, code=..., state=...) 完成
# code 换 token，返回 (token_data, state)。
def _build_oauth_clients() -> dict:
    clients: dict[str, dict] = {}

    if settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET:
        gh_client = GitHubOAuth20(
            client_id=settings.GITHUB_CLIENT_ID,
            client_secret=settings.GITHUB_CLIENT_SECRET,
        )
        clients["github"] = {
            "client": gh_client,
            "handler": FastAPIOAuth20(gh_client, redirect_uri=settings.GITHUB_OAUTH_CALLBACK_URL),
            "callback_url": settings.GITHUB_OAUTH_CALLBACK_URL,
            "scope": ["read:user", "user:email"],
            "allow_signup": True,                       # GitHub 授权页允许新用户注册
            "auth_header": "Bearer",                     # 拉 /emails 时的 Authorization 前缀
            "emails_api": None,                          # GitHub 的 user 接口已含 public email，由客户端内部处理
        }

    if settings.GITEE_CLIENT_ID and settings.GITEE_CLIENT_SECRET:
        gt_client = GiteeOAuth20Compat(
            client_id=settings.GITEE_CLIENT_ID,
            client_secret=settings.GITEE_CLIENT_SECRET,
        )
        clients["gitee"] = {
            "client": gt_client,
            "handler": FastAPIOAuth20(gt_client, redirect_uri=settings.GITEE_OAUTH_CALLBACK_URL),
            "callback_url": settings.GITEE_OAUTH_CALLBACK_URL,
            "scope": ["user_info", "emails"],            # 需 emails 权限才能拉取邮箱
            "allow_signup": False,
            "auth_header": "token",                       # Gitee 使用 "token <access_token>" 而非 Bearer
            "emails_api": "https://gitee.com/api/v5/emails",
        }

    return clients


_OAUTH = _build_oauth_clients()


def _provider_enabled(provider: str) -> bool:
    """provider 是否已配置（client_id 与 client_secret 同时存在）"""
    return provider in _OAUTH


def _cookie_kwargs(max_age: int) -> dict:
    """统一 cookie 属性（HttpOnly + SameSite=Lax + 生产环境 Secure）"""
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": not settings.DEBUG,
        "max_age": max_age,
        "path": "/",
    }


def _clear_and_redirect(cookie_name: str, target: str) -> RedirectResponse:
    """清理 state cookie 并跳转到 target（用于异常分支）"""
    resp = RedirectResponse(url=target, status_code=302)
    resp.delete_cookie(key=cookie_name, path="/")
    return resp


async def _fetch_email(emails_api: str, access_token: str, auth_header: str) -> Optional[str]:
    """拉取第三方邮箱（Gitee 主邮箱为空时补充调用 /emails）"""
    headers = {"Accept": "application/json", "Authorization": f"{auth_header} {access_token}"}
    try:
        resp = httpx.get(emails_api, headers=headers, timeout=10)
        emails = resp.json()
        if isinstance(emails, list) and emails:
            # 优先取「主邮箱且已验证」，否则取列表首个
            primary = next(
                (e for e in emails if e.get("primary") and e.get("verified")),
                emails[0],
            )
            return primary.get("email")
    except Exception as e:
        logger.warning(f"获取 {emails_api} 邮箱失败: {e}")
    return None


async def _normalize_user(cfg: dict, raw: dict, access_token: str) -> dict:
    """将第三方原始用户信息统一为 provider_id / login / name / avatar / email"""
    email = raw.get("email")
    if not email and cfg.get("emails_api"):
        email = await _fetch_email(cfg["emails_api"], access_token, cfg["auth_header"])
    return {
        "provider_id": raw.get("id"),
        "provider_login": raw.get("login") or "",
        "provider_name": raw.get("name") or raw.get("login") or "",
        "provider_avatar": raw.get("avatar_url"),
        "email": email,
    }


# ===================== 通用流程实现 =====================
async def _authorize(provider: str) -> RedirectResponse:
    """发起第三方授权：设 state cookie 并 302 跳转授权页"""
    cfg = _OAUTH.get(provider)
    if cfg is None:
        return JSONResponse(
            status_code=400,
            content={"detail": f"{provider} OAuth 未配置（缺少 CLIENT_ID / CLIENT_SECRET）"},
        )

    state = secrets.token_urlsafe(24)
    state_token = create_oauth_state_token(state)

    # 委托 fastapi-oauth20 构造授权地址（自动拼接 client_id / redirect_uri / scope / state）
    extra = {"allow_signup": "true"} if cfg.get("allow_signup") else {}
    auth_url = await cfg["client"].get_authorization_url(
        redirect_uri=cfg["callback_url"],
        state=state,
        scope=cfg["scope"],
        **extra,
    )
    resp = RedirectResponse(url=auth_url, status_code=302)
    resp.set_cookie(
        key=f"oauth_state_{provider}",
        value=state_token,
        **_cookie_kwargs(600),
    )
    return resp


async def _callback(
    provider: str,
    code: Optional[str],
    state: Optional[str],
    request: Request,
    db: Session,
) -> RedirectResponse:
    """第三方授权回跳：校验 state -> 换 token -> 拉用户信息 -> 登录或跳注册"""
    cfg = _OAUTH.get(provider)
    state_cookie = f"oauth_state_{provider}"
    family_login = f"{settings.FAMILY_WEB_URL}/login"

    if cfg is None:
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_fail")

    # —— state 校验（防 CSRF）——
    state_token = request.cookies.get(state_cookie)
    expected_state = verify_oauth_state_token(state_token) if state_token else None
    if not state or not expected_state or state != expected_state:
        logger.warning(f"{provider} OAuth state 校验失败")
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_state")
    if not code:
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_code")

    # —— 换取 access_token（委托 fastapi-oauth20 的 FastAPIOAuth20 回调依赖）——
    try:
        token_data, _ = await cfg["handler"](request, code=code, state=state)
    except OAuth20AuthorizeCallbackError as e:
        logger.error(f"{provider} OAuth code 换 token 失败: {e.detail}")
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_fail")

    access_token = token_data.get("access_token")
    if not access_token:
        logger.error(f"{provider} 换 token 返回数据缺少 access_token: {token_data}")
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_token")

    # —— 拉取用户信息（委托客户端 get_userinfo）——
    try:
        raw = await cfg["client"].get_userinfo(access_token)
        info = await _normalize_user(cfg, raw, access_token)
    except Exception as e:
        logger.error(f"{provider} OAuth 拉取用户信息异常: {e}")
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_fail")

    provider_id = info["provider_id"]
    if not provider_id:
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_user")

    # —— 已绑定 -> 直接登录并签发 JWT ——
    existing = AuthService.get_by_provider(db, provider, provider_id)
    if existing:
        jwt_token = create_access_token(data={"sub": existing.id})
        resp = _clear_and_redirect(state_cookie, f"{settings.FAMILY_WEB_URL}/")
        resp.set_cookie(
            key="access_token",
            value=jwt_token,
            **_cookie_kwargs(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
        )
        return resp

    # —— 首次登录 -> 签发 pending 令牌，跳转注册页补全 ——
    pending = create_oauth_pending_token(
        provider=provider,
        provider_id=provider_id,
        provider_login=info["provider_login"],
        provider_name=info["provider_name"],
        provider_avatar=info["provider_avatar"],
        email=info["email"],
    )
    # github 沿用历史 cookie 名 oauth_pending，gitee 单独命名 oauth_pending_gitee
    pending_cookie = "oauth_pending" if provider == "github" else f"oauth_pending_{provider}"
    q_prefix = "gh" if provider == "github" else "gt"
    register_url = (
        f"{settings.FAMILY_WEB_URL}/register"
        f"?{q_prefix}_login={quote(info['provider_login'])}"
        f"&{q_prefix}_name={quote(info['provider_name'] or '')}"
    )
    resp = _clear_and_redirect(state_cookie, register_url)
    resp.set_cookie(key=pending_cookie, value=pending, **_cookie_kwargs(900))
    return resp


# ===================== 路由（GitHub / Gitee 成对声明） =====================
@router.get("/oauth/github/config")
def github_config() -> dict:
    return {"enabled": _provider_enabled("github")}


@router.get("/oauth/github/enabled")
def github_enabled() -> dict:
    """兼容别名：/config 与 /enabled 行为一致"""
    return {"enabled": _provider_enabled("github")}


@router.get("/oauth/github/authorize")
async def github_authorize() -> RedirectResponse:
    return await _authorize("github")


@router.get("/oauth/github/callback")
async def github_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    request: Request = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    return await _callback("github", code, state, request, db)


@router.get("/oauth/gitee/config")
def gitee_config() -> dict:
    return {"enabled": _provider_enabled("gitee")}


@router.get("/oauth/gitee/enabled")
def gitee_enabled() -> dict:
    return {"enabled": _provider_enabled("gitee")}


@router.get("/oauth/gitee/authorize")
async def gitee_authorize() -> RedirectResponse:
    return await _authorize("gitee")


@router.get("/oauth/gitee/callback")
async def gitee_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    request: Request = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    return await _callback("gitee", code, state, request, db)
