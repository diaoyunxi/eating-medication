# -*- coding: utf-8 -*-
"""MFA（TOTP 第二因子）与 WebAuthn / Passkey 业务逻辑。

设计要点：
- TOTP 作为「密码后的第二因子」：登录时先验证手机号+密码，已开启则再要求动态码。
- WebAuthn 采用无用户名（usernameless）passkey 登录：residentKey=required 的 discoverable
  凭证，登录页直接调起系统选择器，后端按 credential_id 反查用户签发 JWT。
- WebAuthn 挑战（challenge）不落库：签发短期签名令牌（webauthn_challenge）随响应下发，
  客户端回传后校验，避免服务端会话存储（与现有无状态 JWT 架构一致）。
"""
import io
import json
import secrets
import string

import bcrypt
import pyotp
import qrcode
from qrcode.image.svg import SvgPathImage

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import settings
from app.core.security import (
    create_webauthn_challenge_token,
    verify_webauthn_challenge_token,
)


# ==================== TOTP ====================
def generate_totp_secret() -> str:
    """生成新的 TOTP 共享密钥（base32 字符串）"""
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, account: str, issuer: str = "吃饭提醒") -> str:
    """生成 otpauth:// URI，用于 Authenticator 应用扫码绑定"""
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def generate_totp_qr_svg(uri: str) -> str:
    """将 otpauth URI 渲染为 SVG 字符串（无需 Pillow 依赖）"""
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(
        fill_color="black", back_color="white", image_factory=SvgPathImage
    )
    # qrcode 的 SVG 保存以 UTF-8 字节写入，需经 BytesIO 再解码为 str
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def verify_totp_code(secret: str, code: str) -> bool:
    """校验 6 位动态码（允许 ±30s 漂移窗口）"""
    if not secret or not code:
        return False
    try:
        cleaned = code.strip().replace(" ", "")
        return pyotp.TOTP(secret).verify(cleaned, valid_window=1)
    except Exception:
        return False


def generate_backup_codes(n: int = 8) -> list:
    """生成备用恢复码（纯数字，便于手动输入）"""
    return ["".join(secrets.choice(string.digits) for _ in range(6)) for _ in range(n)]


def hash_backup_codes(codes: list) -> str:
    """将备用码列表 bcrypt 哈希后序列化为 JSON 字符串存储"""
    hashed = [
        bcrypt.hashpw(c.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")
        for c in codes
    ]
    return json.dumps(hashed)


def verify_backup_code(hashed_json: str, code: str) -> bool:
    """校验备用码（明文）是否匹配任一已哈希码"""
    if not hashed_json or not code:
        return False
    try:
        hashed_list = json.loads(hashed_json)
    except Exception:
        return False
    code = code.strip()
    for h in hashed_list:
        try:
            if bcrypt.checkpw(code.encode("utf-8"), h.encode("utf-8")):
                return True
        except Exception:
            continue
    return False


def consume_backup_code(hashed_json: str, code: str) -> str:
    """校验并消费一个备用码，返回更新后的哈希 JSON（未命中则原样返回）"""
    if not hashed_json:
        return hashed_json
    try:
        hashed_list = json.loads(hashed_json)
    except Exception:
        return hashed_json
    code = code.strip()
    new_list = []
    consumed = False
    for h in hashed_list:
        if not consumed and bcrypt.checkpw(code.encode("utf-8"), h.encode("utf-8")):
            consumed = True
            continue
        new_list.append(h)
    return json.dumps(new_list)


# ==================== WebAuthn / Passkey ====================
def _webauthn_config():
    """返回 (rp_id, rp_name, origin)"""
    return settings.WEBAUTHN_RP_ID, settings.WEBAUTHN_RP_NAME, settings.WEBAUTHN_ORIGIN


def build_registration_options(user, existing_credential_ids: list) -> tuple:
    """构造通行密钥登记选项。

    :param user: 当前用户对象（需 id / phone / username）
    :param existing_credential_ids: 该用户已有凭证 ID（base64url），用于 exclude
    :return: (options_json, challenge_token)
    """
    rp_id, rp_name, _origin = _webauthn_config()
    exclude = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(cid))
        for cid in (existing_credential_ids or [])
    ]
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=str(user.id).encode("utf-8"),
        user_name=user.phone or user.username or str(user.id),
        user_display_name=user.username or user.phone or str(user.id),
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # 无用户名登录要求凭证可发现（discoverable）
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=exclude,
    )
    challenge_b64 = bytes_to_base64url(options.challenge)
    challenge_token = create_webauthn_challenge_token(challenge_b64)
    return options_to_json(options), challenge_token


def verify_registration(credential: dict, challenge_token: str) -> tuple:
    """校验通行密钥登记响应。

    :return: (ok, credential_id_b64, public_key_bytes, sign_count)
    """
    challenge_b64 = verify_webauthn_challenge_token(challenge_token)
    if not challenge_b64:
        return (False, "", b"", 0)
    _rp_id, _rp_name, origin = _webauthn_config()
    expected_challenge = base64url_to_bytes(challenge_b64)
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_origin=origin,
            expected_rp_id=_rp_id,
            require_user_verification=False,
        )
    except Exception:
        return (False, "", b"", 0)
    cred_id_b64 = bytes_to_base64url(verified.credential_id)
    return (True, cred_id_b64, verified.credential_public_key, verified.sign_count)


def build_authentication_options() -> tuple:
    """构造无用户名登录断言选项（allow_credentials 留空，依赖 discoverable 凭证）。

    :return: (options_json, challenge_token)
    """
    rp_id, _rp_name, _origin = _webauthn_config()
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[],  # 无用户名：浏览器从已注册 passkey 中自动发现
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    challenge_b64 = bytes_to_base64url(options.challenge)
    challenge_token = create_webauthn_challenge_token(challenge_b64)
    return options_to_json(options), challenge_token


def verify_authentication(
    credential: dict, challenge_token: str, public_key: bytes, sign_count: int
) -> tuple:
    """校验通行密钥登录断言。

    :return: (ok, new_sign_count)
    """
    challenge_b64 = verify_webauthn_challenge_token(challenge_token)
    if not challenge_b64:
        return (False, 0)
    _rp_id, _rp_name, origin = _webauthn_config()
    expected_challenge = base64url_to_bytes(challenge_b64)
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_origin=origin,
            expected_rp_id=_rp_id,
            credential_public_key=public_key,
            credential_current_sign_count=sign_count,
            require_user_verification=False,
        )
    except Exception:
        return (False, 0)
    return (True, verified.new_sign_count)
