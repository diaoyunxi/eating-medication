# -*- coding: utf-8 -*-
"""
FastAPI 应用入口 - 最终版
创建并配置 FastAPI 实例，注册路由、中间件、异常处理器，并启动后台定时任务。
"""

import logging
import sys
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import (
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
    get_redoc_html,
)

from app.core.config import settings
from app.core.database import engine, Base
from app.middleware.logging import LoggingMiddleware
from app.middleware.exception_handler import add_exception_handlers
# C7：改用统一的 setup_cors 配置 CORS
from app.middleware.cors import setup_cors
from app.api.v1.endpoints import (
    auth, users, medication, ai, vision, public, chat, oauth
)
from app.tasks.stock_checker import start_scheduler, shutdown_scheduler

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

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

    # FIX (2.10.1)：Turnstile 配置检查——缺失 Secret Key 会导致生产环境登录/注册全部被拒
    # Turnstile 需两把密钥：站点密钥(Site Key) 在 family_monitor/.env 渲染前端，
    # 密钥(Secret Key) 在 server/.env 用于后端 siteverify 校验。两者必须分别配置。
    if settings.TURNSTILE_SECRET_KEY:
        logger.info(" Turnstile 配置: 已启用（后端 siteverify 校验）")
    elif settings.DEBUG:
        logger.warning(
            "⚠ Turnstile 未配置 TURNSTILE_SECRET_KEY：开发环境将跳过人机验证；"
            "生产环境（DEBUG=False）必须配置，否则所有登录/注册将被拒绝。"
        )
    else:
        logger.error(
            "⚠ 生产环境未配置 TURNSTILE_SECRET_KEY！所有登录/注册将被拒绝。"
            "请在 server/.env 的 TURNSTILE_SECRET_KEY 填入 Cloudflare Turnstile 的 Secret Key 后重启服务。"
        )

    logger.info("="*60)

    # 创建数据库表（如果不存在）
    # S3 修复：优先使用 Alembic 迁移管理表结构，失败则回退 create_all（兼容现有部署）
    try:
        from alembic.config import Config
        from alembic import command
        import os as _os
        alembic_ini = _os.path.join(_os.path.dirname(__file__), "migrations", "alembic.ini")
        if _os.path.exists(alembic_ini):
            alembic_cfg = Config(alembic_ini)
            command.upgrade(alembic_cfg, "head")
            logger.info(" Alembic 迁移已执行")
        else:
            raise FileNotFoundError("alembic.ini 不存在")
    except Exception as e:
        logger.warning(f" Alembic 迁移跳过（{e}），回退到 create_all")
        Base.metadata.create_all(bind=engine)
        logger.info(" 数据库表检查完成（create_all）")

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


# 路径前缀（Cloudflare 隧道子路径），本地直连设为空
PATH_PREFIX = settings.PATH_PREFIX.rstrip("/")

# 创建 FastAPI 实例（禁用默认文档，使用本地静态资源）
# 安全修复（中危7）：生产环境完全禁用 API 文档，防止信息泄露
_is_debug = settings.DEBUG
app = FastAPI(
    title=settings.APP_NAME,
    version="2.10.1",
    description="老人用药管理智能助手后端 API",
    debug=_is_debug,
    lifespan=lifespan,
    root_path=PATH_PREFIX,
    docs_url=None,
    redoc_url=None,
    # 生产环境不暴露 openapi.json，开发环境暴露
    openapi_url="/openapi.json" if _is_debug else None,
)

# ==================== 中间件配置 ====================

# C7：使用统一的 setup_cors 配置 CORS（从环境变量 ALLOWED_ORIGINS 读取白名单）
setup_cors(app)

# 请求日志中间件
app.add_middleware(LoggingMiddleware)

# S13 修复：移除手动 path_prefix 中间件，前缀剥离统一由 root_path 处理，避免双重处理

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
app.include_router(oauth.router, prefix=api_prefix)

# S8 修复：移除冲突的 ws_router（/ws 与 chat.py 的 /chat/ws/{user_id} 重叠）
# WebSocket 聊天功能统一由 chat.py 的 ws_chat 提供

# ==================== 静态文件服务 ====================
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ==================== 自定义文档路由（使用本地静态资源） ====================
# 安全修复（中危7）：生产环境不注册文档路由，防止 API 结构泄露
docs_static_url = f"{PATH_PREFIX}/static/docs" if PATH_PREFIX else "/static/docs"
openapi_full_url = f"{PATH_PREFIX}/openapi.json" if PATH_PREFIX else "/openapi.json"


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    """Swagger UI - 仅开发环境可用"""
    if not _is_debug:
        raise HTTPException(status_code=404, detail="Not Found")
    return get_swagger_ui_html(
        openapi_url=openapi_full_url,
        title=app.title + " - Swagger UI",
        swagger_js_url=f"{docs_static_url}/js/swagger-ui-bundle.js",
        swagger_css_url=f"{docs_static_url}/css/swagger-ui.css",
        swagger_favicon_url=f"{docs_static_url}/img/favicon.png",
        oauth2_redirect_url=f"{PATH_PREFIX}/docs/oauth2-redirect" if PATH_PREFIX else "/docs/oauth2-redirect",
    )


@app.get("/docs/oauth2-redirect", include_in_schema=False)
async def swagger_ui_oauth2_redirect():
    if not _is_debug:
        raise HTTPException(status_code=404, detail="Not Found")
    return get_swagger_ui_oauth2_redirect_html()


@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    """ReDoc - 仅开发环境可用"""
    if not _is_debug:
        raise HTTPException(status_code=404, detail="Not Found")
    return get_redoc_html(
        openapi_url=openapi_full_url,
        title=app.title + " - ReDoc",
        redoc_js_url=f"{docs_static_url}/js/redoc.standalone.js",
        redoc_favicon_url=f"{docs_static_url}/img/favicon.png",
        with_google_fonts=False,
    )


# ==================== 健康检查 ====================

@app.get("/health")
async def health_check():
    """健康检查接口，用于容器编排或监控"""
    # O7 修复：健康检查高频调用，降为 debug 级别避免日志刷屏
    logger.debug("健康检查被调用")
    return JSONResponse(
        content={"status": "ok", "service": settings.APP_NAME},
        media_type="application/json; charset=utf-8"
    )

@app.get("/")
async def root():
    """根路径，返回简单提示"""
    logger.debug("根路径被访问")
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
