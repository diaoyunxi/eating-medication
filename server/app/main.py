# -*- coding: utf-8 -*-
"""
FastAPI 应用入口 - 最终版
创建并配置 FastAPI 实例，注册路由、中间件、异常处理器，并启动后台定时任务。
"""

import logging
import sys
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import engine, Base
from app.middleware.logging import LoggingMiddleware
from app.middleware.exception_handler import add_exception_handlers  
from app.api.v1.endpoints import (
    auth, users, medication, ai, vision, public, chat
)
from app.api.v1.websocket import router as ws_router
from app.tasks.stock_checker import start_scheduler, shutdown_scheduler

# 配置更详细的日志
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,     
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",   
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# 设置第三方库的日志级别
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)        
logging.getLogger("uvicorn.error").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    管理应用生命周期：
    - 启动时创建数据库表、启动后台任务
    - 关闭时清理资源
    """
    logger.info("="*60)
    logger.info(" 正在启动服务端...")
    logger.info(f" 应用名称: {settings.APP_NAME}")
    logger.info(f" 调试模式: {'开启' if settings.DEBUG else '关闭'}")
    logger.info(f" ZhipuAI 配置: {'已配置' if settings.ZHIPUAI_API_KEY else '未配置'}")
    if settings.ZHIPUAI_API_KEY:
        logger.info(f"   - 模型: {settings.ZHIPUAI_MODEL}")
    logger.info("="*60)

    # 创建数据库表（如果不存在）
    logger.info(" 检查数据库表...")
    Base.metadata.create_all(bind=engine)
    logger.info(" 数据库表检查完成")

    # 启动后台定时任务（低库存检查等）
    logger.info(" 启动后台定时任务...")
    start_scheduler()
    logger.info(" 后台定时任务已启动")

    logger.info(" 服务端启动成功！")
    logger.info("="*60)

    yield

    # 关闭时执行
    logger.info("="*60)
    logger.info(" 正在关闭服务端...")
    shutdown_scheduler()
    logger.info(" 后台定时任务已停止")
    logger.info(" 再见！")
    logger.info("="*60)


# 创建 FastAPI 实例
app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    description="老人用药管理智能助手后端 API",
    debug=settings.DEBUG,
    lifespan=lifespan
)

# ==================== 中间件配置 ====================

# CORS（允许跨域，开发模式使用 *）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 生产环境应替换为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求日志中间件
app.add_middleware(LoggingMiddleware)

# 全局异常处理器
add_exception_handlers(app)

# ==================== 路由注册 ====================

api_prefix = settings.API_V1_PREFIX
app.include_router(auth.router, prefix=api_prefix)
app.include_router(users.router, prefix=api_prefix)
app.include_router(medication.router, prefix=api_prefix)
app.include_router(ai.router, prefix=api_prefix)
app.include_router(vision.router, prefix=api_prefix)
app.include_router(public.router, prefix=api_prefix)
app.include_router(chat.router, prefix=api_prefix)

# WebSocket 路由（独立路径，不加 /api/v1 前缀）
app.include_router(ws_router, prefix="/ws")

# ==================== 健康检查 ====================

@app.get("/health")
async def health_check():
    """健康检查接口，用于容器编排或监控"""
    logger.info(" 健康检查被调用")
    return JSONResponse(
        content={"status": "ok", "service": settings.APP_NAME},
        media_type="application/json; charset=utf-8"
    )

@app.get("/")
async def root():
    """根路径，返回简单提示"""
    logger.info(" 根路径被访问")
    return JSONResponse(
        content={
            "message": f"欢迎使用 {settings.APP_NAME} API",
            "docs": "/docs",
            "health": "/health"
        },
        media_type="application/json; charset=utf-8"
    )


if __name__ == "__main__":
    import uvicorn
    logger.info("="*60)
    logger.info(" 正在启动服务端...")
    logger.info("="*60)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info",
        access_log=False
    )
