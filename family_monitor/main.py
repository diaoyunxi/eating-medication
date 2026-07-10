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

import struct
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse, Response
from core import config
from core.auth import get_user_manager
from core.session import get_session_manager
from routes import home_router
from routes import chat_router
from routes import auth_router
from routes.admin import admin_router
import logging

# 使用 uvicorn.error logger，确保启动阶段的 info/warning 日志能随 uvicorn 输出
# 否则默认 Python logging 只显示 WARNING+，应用层的 info 诊断日志将不可见
logger = logging.getLogger("uvicorn.error")

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
    version="2.9",
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
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "object-src 'none'; "
        "base-uri 'self'"
    )
    return response


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """认证中间件，保护需要登录的页面。
    注意：使用 request.scope["path"]（已被前缀中间件剥离前缀后的路径）。"""
    # 公开路径精确匹配，防止路径前缀绕过
    public_paths = ["/login", "/register", "/favicon.ico"]
    path = request.scope.get("path", request.url.path)
    is_public = path in public_paths or path.startswith("/static/") or path.startswith("/.well-known/")

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
# 注意：必须确保 static 目录存在，否则 /static/* 请求会全部 404，导致 UI 样式丢失
if config.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
    logger.info(f"静态文件已挂载: /static -> {config.STATIC_DIR}")
else:
    logger.warning(
        f"静态文件目录不存在: {config.STATIC_DIR}，/static/* 请求将返回 404，"
        f"UI 样式将无法加载。请检查 git clone 是否完整，目录应包含 css/style.css"
    )


@app.middleware("http")
async def static_404_hint_middleware(request: Request, call_next):
    """静态文件 404 提示中间件：当 /static/ 请求返回 404 时，输出日志提示检查配置"""
    response = await call_next(request)
    path = request.scope.get("path", request.url.path)
    if path.startswith("/static/") and response.status_code == 404:
        logger.warning(
            f"静态文件 404: {path} | 可能原因: "
            f"1) 文件不存在请检查 static/ 目录; "
            f"2) PATH_PREFIX 配置不当（当前: '{PATH_PREFIX}'，本地直连应为空）; "
            f"3) 通过 Cloudflare 隧道子路径访问时需确保前缀剥离正确"
        )
    return response


# ---------------------------------------------------------------------------
# 浏览器自动请求的辅助路由（避免 404 噪音）
# ---------------------------------------------------------------------------

def _generate_favicon_ico() -> bytes:
    """生成 16x16 蓝色 ICO 图标字节（BGRA 格式，不依赖第三方库）"""
    width = height = 16
    # BMP Info Header (40 bytes)
    bmp_header = struct.pack(
        '<IiiHHIIiiII',
        40,            # biSize
        width,         # biWidth
        height * 2,    # biHeight（ICO 中需翻倍，含 AND mask）
        1,             # biPlanes
        32,            # biBitCount
        0, 0, 0, 0,    # compression, imageSize, x/y ppm
        0, 0,          # colors used, important
    )
    # 像素数据：16x16 BGRA，蓝色 #007CFF（B=0xFF, G=0x7C, R=0x00, A=0xFF）
    pixel_data = bytes([0xFF, 0x7C, 0x00, 0xFF]) * (width * height)
    # AND mask：每行按 4 字节对齐，16 行共 64 字节，全 0 表示不透明
    and_mask = bytes([0x00] * (4 * height))
    image_data = bmp_header + pixel_data + and_mask

    # ICO Header (6 bytes) + Directory Entry (16 bytes)
    ico_header = struct.pack('<HHH', 0, 1, 1)  # reserved, type=ICO, count=1
    dir_entry = struct.pack(
        '<BBBBHHII',
        width,            # bWidth（<256 时直接填像素值）
        height,           # bHeight
        0,                # bColorCount
        0,                # bReserved
        1,                # wPlanes
        32,               # wBitCount
        len(image_data),  # dwBytesInRes
        6 + 16,           # dwImageOffset
    )
    return ico_header + dir_entry + image_data


# 预生成 favicon 字节（模块级缓存，避免每次请求重新生成）
_FAVICON_BYTES = _generate_favicon_ico()


@app.get("/favicon.ico")
async def favicon():
    """返回 favicon.ico，避免浏览器请求 404"""
    return Response(content=_FAVICON_BYTES, media_type="image/x-icon")


@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def chrome_devtools_json():
    """Chrome DevTools 自动探测文件，返回空 JSON 避免 404"""
    return JSONResponse(content={})


# 注册路由
app.include_router(auth_router)
app.include_router(home_router)
app.include_router(chat_router)
app.include_router(admin_router)

def main():
    """主函数"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    # 启动时检查更新
    # 默认仅提示有新版本，不自动拉取（避免供应链风险）
    # 需通过环境变量 AUTO_UPDATE=true 才启用自动拉取
    auto_pull = os.environ.get("AUTO_UPDATE", "").lower() == "true"
    if auto_pull:
        logger.warning(
            "⚠️ AUTO_UPDATE=true 已启用自动拉取更新，存在供应链风险，"
            "请确保运行环境可信且更新源已校验。"
        )
    try:
        from updater import check_for_update
        check_for_update(auto_pull=auto_pull)
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
