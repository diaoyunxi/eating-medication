# -*- coding: utf-8 -*-
"""WebAuthn / Passkey 端点（无用户名 passkey 登录）。

- 登记（绑定）：/webauthn/register/options → /webauthn/register（需登录态）
- 登录：/webauthn/login/options → /webauthn/login（公开，按 credential_id 反查用户）
- 管理：/webauthn/credentials 列表与删除（需登录态）
"""
import json
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.utils.datetime_utils import utcnow
from app.core.dependencies import get_db, get_current_user
from app.models.user import User, WebAuthnCredential
from app.schemas.auth import TokenResp
from app.services import mfa_service

router = APIRouter(tags=["auth", "webauthn"])


class WebAuthnRegisterIn(BaseModel):
    credential: dict
    challenge_token: str
    nickname: str = None


class WebAuthnLoginIn(BaseModel):
    credential: dict
    challenge_token: str


class WebAuthnOptionsOut(BaseModel):
    options: dict
    challenge_token: str

    @classmethod
    def from_json(cls, options_json: str, challenge_token: str):
        return cls(options=json.loads(options_json), challenge_token=challenge_token)


@router.post("/webauthn/register/options", response_model=WebAuthnOptionsOut)
def wa_register_options(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """构造通行密钥登记选项（已排除本用户已有凭证）。"""
    existing = [c.credential_id for c in current_user.webauthn_credentials]
    options_json, challenge_token = mfa_service.build_registration_options(current_user, existing)
    return WebAuthnOptionsOut.from_json(options_json, challenge_token)


@router.post("/webauthn/register")
def wa_register(
    in_: WebAuthnRegisterIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """校验登记响应并保存凭证。"""
    ok, cred_id, pub_key, sign_count = mfa_service.verify_registration(
        in_.credential, in_.challenge_token
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="通行密钥登记校验失败")
    if db.query(WebAuthnCredential).filter(WebAuthnCredential.credential_id == cred_id).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该通行密钥已注册")
    cred = WebAuthnCredential(
        user_id=current_user.id,
        credential_id=cred_id,
        public_key=pub_key,
        sign_count=sign_count,
        nickname=in_.nickname,
    )
    db.add(cred)
    db.commit()
    return {"success": True, "credential_id": cred_id}


@router.post("/webauthn/login/options", response_model=WebAuthnOptionsOut)
def wa_login_options(db: Session = Depends(get_db)):
    """构造无用户名登录断言选项（allow_credentials 留空，依赖 discoverable 凭证）。"""
    options_json, challenge_token = mfa_service.build_authentication_options()
    return WebAuthnOptionsOut.from_json(options_json, challenge_token)


@router.post("/webauthn/login", response_model=TokenResp)
def wa_login(in_: WebAuthnLoginIn, db: Session = Depends(get_db)):
    """校验通行密钥断言，按 credential_id 反查用户并签发 JWT。"""
    raw_id = in_.credential.get("rawId")
    if not raw_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少 rawId")
    cred = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.credential_id == raw_id)
        .first()
    )
    if not cred:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未知的通行密钥")
    ok, new_sign_count = mfa_service.verify_authentication(
        in_.credential, in_.challenge_token, cred.public_key, cred.sign_count
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="通行密钥校验失败")
    cred.sign_count = new_sign_count
    cred.last_used_at = utcnow()
    db.add(cred)
    db.commit()
    return {"access_token": create_access_token({"sub": cred.user_id}), "token_type": "bearer"}


@router.get("/webauthn/credentials")
def wa_list_credentials(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户已登记的通行密钥。"""
    creds = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.user_id == current_user.id)
        .order_by(WebAuthnCredential.created_at.desc())
        .all()
    )
    return [
        {
            "id": c.id,
            "credential_id": c.credential_id,
            "nickname": c.nickname,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
        }
        for c in creds
    ]


@router.delete("/webauthn/credentials/{cred_id}")
def wa_delete_credential(
    cred_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除指定通行密钥。"""
    cred = (
        db.query(WebAuthnCredential)
        .filter(
            WebAuthnCredential.credential_id == cred_id,
            WebAuthnCredential.user_id == current_user.id,
        )
        .first()
    )
    if not cred:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="凭证不存在")
    db.delete(cred)
    db.commit()
    return {"success": True}
