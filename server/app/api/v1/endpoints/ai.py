# -*- coding: utf-8 -*-
import re
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.ai import AIQuestion, AIAnswer
from app.services.ai_service import AIService
from app.services.ai_config_service import get_effective_config
from app.utils.rate_limit import check_rate_limit
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI健康助手"])

# AI 公开端点限流：每分钟每 IP 最多 10 次
_AI_RATE_LIMIT = 10

# 去除 HTML 标签，防止脚本注入（XSS）与日志注入（BUG-M05）
_TAG_RE = re.compile(r"<[^>]*>", flags=re.IGNORECASE)
# 去除控制字符（含换行/回车/制表），避免日志注入与协议污染
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_question(raw: str) -> str:
    """对用户输入做基础净化（BUG-M05 修复）：

    - 剥离 HTML 标签（防止 <script> 等脚本注入）；
    - 去除控制字符（防止日志注入 / 换行绕过）；
    - 去除首尾空白。
    净化仅用于缓解注入与日志污染，不改变语义内容。
    """
    if not raw:
        return ""
    cleaned = _TAG_RE.sub("", raw)
    cleaned = _CTRL_RE.sub("", cleaned)
    return cleaned.strip()


@router.post("/chat", response_model=AIAnswer)
async def chat(
    req: AIQuestion,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """向AI健康助手提问（需要认证，使用当前用户各自的 AI 配置）"""
    question = _sanitize_question(req.question)
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    # 优先使用当前用户（或同组兜底）在数据库中配置的每用户 AI 设置
    cfg = get_effective_config(db, current_user)
    answer = await AIService.ask(question, **cfg)
    # 可选：保存问答记录到数据库
    return AIAnswer(answer=answer)

@router.post("/chat/public", response_model=AIAnswer)
async def chat_public(
    req: AIQuestion,
    request: Request,
):
    """向AI健康助手提问（无需认证，供老人端使用，基于 IP 限流）"""
    # 限流
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(f"ai_chat_public:{client_ip}", _AI_RATE_LIMIT):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    question = _sanitize_question(req.question)
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    logger.info(f"收到老人端提问: {question}")
    answer = await AIService.ask(question)
    logger.info(f"AI回答: {answer}")
    return AIAnswer(answer=answer)
