# -*- coding: utf-8 -*-
from typing import Optional
from app.core.config import settings
import logging
import threading
import asyncio

logger = logging.getLogger(__name__)

# 各厂商 OpenAI 兼容 base_url 预设（统一走 OpenAI 协议，仅需一个 openai 库即可覆盖全部厂商）
# 自定义厂商(custom)的 base_url 由调用方传入，不在此预设
PROVIDER_BASE_URLS = {
    "zhipuai": "https://open.bigmodel.cn/api/paas/v4",
    "hunyuan": "https://api.hunyuan.cloud.tencent.com/v1",
    "minimax": "https://api.minimax.io/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}

# 各厂商默认模型（当用户未显式指定模型时使用；火山方舟需推理接入点 ID，无通用默认值）
PROVIDER_DEFAULT_MODELS = {
    "zhipuai": "glm-4.7-flash",
    "hunyuan": "hunyuan-2.0-instruct-20251111",
    "minimax": "MiniMax-M2.5",
    "kimi": "moonshot-v1-8k",
    "deepseek": "deepseek-chat",
    "doubao": "",
    "qwen": "qwen-plus",
}

SUPPORTED_PROVIDERS = list(PROVIDER_BASE_URLS.keys()) + ["custom"]


class AIService:
    """AI 健康助手服务（统一 OpenAI 协议，支持多厂商）

    设计要点：
    - 所有厂商均通过 OpenAI 官方 SDK（openai 库）以 base_url 区分，无需各厂商专属库。
    - 调用方（路由层）应优先传入「每用户各自的配置」(provider/api_key/model/base_url)；
      缺省时回退到全局 settings.ZHIPUAI_*（兼容旧 .env 单厂商配置）。
    """

    # 按 (provider, api_key) 缓存 OpenAI 客户端，避免重复初始化
    _clients: dict = {}
    _lock = threading.Lock()

    @classmethod
    def _resolve(cls, provider: Optional[str], api_key: Optional[str],
                 model: Optional[str], base_url: Optional[str]):
        """解析并归一化一组 AI 配置，返回 (provider, api_key, base_url, model)。"""
        prov = (provider or "zhipuai").lower()
        key = api_key if api_key else settings.ZHIPUAI_API_KEY
        # base_url：custom 必须显式传入；其余厂商从预设取，允许调用方覆盖
        if prov == "custom":
            base = base_url or ""
        else:
            base = base_url or PROVIDER_BASE_URLS.get(prov, "")
        mdl = model or settings.ZHIPUAI_MODEL or PROVIDER_DEFAULT_MODELS.get(prov, "")
        return prov, key, base, mdl

    @classmethod
    def _get_client(cls, provider: str, api_key: str, base_url: str):
        """获取 OpenAI 兼容客户端（按 provider+key 缓存，线程安全）"""
        if not api_key:
            return None
        if not base_url and provider != "custom":
            logger.error(f"❌ AI 厂商 {provider} 缺少 base_url 且不在预设列表中")
            return None
        cache_key = (provider, api_key)
        with cls._lock:
            cached = cls._clients.get(cache_key)
            if cached is not None:
                return cached
        try:
            from openai import OpenAI
            client = OpenAI(base_url=base_url, api_key=api_key)
            with cls._lock:
                cls._clients[cache_key] = client
            logger.info(f"✅ OpenAI 客户端初始化成功 (provider={provider})")
            return client
        except Exception as e:
            logger.error(f"❌ OpenAI 客户端初始化失败 (provider={provider}): {e}")
            return None

    @classmethod
    async def ask(cls, question: str,
                  provider: Optional[str] = None,
                  api_key: Optional[str] = None,
                  model: Optional[str] = None,
                  base_url: Optional[str] = None) -> str:
        """向 AI 提问，返回回答。

        :param question: 用户问题
        :param provider/api_key/model/base_url: 优先使用调用方传入的「每用户配置」；
              缺省回退到全局 settings.ZHIPUAI_*（兼容旧的单一智谱配置）。
        """
        if not question or not question.strip():
            return "问题不能为空"

        prov, key, base, mdl = cls._resolve(provider, api_key, model, base_url)
        if not key:
            return "AI 服务未配置，请在设置中配置 API 密钥"
        if not mdl:
            return f"AI 模型未配置（厂商 {prov}），请在设置中指定模型"

        client = cls._get_client(prov, key, base)
        if not client:
            return "AI 服务初始化失败，请稍后再试"

        logger.info(f"🤔 AI 请求 - 厂商: {prov}, 模型: {mdl}, 问题: {question}")
        try:
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=mdl,
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
            logger.exception("AI 服务调用失败")
            return "AI 服务暂时不可用，请稍后再试"
