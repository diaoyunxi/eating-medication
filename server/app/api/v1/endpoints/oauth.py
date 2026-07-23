# -*- coding: utf-8 -*-
"""OAuth 第三方登录（GitHub / Gitee 通用 provider 框架）

providers 互补说明：
- github：authorization_code 换取 token；用户信息取 https://api.github.com/user（scope=read:user）
- gitee ：authorization_code 换取 token；用户信息取 https://gitee.com/api/v5/user（scope=user_info emails），
          emails 需额外调用 https://gitee.com/api/v5/emails（授权 emails 权限）

两种平台流程完全一致：authorize 设 state cookie 并 302 到对应授权页 -> 用户同意后
回调本服务的 callback -> 换 token -> 拉用户信息 -> 已绑定则直接签发 JWT 登录，
未绑定则签发短期 pending 令牌（写入 HttpOnly cookie）并跳转 family_monitor 注册页补全。
"""
import httpx
import secrets
import logging
from urllib.parse import urlencode, quote
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

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

# ===================== OAuth provider 配置表 =====================
# 通过 provider key 选择，新增平台只需在此扩展，无需复制整段逻辑。
_OAUTH_PROVIDERS = {
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "user_api": "https://api.github.com/user",
        "emails_api": None,                       # GitHub 的 user 接口已含 public email
        "scope": "read:user",
        "auth_header": "Bearer",                  # 请求用户接口时的 Authorization 前缀
        "allow_signup": True,
        "id_field": "id",
        "login_field": "login",
        "name_field": "name",
        "avatar_field": "avatar_url",
        "email_field": "email",
        "client_id": settings.GITHUB_CLIENT_ID,
        "client_secret": settings.GITHUB_CLIENT_SECRET,
        "callback_url": settings.GITHUB_OAUTH_CALLBACK_URL,
        "extra_token_params": {},
    },
    "gitee": {
        "authorize_url": "https://gitee.com/oauth/authorize",
        "token_url": "https://gitee.com/oauth/token",
        "user_api": "https://gitee.com/api/v5/user",
        "emails_api": "https://gitee.com/api/v5/emails",  # 需 emails 权限
        "scope": "user_info emails",
        "auth_header": "token",                   # Gitee 使用 "token <access_token>" 而非 Bearer
        "allow_signup": False,
        "id_field": "id",
        "login_field": "login",
        "name_field": "name",
        "avatar_field": "avatar_url",
        "email_field": "email",
        "client_id": settings.GITEE_CLIENT_ID,
        "client_secret": settings.GITEE_CLIENT_SECRET,
        "callback_url": settings.GITEE_OAUTH_CALLBACK_URL,
        "extra_token_params": {"grant_type": "authorization_code"},
    },
}


def _provider_enabled(provider: str) -> bool:
    """provider 是否已配置（client_id 与 client_secret 同时存在）"""
    cfg = _OAUTH_PROVIDERS[provider]
    return bool(cfg["client_id"] and cfg["client_secret"])


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


def _fetch_provider_user(cfg: dict, access_token: str) -> dict:
    """拉取第三方用户信息，统一返回 provider_id / login / name / avatar / email"""
    auth_header = f'{cfg["auth_header"]} {access_token}'
    headers = {"Accept": "application/json", "Authorization": auth_header}
    user_resp = httpx.get(cfg["user_api"], headers=headers, timeout=10)
    u = user_resp.json()

    email = u.get(cfg["email_field"])
    if email is None and cfg.get("emails_api"):
        try:
            eresp = httpx.get(cfg["emails_api"], headers=headers, timeout=10)
            emails = eresp.json()
            if isinstance(emails, list) and emails:
                # 优先取「主邮箱且已验证」，否则取列表首个
                primary = next(
                    (e for e in emails if e.get("primary") and e.get("verified")),
                    emails[0],
                )
                email = primary.get("email")
        except Exception as e:
            logger.warning(f"获取 {cfg['emails_api']} 邮箱失败: {e}")

    return {
        "provider_id": u.get(cfg["id_field"]),
        "provider_login": u.get(cfg["login_field"]) or "",
        "provider_name": u.get(cfg["name_field"]) or u.get(cfg["login_field"]) or "",
        "provider_avatar": u.get(cfg["avatar_field"]),
        "email": email,
    }


# ===================== 通用流程实现 =====================
def _authorize(provider: str) -> RedirectResponse:
    """发起第三方授权：设 state cookie 并 302 跳转授权页"""
    cfg = _OAUTH_PROVIDERS[provider]
    if not cfg["client_id"]:
        return JSONResponse(
            status_code=400,
            content={"detail": f"{provider} OAuth 未配置（缺少 CLIENT_ID）"},
        )

    state = secrets.token_urlsafe(24)
    state_token = create_oauth_state_token(state)

    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["callback_url"],
        "scope": cfg["scope"],
        "state": state,
    }
    if cfg["allow_signup"]:
        params["allow_signup"] = "true"

    url = f'{cfg["authorize_url"]}?{urlencode(params)}'
    resp = RedirectResponse(url=url, status_code=302)
    resp.set_cookie(
        key=f"oauth_state_{provider}",
        value=state_token,
        **_cookie_kwargs(600),
    )
    return resp


def _callback(provider: str, code: str, state: str, request: Request, db: Session) -> RedirectResponse:
    """第三方授权回跳：校验 state -> 换 token -> 拉用户信息 -> 登录或跳注册"""
    cfg = _OAUTH_PROVIDERS[provider]
    state_cookie = f"oauth_state_{provider}"
    family_login = f"{settings.FAMILY_WEB_URL}/login"

    # —— state 校验（防 CSRF）——
    state_token = request.cookies.get(state_cookie)
    expected_state = verify_oauth_state_token(state_token) if state_token else None
    if not state or not expected_state or state != expected_state:
        logger.warning(f"{provider} OAuth state 校验失败")
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_state")
    if not code:
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_code")

    # —— 换取 access_token ——
    try:
        token_data = dict(cfg["extra_token_params"])
        token_data.update({
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "code": code,
            "redirect_uri": cfg["callback_url"],
        })
        token_resp = httpx.post(
            cfg["token_url"],
            data=token_data,
            headers={"Accept": "application/json"},
            timeout=10,
        )
        token_json = token_resp.json()
        access_token = token_json.get("access_token")
        if not access_token:
            logger.error(f"{provider} 换 token 失败: {token_json}")
            return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_token")
    except Exception as e:
        logger.error(f"{provider} OAuth 换取 access_token 异常: {e}")
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_fail")

    # —— 拉取用户信息 ——
    try:
        info = _fetch_provider_user(cfg, access_token)
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
def github_authorize() -> RedirectResponse:
    return _authorize("github")


@router.get("/oauth/github/callback")
def github_callback(
    code: str = None,
    state: str = None,
    request: Request = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    return _callback("github", code, state, request, db)


@router.get("/oauth/gitee/config")
def gitee_config() -> dict:
    return {"enabled": _provider_enabled("gitee")}


@router.get("/oauth/gitee/enabled")
def gitee_enabled() -> dict:
    return {"enabled": _provider_enabled("gitee")}


@router.get("/oauth/gitee/authorize")
def gitee_authorize() -> RedirectResponse:
    return _authorize("gitee")


@router.get("/oauth/gitee/callback")
def gitee_callback(
    code: str = None,
    state: str = None,
    request: Request = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    return _callback("gitee", code, state, request, db)
