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
from fastapi_oauth20.errors import AccessTokenError, GetUserInfoError

from app.core.dependencies import get_db
from app.core.config import settings
from app.core.security import (
    create_oauth_state_token,
    verify_oauth_state_token,
    create_oauth_pending_token,
    create_access_token,
    decode_token,
)
from app.services.auth_service import AuthService, _mask_email
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ===================== 延长 httpx 超时（应对慢速出站链路） =====================
# fastapi-oauth20 v0.0.3 在 get_access_token / get_userinfo 中使用 httpx.AsyncClient()
# 而未指定超时，走 httpx 默认 5s 超时。服务器到 GitHub/Gitee 的出站链路较慢时，
# code 换 token 或拉用户信息会触发 httpx.ReadTimeout（见服务端 nohup.out 中 github
# callback 的 ReadTimeout: connect_tcp timeout=5.0）。下列混入/子类在构造 httpx 客户端时
# 显式注入更宽松的超时，其余请求参数、鉴权、错误处理逻辑与上游基类、GitHub/Gitee
# 子类完全一致（仅新增 timeout 参数）。
OAUTH_HTTP_TIMEOUT = httpx.Timeout(connect=15, read=30, write=15, pool=15)


class _OAuth20TimeoutMixin:
    """为 OAuth20Base.get_access_token 注入更长 httpx 超时的混入类。

    仅将 ``httpx.AsyncClient(...)`` 替换为携带 ``timeout=OAUTH_HTTP_TIMEOUT`` 的客户端，
    请求体、鉴权、错误处理均与上游 OAuth20Base.get_access_token 保持一致。
    """

    async def get_access_token(
        self, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict[str, Any]:
        data = {
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        auth = None
        if not self.token_endpoint_basic_auth:
            data.update({"client_id": self.client_id, "client_secret": self.client_secret})
        else:
            auth = httpx.BasicAuth(self.client_id, self.client_secret)
        if code_verifier:
            data.update({"code_verifier": code_verifier})
        async with httpx.AsyncClient(auth=auth, timeout=OAUTH_HTTP_TIMEOUT) as client:
            response = await client.post(
                self.access_token_endpoint,
                data=data,
                headers=self.request_headers,
            )
            self.raise_httpx_oauth20_errors(response)
            result = self.get_json_result(response, err_class=AccessTokenError)
            return result


class GitHubOAuth20Timeout(_OAuth20TimeoutMixin, GitHubOAuth20):
    """GitHub 客户端：加长超时，并保留上游 get_userinfo 的邮箱回退逻辑。"""

    async def get_userinfo(self, access_token: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(headers=headers, timeout=OAUTH_HTTP_TIMEOUT) as client:
            response = await client.get(self.userinfo_endpoint)
            self.raise_httpx_oauth20_errors(response)
            result = self.get_json_result(response, err_class=GetUserInfoError)
            email = result.get("email")
            if email is None:
                response = await client.get(f"{self.userinfo_endpoint}/emails")
                self.raise_httpx_oauth20_errors(response)
                emails = self.get_json_result(response, err_class=GetUserInfoError)
                email = next(
                    (e["email"] for e in emails if e.get("primary")),
                    emails[0]["email"],
                )
                result["email"] = email
            return result


class GiteeOAuth20Compat(_OAuth20TimeoutMixin, GiteeOAuth20):
    """Gitee 兼容子类：加长超时，并保留 ``token <token>`` 鉴权头。

    fastapi-oauth20 基类 get_userinfo 默认使用 ``Authorization: Bearer <token>``，
    而 Gitee 开放 API 实际支持的是 ``Authorization: token <token>``（历史约定）。
    覆盖 get_userinfo 以保留原有可用的鉴权头，避免重构后 Gitee 拉取用户信息失败。
    """

    async def get_userinfo(self, access_token: str) -> dict[str, Any]:
        headers = {"Authorization": f"token {access_token}"}
        async with httpx.AsyncClient(headers=headers, timeout=OAUTH_HTTP_TIMEOUT) as client:
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
        gh_client = GitHubOAuth20Timeout(
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
            # GitHub 的 /user 接口在用户将邮箱设为「私有」时返回 null，
            # 故显式指向 /user/emails（需 user:email scope，已在上方申请），
            # 由 _fetch_email 回退拉取（含私有且已验证的邮箱），与 Gitee 行为一致。
            "emails_api": "https://api.github.com/user/emails",
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
    headers = {
        "Accept": "application/json",
        "Authorization": f"{auth_header} {access_token}",
        # GitHub API 要求请求必须携带 User-Agent，否则返回 403
        "User-Agent": "eating-medication",
    }
    try:
        resp = httpx.get(emails_api, headers=headers, timeout=OAUTH_HTTP_TIMEOUT)
        emails = resp.json()
        if isinstance(emails, list) and emails:
            # 优先取「主邮箱且已验证」，否则取列表首个
            primary = next(
                (e for e in emails if e.get("primary") and e.get("verified")),
                emails[0],
            )
            return primary.get("email")
    except Exception:
        # 不记录异常细节（可能含第三方接口/令牌相关信息），仅记录失败事实
        logger.warning(f"获取 {emails_api} 邮箱失败")
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
async def _authorize(
    provider: str, error_url: Optional[str] = None
) -> RedirectResponse:
    """发起第三方授权：设 state cookie 并 302 跳转授权页

    :param provider: OAuth 提供商名称（github / gitee）
    :param error_url: 网络异常时的跳转地址。未指定时默认跳转登录页并携带
                      ``?error=oauth_timeout``。绑定模式应传入设置页地址。
    """
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
    try:
        auth_url = await cfg["client"].get_authorization_url(
            redirect_uri=cfg["callback_url"],
            state=state,
            scope=cfg["scope"],
            **extra,
        )
    except httpx.HTTPError as e:
        # 网络超时/连接失败（如服务器访问 GitHub 受限）：不崩溃，优雅跳转
        logger.error(f"{provider} OAuth 构造授权地址网络异常: {type(e).__name__}: {e}")
        target = error_url or f"{settings.FAMILY_WEB_URL}/login?error=oauth_timeout"
        return RedirectResponse(url=target, status_code=302)
    except Exception as e:
        logger.error(f"{provider} OAuth 构造授权地址异常: {type(e).__name__}: {e}")
        target = error_url or f"{settings.FAMILY_WEB_URL}/login?error=oauth_fail"
        return RedirectResponse(url=target, status_code=302)

    resp = RedirectResponse(url=auth_url, status_code=302)
    resp.set_cookie(
        key=f"oauth_state_{provider}",
        value=state_token,
        **_cookie_kwargs(600),
    )
    return resp


async def _bind_authorize(provider: str, request: Request) -> RedirectResponse:
    """绑定模式授权入口：验证 JWT 后设 oauth_bind_jwt cookie，再走正常 authorize

    流程：
    1. 从 query 参数 token 取用户 JWT（由 family_monitor 转发）
    2. 验证 JWT 有效性（decode_token）
    3. 设 oauth_bind_jwt cookie（10 分钟有效）
    4. 调用 _authorize 跳转第三方授权页
    5. 将 oauth_bind_jwt cookie 附加到 _authorize 的响应上
    """
    cfg = _OAUTH.get(provider)
    family_settings = f"{settings.FAMILY_WEB_URL}/settings"
    if cfg is None:
        return RedirectResponse(url=f"{family_settings}?error=oauth_not_configured", status_code=302)

    token = request.query_params.get("token", "")
    if not token:
        return RedirectResponse(url=f"{family_settings}?error=no_token", status_code=302)

    # 验证 JWT
    try:
        payload = decode_token(token)
        sub = payload.get("sub")
        if sub is None:
            raise ValueError("JWT 缺少 sub")
    except Exception as e:
        logger.warning(f"OAuth 绑定模式 JWT 验证失败: {e}")
        return RedirectResponse(url=f"{family_settings}?error=invalid_token", status_code=302)

    # 走正常 authorize 流程（绑定模式异常跳转设置页而非登录页）
    resp = await _authorize(
        provider, error_url=f"{family_settings}?error=oauth_timeout"
    )
    # 附加 bind cookie（短生命周期，10 分钟）
    # 注意：若 _authorize 因网络异常返回错误跳转，此 cookie 仍会被设置，
    # 但不会造成安全问题（10 分钟后自动过期，且不会被回调流程使用）。
    resp.set_cookie(
        key="oauth_bind_jwt",
        value=token,
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
    except httpx.HTTPError as e:
        # 网络超时/连接失败（如服务器访问 GitHub 受限）：不崩溃，优雅跳转登录页
        logger.error(f"{provider} OAuth code 换 token 网络异常: {type(e).__name__}: {e}")
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_timeout")

    access_token = token_data.get("access_token")
    if not access_token:
        logger.error(f"{provider} 换 token 返回数据缺少 access_token: {token_data}")
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_token")

    # —— 拉取用户信息（委托客户端 get_userinfo）——
    try:
        raw = await cfg["client"].get_userinfo(access_token)
        info = await _normalize_user(cfg, raw, access_token)
    except httpx.HTTPError as e:
        logger.error(f"{provider} OAuth 拉取用户信息网络异常: {type(e).__name__}: {e}")
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_timeout")
    except Exception as e:
        logger.error(f"{provider} OAuth 拉取用户信息异常: {e}")
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_fail")

    provider_id = info["provider_id"]
    if not provider_id:
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_user")

    # —— 绑定模式：已登录用户在设置页点击"绑定第三方" ——
    # 通过 oauth_bind_jwt cookie 携带用户 JWT，回调时检测到该 cookie 则走绑定流程
    bind_jwt = request.cookies.get("oauth_bind_jwt")
    if bind_jwt:
        family_settings = f"{settings.FAMILY_WEB_URL}/settings"
        try:
            payload = decode_token(bind_jwt)
            bind_user_id = payload.get("sub")
            if bind_user_id is None:
                raise ValueError("JWT 缺少 sub")
            bind_user = db.query(User).filter(User.id == int(bind_user_id)).first()
            if not bind_user:
                raise ValueError("用户不存在")
            # 检查该第三方账号是否已绑定其他用户
            already_bound = AuthService.get_by_provider(db, provider, provider_id)
            if already_bound and already_bound.id != bind_user.id:
                logger.warning(
                    f"OAuth({provider}) 绑定失败: provider_id={provider_id} "
                    f"已绑定到其他用户 {already_bound.username}"
                )
                resp = _clear_and_redirect(state_cookie, f"{family_settings}?error=already_bound")
                resp.delete_cookie(key="oauth_bind_jwt", path="/")
                return resp
            if already_bound and already_bound.id == bind_user.id:
                # 已绑定到当前用户，直接返回
                resp = _clear_and_redirect(state_cookie, f"{family_settings}?info=already_bound")
                resp.delete_cookie(key="oauth_bind_jwt", path="/")
                return resp
            # 绑定第三方到当前用户
            AuthService._bind_provider(bind_user, provider, provider_id)
            db.commit()
            logger.info(
                f"OAuth({provider}) 绑定成功: user={bind_user.username}, "
                f"email={_mask_email(info.get('email') or '')}"
            )
            resp = _clear_and_redirect(state_cookie, f"{family_settings}")
            resp.delete_cookie(key="oauth_bind_jwt", path="/")
            return resp
        except Exception as e:
            logger.error(f"OAuth 绑定模式失败: {e}")
            resp = _clear_and_redirect(state_cookie, f"{family_settings}?error=bind_fail")
            resp.delete_cookie(key="oauth_bind_jwt", path="/")
            return resp

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

    # —— 首次登录 -> 自动注册（不再跳转注册页补全手机号/密码） ——
    # 邮箱冲突检测：若 OAuth 邮箱已存在对应用户（且未绑定本 provider），合并绑定后直接登录
    oauth_email = info["email"]
    if oauth_email:
        email_user = db.query(User).filter(
            User.email == oauth_email.strip().lower()
        ).first()
        if email_user and not (
            (provider == "github" and email_user.github_id) or
            (provider == "gitee" and email_user.gitee_id)
        ):
            # 合并绑定到现有账号
            AuthService._bind_provider(email_user, provider, provider_id)
            db.commit()
            logger.info(
                f"OAuth({provider}) 邮箱 {_mask_email(oauth_email)} 已合并绑定至现有账号 {email_user.username}"
            )
            jwt_token = create_access_token(data={"sub": email_user.id})
            resp = _clear_and_redirect(state_cookie, f"{settings.FAMILY_WEB_URL}/")
            resp.set_cookie(
                key="access_token",
                value=jwt_token,
                **_cookie_kwargs(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
            )
            return resp

    # 无邮箱冲突 -> 直接创建新账号
    try:
        user = AuthService.auto_register_oauth(
            db,
            provider=provider,
            provider_id=provider_id,
            provider_name=info["provider_name"],
            email=oauth_email,
        )
        jwt_token = create_access_token(data={"sub": user.id})
        resp = _clear_and_redirect(state_cookie, f"{settings.FAMILY_WEB_URL}/")
        resp.set_cookie(
            key="access_token",
            value=jwt_token,
            **_cookie_kwargs(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
        )
        return resp
    except Exception as e:
        logger.error(f"OAuth 自动注册失败: {e}")
        return _clear_and_redirect(state_cookie, f"{family_login}?error=oauth_fail")


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


@router.get("/oauth/github/bind")
async def github_bind(request: Request) -> RedirectResponse:
    """GitHub 绑定入口（已登录用户在设置页点击"绑定 GitHub"）

    接收 query 参数 token（用户 JWT），验证后设 oauth_bind_jwt cookie，
    然后走正常 authorize 流程；回调时检测到该 cookie 则绑定到当前用户。
    """
    return await _bind_authorize("github", request)


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


@router.get("/oauth/gitee/bind")
async def gitee_bind(request: Request) -> RedirectResponse:
    """Gitee 绑定入口（已登录用户在设置页点击"绑定 Gitee"）"""
    return await _bind_authorize("gitee", request)


@router.get("/oauth/gitee/callback")
async def gitee_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    request: Request = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    return await _callback("gitee", code, state, request, db)
