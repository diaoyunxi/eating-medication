# -*- coding: utf-8 -*-
import time
import logging
import json
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

# 使用独立的 logger 而不是 uvicorn.access
logger = logging.getLogger("app.access")

class LoggingMiddleware(BaseHTTPMiddleware):
    """详细记录每个请求的信息：方法、路径、客户端IP、User-Agent、状态码和耗时"""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # 获取客户端信息
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        
        # 记录请求开始
        logger.info(
            f"📥 新请求 - {request.method} {request.url.path} "
            f"来自: {client_ip} - UA: {user_agent}"
        )
        
        # 尝试读取请求体
        content_type = request.headers.get("content-type", "")
        if request.method in ["POST", "PUT", "PATCH"]:
            # 对于文件上传(multipart/form-data)，只记录元信息，不尝试解码二进制数据
            if "multipart/form-data" in content_type or "application/octet-stream" in content_type:
                logger.info(f"📦 文件上传请求，不记录二进制内容")
            else:
                # 对于文本请求，尝试读取和解析
                try:
                    body_bytes = await request.body()
                    if body_bytes:
                        request_body = body_bytes.decode("utf-8", errors="replace")
                        # 尝试格式化 JSON
                        try:
                            parsed = json.loads(request_body)
                            request_body = json.dumps(parsed, ensure_ascii=False, indent=2)
                        except:
                            pass
                        logger.info(f"📦 请求体:\n{request_body}")
                except Exception as e:
                    logger.debug(f"读取请求体失败: {e}")
        
        # 处理请求
        response = await call_next(request)
        
        process_time = time.time() - start_time
        
        # 记录响应
        status_emoji = "✅" if 200 <= response.status_code < 300 else "⚠️" if 400 <= response.status_code < 500 else "❌"
        logger.info(
            f"{status_emoji} 响应完成 - {request.method} {request.url.path} "
            f"status={response.status_code} "
            f"duration={process_time:.3f}s"
        )
        
        response.headers["X-Process-Time"] = str(process_time)
        return response
