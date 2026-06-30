# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.ai import AIQuestion, AIAnswer
from app.services.ai_service import AIService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI健康助手"])

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
    req: AIQuestion
):
    """向AI健康助手提问（无需认证，供老人端使用）"""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    logger.info(f"收到老人端提问: {req.question}")
    answer = await AIService.ask(req.question)
    logger.info(f"AI回答: {answer}")
    return AIAnswer(answer=answer)