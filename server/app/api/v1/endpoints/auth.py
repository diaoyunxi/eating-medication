# -*- coding: utf-8 -*-
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.dependencies import get_db
from app.core.security import verify_oauth_pending_token
from app.schemas.auth import (
    RegisterReq, LoginReq, TokenResp, EmailSendCodeReq, EmailCodeLoginReq,
    BindPhoneReq, BindEmailReq, BindEmailSendCodeReq,
)
from app.services.auth_service import AuthService
from app.core.dependencies import get_current_user, get_current_user_optional, get_db
from app.models.user import User
from app.utils.rate_limit import check_rate_limit
from app.utils.request_utils import get_client_ip
from app.utils import email_code as email_code_store
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])

# 注册限流——每分钟每 IP 最多 5 次注册
_REGISTER_RATE_LIMIT = 5
# 登录限流——每分钟每 IP 最多 10 次登录
_LOGIN_RATE_LIMIT = 10
# 邮箱验证码发送限流——每分钟每 IP 最多 5 次
_EMAIL_SEND_RATE_LIMIT = 5
# 邮箱验证码登录限流——每分钟每 IP 最多 10 次
_EMAIL_LOGIN_RATE_LIMIT = 10


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

@router.post("/login")
def login(req: LoginReq, request: Request, db: Session = Depends(get_db)):
    """用户登录（Turnstile 人机验证 + 限流）

    已开启 TOTP 第二因子的账号：密码校验通过后返回 {mfa_required: true, mfa_token}，
    前端再调用 /auth/totp/verify 校验动态码获取正式 JWT。
    """
    # Turnstile 人机验证
    if not verify_turnstile(req.cf_turnstile_token):
        raise HTTPException(status_code=400, detail="人机验证失败，请重试")
    # 限流（使用真实客户端 IP）
    client_ip = get_client_ip(request)
    if not check_rate_limit(f"login:{client_ip}", _LOGIN_RATE_LIMIT):
        raise HTTPException(status_code=429, detail="登录请求过于频繁，请稍后再试")
    result = AuthService.login(db, req.phone, req.password)
    if result is None:
        raise HTTPException(status_code=401, detail="手机号或密码错误")
    if result.get("mfa_required"):
        return {"mfa_required": True, "mfa_token": result["mfa_token"]}
    return TokenResp(access_token=result["access_token"], token_type="bearer")


@router.post("/email/send-code")
def email_send_code(req: EmailSendCodeReq, request: Request, db: Session = Depends(get_db)):
    """邮箱验证码 - 发送验证码（Turnstile 人机验证 + 限流 + 安全策略）

    无论邮箱是否已注册都发送验证码（不泄露账号存在性）；具体登录/注册在 /email/code-login 处理。
    """
    # Turnstile 人机验证
    if not verify_turnstile(req.cf_turnstile_token):
        raise HTTPException(status_code=400, detail="人机验证失败，请重试")
    # 限流（使用真实客户端 IP）
    client_ip = get_client_ip(request)
    if not check_rate_limit(f"email_send:{client_ip}", _EMAIL_SEND_RATE_LIMIT):
        raise HTTPException(status_code=429, detail="验证码请求过于频繁，请稍后再试")

    ok, msg = email_code_store.send_code(req.email)
    if not ok:
        # 邮件服务未配置 / 发送失败 / 频率限制等：内部细节仅记录日志，不向客户端泄露
        logger.warning(f"发送邮箱验证码失败: {msg}")
        raise HTTPException(status_code=400, detail="验证码发送失败，请稍后重试")
    return {"success": True, "message": "验证码已发送，请查收邮箱"}


@router.post("/email/code-login")
def email_code_login(req: EmailCodeLoginReq, request: Request, db: Session = Depends(get_db)):
    """邮箱验证码 - 登录 / 自动注册（Turnstile 人机验证 + 限流）

    - 验证码校验通过但邮箱未注册：自动创建账号并登录。
    - 验证码错误或过期：返回 400（不区分是否已注册，避免泄露账号存在性）。
    - 用户已开启 TOTP 第二因子：返回 MFA 挑战令牌，前端再调用 /auth/totp/verify。
    """
    # Turnstile 人机验证
    if not verify_turnstile(req.cf_turnstile_token):
        raise HTTPException(status_code=400, detail="人机验证失败，请重试")
    # 限流（使用真实客户端 IP）
    client_ip = get_client_ip(request)
    if not check_rate_limit(f"email_login:{client_ip}", _EMAIL_LOGIN_RATE_LIMIT):
        raise HTTPException(status_code=429, detail="登录请求过于频繁，请稍后再试")

    # 先校验验证码（不泄露账号存在性）；验证码无效不进入账号逻辑
    if not email_code_store.verify_code(req.email, req.code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期，请重新获取")

    try:
        token_data = AuthService.login_or_register_by_email(db, req.email)
        if token_data.get("mfa_required"):
            return {"mfa_required": True, "mfa_token": token_data["mfa_token"]}
        return TokenResp(access_token=token_data["access_token"], token_type="bearer")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== 登录方式管理（绑定/解绑/查询） ====================

@router.get("/login-methods")
def get_login_methods(
    current_user: User = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """查询登录方式状态（公开，登录前即可访问，BUG-C07 修复）

    - 未携带/无效 token：返回系统级各登录方式的「启用状态」
      （phone/email 始终启用；github/gitee 取决于 OAuth 是否配置），供登录页展示入口。
    - 已登录：返回当前用户各登录方式的「绑定状态」与脱敏值。
    """
    return AuthService.get_login_methods(db, current_user)


@router.post("/bind-phone")
def bind_phone(
    req: BindPhoneReq,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """绑定手机号（需同时设置密码，绑定后可用手机号+密码登录）"""
    try:
        AuthService.bind_phone(db, current_user, req.phone, req.password)
        return {"success": True, "message": "手机号绑定成功"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bind-email/send-code")
def bind_email_send_code(
    req: BindEmailSendCodeReq,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """绑定邮箱 - 发送验证码（需登录）

    与 /email/send-code 不同：此端点用于已登录用户绑定新邮箱，
    会先校验该邮箱是否已被其他账号占用。
    """
    email = req.email.strip().lower()
    # 校验邮箱是否已被其他用户占用
    existing = db.query(User).filter(User.email == email).first()
    if existing and existing.id != current_user.id:
        raise HTTPException(status_code=400, detail="该邮箱已被其他账号绑定")
    if current_user.email:
        raise HTTPException(status_code=400, detail="当前已绑定邮箱，请先解绑")

    client_ip = get_client_ip(request)
    if not check_rate_limit(f"bind_email_send:{client_ip}", _EMAIL_SEND_RATE_LIMIT):
        raise HTTPException(status_code=429, detail="验证码请求过于频繁，请稍后再试")

    ok, msg = email_code_store.send_code(email)
    if not ok:
        logger.warning(f"绑定邮箱发送验证码失败: {msg}")
        raise HTTPException(status_code=400, detail="验证码发送失败，请稍后重试")
    return {"success": True, "message": "验证码已发送，请查收邮箱"}


@router.post("/bind-email")
def bind_email(
    req: BindEmailReq,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """绑定邮箱（需先通过验证码校验）"""
    # 校验验证码
    if not email_code_store.verify_code(req.email, req.code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期，请重新获取")
    try:
        AuthService.bind_email(db, current_user, req.email)
        return {"success": True, "message": "邮箱绑定成功"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/unbind-phone")
def unbind_phone(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """解绑手机号（至少保留一种登录方式）"""
    try:
        AuthService.unbind_phone(db, current_user)
        return {"success": True, "message": "手机号已解绑"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/unbind-email")
def unbind_email(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """解绑邮箱（至少保留一种登录方式）"""
    try:
        AuthService.unbind_email(db, current_user)
        return {"success": True, "message": "邮箱已解绑"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/unbind-oauth/{provider}")
def unbind_oauth(
    provider: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """解绑第三方 OAuth（至少保留一种登录方式）

    :param provider: "github" 或 "gitee"
    """
    if provider not in ("github", "gitee"):
        raise HTTPException(status_code=400, detail="不支持的 OAuth 平台")
    try:
        AuthService.unbind_oauth(db, current_user, provider)
        return {"success": True, "message": f"{provider} 已解绑"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
