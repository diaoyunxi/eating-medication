# -*- coding: utf-8 -*-
"""TOTP 第二因子端点。

登录流程：手机号+密码 → 若已开启 mfa_enabled，返回 mfa_required + mfa_token，
前端再调用 /auth/totp/verify 校验动态码后签发正式 JWT。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import create_access_token, create_mfa_token, verify_mfa_token
from app.core.crypto import encrypt_text, decrypt_text
from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.auth import TokenResp
from app.services import mfa_service

router = APIRouter(tags=["auth", "mfa"])


class TOTPCodeIn(BaseModel):
    code: str


class TOTPSetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class BackupCodesOut(BaseModel):
    backup_codes: list


class TOTPVerifyIn(BaseModel):
    mfa_token: str
    code: str


@router.post("/totp/setup", response_model=TOTPSetupOut)
def totp_setup(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成 TOTP 密钥并暂存（加密，未启用）；返回供 Authenticator 扫码的 URI 与二维码。
    """
    if current_user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP 第二因子已开启")
    secret = mfa_service.generate_totp_secret()
    account = current_user.phone or current_user.username or str(current_user.id)
    uri = mfa_service.totp_provisioning_uri(secret, account)
    qr_svg = mfa_service.generate_totp_qr_svg(uri)
    current_user.totp_secret = encrypt_text(secret)
    db.add(current_user)
    db.commit()
    return TOTPSetupOut(secret=secret, otpauth_uri=uri, qr_svg=qr_svg)


@router.post("/totp/enable", response_model=BackupCodesOut)
def totp_enable(
    in_: TOTPCodeIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """校验动态码后正式启用 TOTP，返回一次性备用恢复码（请妥善保存）。"""
    if current_user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP 第二因子已开启")
    if not current_user.totp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先调用 /totp/setup 生成密钥")
    secret = decrypt_text(current_user.totp_secret)
    if not mfa_service.verify_totp_code(secret, in_.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="动态验证码错误")
    codes = mfa_service.generate_backup_codes()
    current_user.mfa_enabled = True
    current_user.backup_codes = mfa_service.hash_backup_codes(codes)
    db.add(current_user)
    db.commit()
    return BackupCodesOut(backup_codes=codes)


@router.post("/totp/disable")
def totp_disable(
    in_: TOTPCodeIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """关闭 TOTP（需提供动态码或备用码以确认身份）。"""
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP 第二因子未开启")
    secret = decrypt_text(current_user.totp_secret) if current_user.totp_secret else None
    ok = (secret and mfa_service.verify_totp_code(secret, in_.code)) or mfa_service.verify_backup_code(
        current_user.backup_codes, in_.code
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码或备用码错误")
    current_user.mfa_enabled = False
    current_user.totp_secret = None
    current_user.backup_codes = None
    db.add(current_user)
    db.commit()
    return {"success": True}


@router.post("/totp/verify", response_model=TokenResp)
def totp_verify(in_: TOTPVerifyIn, db: Session = Depends(get_db)):
    """MFA 第二步：校验动态码或备用码，成功签发正式 JWT。"""
    user_id = verify_mfa_token(in_.mfa_token)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA 令牌无效或已过期")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    secret = decrypt_text(user.totp_secret) if user.totp_secret else None
    ok = (secret and mfa_service.verify_totp_code(secret, in_.code)) or mfa_service.verify_backup_code(
        user.backup_codes, in_.code
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="动态验证码或备用码错误")
    # 若使用备用码，则消费（一次性）
    if user.backup_codes and mfa_service.verify_backup_code(user.backup_codes, in_.code):
        user.backup_codes = mfa_service.consume_backup_code(user.backup_codes, in_.code)
        db.add(user)
        db.commit()
    return {"access_token": create_access_token({"sub": user.id}), "token_type": "bearer"}
