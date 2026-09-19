# -*- coding: utf-8 -*-
"""邮箱验证码工具：生成、存储、发送与校验。

说明：
- 验证码存储于进程内存，适用于单进程部署；多进程部署需改用 Redis 等共享存储
  （与项目内 rate_limit 的单进程实现风格一致）。
- 邮件发送使用标准 smtplib；未配置 MAIL_* 时回退为日志输出，便于本地开发调试。
"""
import os
import random
import time
import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.header import Header

from app.core.config import settings

logger = logging.getLogger(__name__)

_CODE_TTL = 300  # 验证码有效期（秒）
_CODE_LEN = 6

# 进程内存存储：email(lower) -> (code, expire_ts)
_store = {}


def _gen_code():
    """生成指定长度的数字验证码。"""
    return "".join(random.choice("0123456789") for _ in range(_CODE_LEN))


def send_code(email):
    """生成并发送邮箱验证码。

    :param email: 目标邮箱
    :return: (ok: bool, msg: str)
    """
    if not email:
        return False, "邮箱不能为空"
    email = email.strip().lower()
    code = _gen_code()
    _store[email] = (code, time.time() + _CODE_TTL)
    logger.info(f"[邮箱验证码] 已为 {email} 生成验证码（{_CODE_TTL}s 有效）")

    ok, err = _send_email(email, code)
    if not ok:
        return False, err
    return True, "验证码已发送，请查收邮箱"


def verify_code(email, code):
    """校验验证码，校验成功后立即失效（一次性使用）。

    :param email: 邮箱
    :param code: 待校验验证码
    :return: bool
    """
    if not email or not code:
        return False
    email = email.strip().lower()
    item = _store.get(email)
    if not item:
        return False
    stored_code, expire = item
    if time.time() > expire:
        _store.pop(email, None)
        return False
    if str(code).strip() != stored_code:
        return False
    _store.pop(email, None)  # 一次性使用
    return True


def _send_email(email, code):
    """通过 SMTP 发送验证码邮件；未配置邮件服务时回退为日志输出。

    :return: (ok: bool, msg: str)
    """
    provider = getattr(settings, "MAIL_PROVIDER", None)
    host = getattr(settings, "MAIL_HOST", None)
    if not provider or not host:
        logger.warning(
            f"[邮箱验证码] 未配置邮件服务（MAIL_PROVIDER/MAIL_HOST），验证码 {code} "
            f"仅记录于日志，未实际发送；请配置 MAIL_* 后重试"
        )
        return False, "邮件服务未配置，无法发送验证码（请配置 MAIL_* 后重试）"
    try:
        port = int(getattr(settings, "MAIL_PORT", 0) or 0)
        user = getattr(settings, "MAIL_USERNAME", None)
        pwd = getattr(settings, "MAIL_PASSWORD", None)
        frm = getattr(settings, "MAIL_FROM", None) or user
        use_ssl = bool(getattr(settings, "MAIL_USE_SSL", False))
        use_tls = bool(getattr(settings, "MAIL_USE_TLS", False))

        subject = "老人用药管理 - 邮箱验证码"
        body = (
            f"您的邮箱验证码为：{code}（{_CODE_TTL // 60} 分钟内有效，请勿泄露给他人）。"
        )
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = frm
        msg["To"] = email

        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=10) as s:
                if user:
                    s.login(user, pwd)
                s.sendmail(frm, [email], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=10) as s:
                if use_tls:
                    s.starttls(context=ssl.create_default_context())
                if user:
                    s.login(user, pwd)
                s.sendmail(frm, [email], msg.as_string())
        logger.info(f"[邮箱验证码] 已向 {email} 发送验证码邮件")
        return True, ""
    except Exception as e:
        logger.warning(f"[邮箱验证码] 发送失败: {e}")
        return False, f"验证码邮件发送失败：{e}"
