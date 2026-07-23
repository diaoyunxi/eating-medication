# -*- coding: utf-8 -*-
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.dependencies import get_db
from app.core.security import verify_oauth_pending_token
from app.schemas.auth import RegisterReq, LoginReq, TokenResp
from app.services.auth_service import AuthService
from app.utils.rate_limit import check_rate_limit
from app.utils.request_utils import get_client_ip
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])

# 注册限流——每分钟每 IP 最多 5 次注册
_REGISTER_RATE_LIMIT = 5
# 登录限流——每分钟每 IP 最多 10 次登录
_LOGIN_RATE_LIMIT = 10


def verify_turnstile(token: str) -> bool:
    """调用 Cloudflare Turnstile siteverify API 验证人机验证令牌

    :param token: 前端提交的 cf-turnstile-response 令牌
    :return: 验证通过返回 True；未配置 Secret Key 时自动降级返回 True（跳过验证）；
             网络/服务异常时返回 False 以拒绝请求，避免绕过验证
    """
    secret_key = settings.TURNSTILE_SECRET_KEY
    # 未配置 Turnstile：自动降级，跳过人机验证（不影响登录/注册可用性）
    if not secret_key:
        logger.warning(
            "未配置 TURNSTILE_SECRET_KEY，已降级跳过人机验证（登录/注册仍可正常使用）。"
            "如需启用防机器人验证，请在 server/.env 配置 TURNSTILE_SECRET_KEY 后重启。"
        )
        return True
    if not token:
        logger.warning("Turnstile 校验失败：前端未提交 cf-turnstile-response 令牌（请确认前端小组件已加载且用户已完成验证）")
        return False
    try:
        resp = httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret_key, "response": token},
            timeout=10.0,
        )
        result = resp.json()
        success = bool(result.get("success", False))
        if not success:
            # 记录 Cloudflare 返回的错误码，便于排查（如站点密钥与密钥不匹配、令牌过期、域名不符等）
            logger.warning(f"Turnstile 校验未通过: error-codes={result.get('error-codes')}")
        return success
    except Exception:
        # 网络异常等情况下拒绝请求，避免绕过验证
        logger.error("Turnstile 校验异常（无法连接 Cloudflare siteverify），拒绝本次认证请求")
        return False


@router.post("/register", response_model=TokenResp, status_code=status.HTTP_201_CREATED)
def register(
    req: RegisterReq,
    request: Request,
    db: Session = Depends(get_db),
):
    """用户注册（老人或家属，基于 IP 限流 + Turnstile 人机验证）

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
    # 限流（使用真实客户端 IP）
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
    # 限流（使用真实客户端 IP）
    client_ip = get_client_ip(request)
    if not check_rate_limit(f"login:{client_ip}", _LOGIN_RATE_LIMIT):
        raise HTTPException(status_code=429, detail="登录请求过于频繁，请稍后再试")
    token = AuthService.login(db, req.username, req.password)
    if token is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return TokenResp(access_token=token, token_type="bearer")
