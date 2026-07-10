# -*- coding: utf-8 -*-
from typing import Optional
from app.core.config import settings
import logging
import threading
import asyncio

logger = logging.getLogger(__name__)

class AIService:
    """AI 健康助手服务（调用智谱AI ZhipuAI API）"""

    _client: Optional[object] = None
    _lock = threading.Lock()  # G13 修复：保护单例客户端初始化的线程安全

    @classmethod
    def _get_client(cls):
        """获取 ZhipuAI 客户端（单例，G13：加锁防止并发重复初始化）"""
        # 双重检查锁定，避免已初始化时的锁开销
        if cls._client is None and settings.ZHIPUAI_API_KEY:
            with cls._lock:
                if cls._client is None and settings.ZHIPUAI_API_KEY:
                    try:
                        from zhipuai import ZhipuAI
                        cls._client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY)
                        logger.info("✅ ZhipuAI 客户端初始化成功")
                    except Exception as e:
                        logger.error(f"❌ ZhipuAI 客户端初始化失败: {e}")
                        cls._client = None
        return cls._client

    @staticmethod
    async def ask(question: str) -> str:
        """向 AI 提问，返回回答（老人端POST上来的消息）"""
        if not settings.ZHIPUAI_API_KEY:
            error_msg = "AI 服务未配置，请联系管理员配置 API 密钥"
            logger.warning(f"⚠️ {error_msg}")
            return error_msg
        
        client = AIService._get_client()
        if not client:
            error_msg = "AI 服务初始化失败，请稍后再试"
            logger.error(f"❌ {error_msg}")
            return error_msg
        
        logger.info(f"🤔 AI 请求 - 问题: {question}")
        
        try:
            # S-06 修复：同步 SDK 调用放入线程池，避免阻塞事件循环
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=settings.ZHIPUAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一位专业的健康助手，专门为老年人提供用药指导、健康科普、疾病预防建议。请用通俗易懂、亲切耐心的语气回答，尽量简短明了。",
                    },
                    {"role": "user", "content": question},
                ],
                temperature=0.7,
                max_tokens=1024,
            )
            
            answer = response.choices[0].message.content
            logger.info(f"💬 AI 回答:\n{answer}")
            return answer
            
        except Exception:
            # H10：异常细节不返回客户端，仅记录详细日志
            logger.exception("AI 服务调用失败")
            return "AI 服务暂时不可用，请稍后再试"
