# -*- coding: utf-8 -*-
import httpx
import logging
from typing import Optional, Dict, Any
from app.core.config import settings

logger = logging.getLogger(__name__)

class HTTPClient:
    """HTTP 客户端封装，提供统一的请求方法"""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0):
        self.base_url = base_url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建异步客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                follow_redirects=True
            )
        return self._client

    async def close(self):
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get(self, url: str, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> Dict[str, Any]:
        """GET 请求"""
        client = await self._get_client()
        try:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"GET 请求失败 {url}: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"GET 请求异常 {url}: {e}")
            raise

    async def post(self, url: str, json: Optional[Dict] = None, data: Optional[Dict] = None, headers: Optional[Dict] = None) -> Dict[str, Any]:
        """POST 请求"""
        client = await self._get_client()
        try:
            response = await client.post(url, json=json, data=data, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"POST 请求失败 {url}: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"POST 请求异常 {url}: {e}")
            raise

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()