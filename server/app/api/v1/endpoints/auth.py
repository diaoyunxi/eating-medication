# -*- coding: utf-8 -*-
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.dependencies import get_db
from app.core.security import verify_oauth_pending_token
from app.schemas.auth import RegisterReq, LoginReq, TokenResp
from app.services.auth_service import AuthService
# L8：注册端点限流
from app.utils.rate_limit import check_rate_limit
from app.utils.request_utils import get_client_ip
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])

# L8：注册限流——每分钟每 IP 最多 5 次注册
_REGISTER_RATE_LIMIT = 5
# 登录限流——每分钟每 IP 最多 10 次登录
_LOGIN_RATE_LIMIT = 10


def verify_turnstile(token: str) -> bool:
    """调用 Cloudflare Turnstile siteverify API 验证人机验证令牌

    :param token: 前端提交的 cf-turnstile-response 令牌
    :return: 验证通过返回 True；未配置 Secret Key 时跳过校验返回 True（开发兼容）
    :raises: 不抛异常，网络异常时返回 False 拒绝请求，避免绕过验证
    """
    secret_key = settings.TURNSTILE_SECRET_KEY
    # 安全修复（中危4）：生产环境必须配置 Turnstile
    if not secret_key:
        if not settings.DEBUG:
            # 生产环境未配置 Turnstile，拒绝请求
            logger.error("生产环境未配置 TURNSTILE_SECRET_KEY，拒绝认证请求")
            return False
        # 开发环境跳过校验
        return True
    if not token:
        return False
    try:
        resp = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret_key, "response": token},
            timeout=10.0,
        )
        result = resp.json()
        return bool(result.get("success", False))
    except Exception:
        # 网络异常等情况下拒绝请求，避免绕过验证
        return False


@router.post("/register", response_model=TokenResp, status_code=status.HTTP_201_CREATED)
def register(
    req: RegisterReq,
    request: Request,
    db: Session = Depends(get_db),
):
    """用户注册（老人或家属，L8：基于 IP 限流 + Turnstile 人机验证）

    GitHub OAuth 补全注册：携带有效 oauth_token 时跳过 Turnstile 人机验证（第三方身份已背书）。
    """
    # OAuth 补全注册：携带有效 oauth_token 时跳过 Turnstile 人机验证
    oauth_pending = None
    if req.oauth_token:
        oauth_pending = verify_oauth_pending_token(req.oauth_token)
        if not oauth_pending:
            raise HTTPException(status_code=400, detail="OAuth 身份令牌无效或已过期，请重新发起 GitHub 登录")
    else:
        if not verify_turnstile(req.cf_turnstile_token):
            raise HTTPException(status_code=400, detail="人机验证失败，请重试")
    # L8：限流（安全修复中危5：使用真实客户端 IP）
    client_ip = get_client_ip(request)
    if not check_rate_limit(f"register:{client_ip}", _REGISTER_RATE_LIMIT):
        raise HTTPException(status_code=429, detail="注册请求过于频繁，请稍后再试")

    try:
        token = AuthService.register(db, req, oauth_pending=oauth_pending)
        return TokenResp(access_token=token, token_type="bearer")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/login", response_model=TokenResp)
def login(req: LoginReq, request: Request, db: Session = Depends(get_db)):
    """用户登录（Turnstile 人机验证 + 限流）"""
    # Turnstile 人机验证
    if not verify_turnstile(req.cf_turnstile_token):
        raise HTTPException(status_code=400, detail="人机验证失败，请重试")
    # 限流（安全修复中危5：使用真实客户端 IP）
    client_ip = get_client_ip(request)
    if not check_rate_limit(f"login:{client_ip}", _LOGIN_RATE_LIMIT):
        raise HTTPException(status_code=429, detail="登录请求过于频繁，请稍后再试")
    token = AuthService.login(db, req.username, req.password)
    if token is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return TokenResp(access_token=token, token_type="bearer")
