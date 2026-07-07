#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""子女看护Web端 - 主程序

本地以纯 HTTP 监听，HTTPS 由 Cloudflare 隧道边缘自动配置，无需本地证书。
支持路径前缀（PATH_PREFIX），用于 Cloudflare 隧道按子路径转发场景。
"""

import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
# 这样无论从哪个目录运行，都能正确导入模块
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from core import config
from core.auth import get_user_manager
from core.session import get_session_manager
from routes import home_router
from routes import chat_router
from routes import auth_router
from routes.admin import admin_router
import logging

logger = logging.getLogger(__name__)

# 路径前缀（Cloudflare 隧道子路径），默认 /eating-medication/family
# 本地直连时设为空字符串即可
PATH_PREFIX = os.getenv("PATH_PREFIX", getattr(config, "PATH_PREFIX", "/eating-medication/family")).rstrip("/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    get_user_manager(config.DATA_DIR)

    # O1 修复：启动信息改用 logger
    logger.info("=" * 60)
    logger.info(f" {config.APP_NAME} 启动中...")
    logger.info(f" 服务地址: http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    logger.info(f" 老人端地址: {config.ELDERLY_SERVER_URL}")
    logger.info(f" 认证系统: 已启用 (bcrypt加密)")
    logger.info(f" 路径前缀: {PATH_PREFIX or '(无，根路径)'}")
    logger.info(f" HTTPS: 由 Cloudflare 隧道边缘自动配置，本地监听 HTTP")
    logger.info(f" 管理员入口: {PATH_PREFIX}/admin/administrator/setting")
    logger.info("=" * 60)

    yield

    logger.info("服务已停止")


# 创建FastAPI应用（root_path 用于 OpenAPI 文档与外部 URL 构建）
app = FastAPI(
    title=config.APP_NAME,
    description="子女看护Web端",
    version="2.2.0",
    debug=config.DEBUG,
    lifespan=lifespan,
    root_path=PATH_PREFIX,
)


# CORS中间件 - 从环境变量 ALLOWED_ORIGINS 读取允许的来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """安全响应头中间件：为每个响应添加安全相关的 HTTP 头"""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "object-src 'none'; "
        "base-uri 'self'"
    )
    return response


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    """CSRF 中间件：
    - 为每个请求确保 csrf_token cookie 存在（不存在则生成并设置到响应）
    - 将 csrf_token 注入 request.state 供模板使用
    """
    csrf_token = request.cookies.get("csrf_token")
    if not csrf_token:
        session_manager = get_session_manager(config.SECRET_KEY)
        csrf_token = session_manager.generate_csrf_token()
    # 注入到 request.state 供模板渲染时读取
    request.state.csrf_token = csrf_token

    response = await call_next(request)

    # 如果请求中没有 csrf_token cookie，则在响应中设置
    if not request.cookies.get("csrf_token"):
        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            httponly=False,  # 允许 JS 读取，用于 AJAX 请求附带 header
            samesite="strict",
            secure=config.COOKIE_SECURE,
            max_age=86400 * 7,
        )

    return response


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """认证中间件，保护需要登录的页面。
    注意：使用 request.scope["path"]（已被前缀中间件剥离前缀后的路径）。"""
    # 公开路径精确匹配，防止路径前缀绕过
    public_paths = ["/login", "/register", "/favicon.ico"]
    path = request.scope.get("path", request.url.path)
    is_public = path in public_paths or path.startswith("/static/")

    request.state.user = None

    if is_public:
        return await call_next(request)

    session_manager = get_session_manager(config.SECRET_KEY)
    session_token = request.cookies.get("session_token")

    # G5 修复：重定向 URL 显式拼接 PATH_PREFIX，不依赖中间件隐式补前缀
    login_url = f"{PATH_PREFIX}/login" if PATH_PREFIX else "/login"
    home_url = f"{PATH_PREFIX}/" if PATH_PREFIX else "/"

    if not session_token:
        return RedirectResponse(url=login_url, status_code=302)

    session_data = session_manager.verify_session(session_token)
    if not session_data:
        return RedirectResponse(url=login_url, status_code=302)

    username = session_data.get("username")
    request.state.user = username

    # 检查admin路径权限
    if path.startswith("/admin"):
        user_manager = get_user_manager(config.DATA_DIR)
        if not user_manager.is_admin(username):
            return RedirectResponse(url=home_url, status_code=302)

    response = await call_next(request)
    return response


@app.middleware("http")
async def path_prefix_middleware(request: Request, call_next):
    """路径前缀中间件（最先执行）：
    - 请求阶段：剥离 PATH_PREFIX，使应用路由按根路径匹配
    - 响应阶段：给 3xx 重定向的 Location 头补回前缀
    本地直连（PATH_PREFIX 为空）时直接放行。"""
    if PATH_PREFIX:
        original = request.scope.get("path", "")
        if original == PATH_PREFIX:
            request.scope["path"] = "/"
            request.scope["raw_path"] = b"/"
        elif original.startswith(PATH_PREFIX + "/"):
            new_path = original[len(PATH_PREFIX):]
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode()
        response = await call_next(request)
        # 重定向 Location 补前缀
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location", "")
            if (location.startswith("/")
                    and not location.startswith(PATH_PREFIX + "/")
                    and location != PATH_PREFIX):
                response.headers["location"] = PATH_PREFIX + location
        return response
    return await call_next(request)


# 挂载静态文件
if config.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

# 注册路由
app.include_router(auth_router)
app.include_router(home_router)
app.include_router(chat_router)
app.include_router(admin_router)

def main():
    """主函数"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    # 启动时检查更新（自动更新功能）
    try:
        from updater import check_for_update
        check_for_update()
    except Exception as e:
        logger.warning(f"更新检查失败: {e}")

    # 本地纯 HTTP 监听，HTTPS 由 Cloudflare 隧道边缘处理
    uvicorn.run(
        "main:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
