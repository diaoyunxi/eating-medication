# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, Request
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.ai import AIQuestion, AIAnswer
from app.services.ai_service import AIService
from app.utils.rate_limit import check_rate_limit
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI健康助手"])

# AI 公开端点限流：每分钟每 IP 最多 10 次
_AI_RATE_LIMIT = 10

@router.post("/chat", response_model=AIAnswer)
async def chat(
    req: AIQuestion,
    current_user: User = Depends(get_current_user)
):
    """向AI健康助手提问（需要认证）"""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    answer = await AIService.ask(req.question)
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

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    logger.info(f"收到老人端提问: {req.question}")
    answer = await AIService.ask(req.question)
    logger.info(f"AI回答: {answer}")
    return AIAnswer(answer=answer)
