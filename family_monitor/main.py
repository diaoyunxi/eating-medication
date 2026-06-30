#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""子女看护Web端 - 主程序"""

import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
# 这样无论从哪个目录运行，都能正确导入模块
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import uvicorn
import ssl
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    get_user_manager(config.DATA_DIR)

    print("=" * 60)
    print(f" {config.APP_NAME} 启动中...")
    print(f" 服务地址: http://{config.SERVER_HOST}:4430")
    print(f" 老人端地址: {config.ELDERLY_SERVER_URL}")
    print(f" 认证系统: 已启用 (bcrypt加密)")
    print("=" * 60)

    yield

    print("服务已停止")


# 创建FastAPI应用
app = FastAPI(
    title=config.APP_NAME,
    description="子女看护Web端",
    version="2.0.0",
    debug=config.DEBUG,
    lifespan=lifespan
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
if config.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

# 注册路由
app.include_router(auth_router)
app.include_router(home_router)
app.include_router(chat_router)
app.include_router(admin_router)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """认证中间件，保护需要登录的页面"""
    public_paths = ["/login", "/register", "/static", "/favicon.ico"]

    path = request.url.path
    is_public = any(path.startswith(pp) for pp in public_paths)

    request.state.user = None

    if is_public:
        return await call_next(request)

    session_manager = get_session_manager(config.SECRET_KEY)
    session_token = request.cookies.get("session_token")

    if not session_token:
        return RedirectResponse(url="/login", status_code=302)

    session_data = session_manager.verify_session(session_token)
    if not session_data:
        return RedirectResponse(url="/login", status_code=302)

    username = session_data.get("username")
    request.state.user = username

    # 检查admin路径权限
    if path.startswith("/admin"):
        user_manager = get_user_manager(config.DATA_DIR)
        if not user_manager.is_admin(username):
            return RedirectResponse(url="/", status_code=302)

    response = await call_next(request)
    return response


def _cert_has_localhost(cert_path):
    """检查证书 SAN 是否包含 localhost 或 127.0.0.1"""
    import subprocess
    try:
        result = subprocess.run(
            ['openssl', 'x509', '-in', cert_path, '-noout', '-text'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            text = result.stdout.lower()
            return 'localhost' in text or '127.0.0.1' in text
    except Exception:
        pass
    return False


def check_ssl_certificates():
    """检查SSL证书是否存在且有效，优先检测certs文件夹。
    如果证书 SAN 不包含 localhost，则回退 HTTP 模式。"""
    cert_file_config = getattr(config, 'SSL_CERTFILE', '')
    key_file_config = getattr(config, 'SSL_KEYFILE', '')

    # 优先检查环境变量配置的证书
    if cert_file_config and key_file_config:
        if os.path.exists(cert_file_config) and os.path.exists(key_file_config):
            try:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(cert_file_config, key_file_config)
                if _cert_has_localhost(cert_file_config):
                    logger.info(f"找到有效的SSL证书（从配置）: {cert_file_config}")
                    return cert_file_config, key_file_config
                else:
                    logger.info(f"证书不包含 localhost，跳过 HTTPS: {cert_file_config}")
            except Exception as e:
                logger.warning(f"配置的证书文件无效: {e}")

    # 检查项目根目录下的certs文件夹（支持acme.sh等工具生成的证书）
    certs_dir = Path(__file__).resolve().parent.parent / "certs"
    if certs_dir.exists() and certs_dir.is_dir():
        cert_candidates = [
            ("fullchain.cer", "privkey.pem"),
            ("fullchain.cer", "fullchain.key"),
            ("fullchain.cer", "*.key"),
            ("*.cer", "*.key"),
            ("*.crt", "*.key"),
            ("cert.pem", "key.pem"),
            ("server.crt", "server.key"),
        ]

        for cert_pattern, key_pattern in cert_candidates:
            cert_files = list(certs_dir.glob(cert_pattern))
            key_files = list(certs_dir.glob(key_pattern))

            if cert_files and key_files:
                cert_path = str(cert_files[0])
                key_path = str(key_files[0])

                try:
                    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    ctx.load_cert_chain(cert_path, key_path)
                    if _cert_has_localhost(cert_path):
                        logger.info(f"找到有效的SSL证书: {cert_path}")
                        return cert_path, key_path
                    else:
                        logger.info(f"证书不包含 localhost，跳过 HTTPS: {cert_path}")
                except Exception as e:
                    logger.warning(f"证书文件无效 {cert_path}: {e}")
                    continue

    return None, None


def main():
    """主函数"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    # 启动时检查更新（自动更新功能）
    try:
        import os as _os, sys as _sys
        _here = _os.path.dirname(_os.path.abspath(__file__))
        if _here not in _sys.path:
            _sys.path.insert(0, _here)
        from updater import check_for_update
        check_for_update()
    except Exception:
        pass

    cert_file, key_file = check_ssl_certificates()

    if cert_file and key_file:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(cert_file, key_file)

        print("=" * 60)
        print(f" {config.APP_NAME} 启动中...")
        print(f" HTTPS模式")
        print(f" 服务地址: https://{config.SERVER_HOST}:4430")
        print(f" 老人端地址: {config.ELDERLY_SERVER_URL}")
        print(f" 认证系统: 已启用 (bcrypt加密)")
        print(f" SSL证书: {cert_file}")
        print(f" 管理员入口: /admin/administrator/setting")
        print("=" * 60)

        uvicorn.run(
            "main:app",
            host=config.SERVER_HOST,
            port=4430,
            reload=False,
            ssl_certfile=cert_file,
            ssl_keyfile=key_file
        )
    else:
        print("=" * 60)
        print(f" {config.APP_NAME} 启动中...")
        print(f" 服务地址: http://{config.SERVER_HOST}:4430")
        print(f" 老人端地址: {config.ELDERLY_SERVER_URL}")
        print(f" 认证系统: 已启用 (bcrypt加密)")
        print(f" 提示: 放置证书文件到项目目录可启用HTTPS")
        print(f"    支持格式: .pem, .crt, .cer + .key")
        print(f" 管理员入口: /admin/administrator/setting")
        print("=" * 60)

        uvicorn.run(
            "main:app",
            host=config.SERVER_HOST,
            port=4430,
            reload=False
        )


if __name__ == "__main__":
    main()
