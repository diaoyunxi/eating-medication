#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务端启动脚本
仿照老人端 main.py 的风格：自动检查依赖、创建必要目录、启动服务
"""

import sys
import os
import secrets
import subprocess
import importlib
import json
import traceback
import logging
from pathlib import Path


def global_exception_handler(exc_type, exc_value, exc_tb):
    """全局未捕获异常处理"""
    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print(f"未捕获的异常:\n{error_msg}")
    try:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        with open(log_dir / 'crash.log', 'a', encoding='utf-8') as f:
            f.write(error_msg)
            f.write("\n")
    except Exception:
        pass

sys.excepthook = global_exception_handler


def check_and_install_dependencies():
    """检查关键依赖是否已安装，若缺失则自动运行 install.py"""
    required_modules = [
        ('fastapi', 'fastapi'),
        ('uvicorn', 'uvicorn'),
        ('sqlalchemy', 'sqlalchemy'),
        ('pydantic', 'pydantic'),
        ('dotenv', 'python-dotenv'),
        ('jose', 'python-jose'),
        ('passlib', 'passlib'),
        ('httpx', 'httpx'),
        ('apscheduler', 'apscheduler'),
    ]

    missing = []
    for module_name, pip_name in required_modules:
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print(f"检测到缺失依赖: {missing}")
        print("正在自动运行 install.py 安装依赖...")

        install_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "install.py")
        if os.path.exists(install_script):
            try:
                result = subprocess.run(
                    [sys.executable, install_script],
                    capture_output=False,
                    text=True,
                    cwd=os.path.dirname(os.path.abspath(__file__))
                )
                if result.returncode != 0:
                    print("依赖安装可能未完全成功，尝试继续运行...")
                else:
                    print("依赖安装完成")
                    print("正在重新启动服务端...")
                    os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception as e:
                print(f"自动安装失败: {e}")
                print("请手动运行: python install.py")
                sys.exit(1)
        else:
            print("未找到 install.py，请手动安装依赖:")
            print(f"pip install {' '.join(missing)}")
            sys.exit(1)


def create_app_dirs():
    """创建服务端所需的目录和默认配置文件"""
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    print(f"已创建数据目录: {data_dir}")

    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    print(f"已创建日志目录: {logs_dir}")

    env_file = Path(".env")
    if not env_file.exists():
        # C2：生产默认 DEBUG=False，SECRET_KEY 用 secrets.token_urlsafe(32) 动态生成
        random_secret = secrets.token_urlsafe(32)
        default_env = (
            "# 服务端配置\n"
            "APP_NAME=老人用药管理系统\n"
            "DEBUG=False\n"
            "API_V1_PREFIX=/api/v1\n"
            "\n"
            "# 数据库\n"
            "DATABASE_URL=sqlite:///./data/elderly_care.db\n"
            "\n"
            "# JWT 密钥（已自动随机生成，请妥善保存）\n"
            f"SECRET_KEY={random_secret}\n"
            "ALGORITHM=HS256\n"
            "ACCESS_TOKEN_EXPIRE_MINUTES=60\n"
            "\n"
            "# CORS 允许的来源（逗号分隔，生产环境必须修改为实际域名）\n"
            "ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000\n"
            "\n"
            "# 路径前缀（Cloudflare 隧道子路径，本地直连设为空）\n"
            "PATH_PREFIX=/eating-medication/server\n"
        )
        env_file.write_text(default_env, encoding='utf-8')
        print("已创建默认 .env 配置文件，已自动生成随机 SECRET_KEY。")
    else:
        print("已找到 .env 配置文件")


def start_server():
    """启动 FastAPI 服务（本地纯 HTTP，HTTPS 由 Cloudflare 隧道边缘处理）"""
    try:
        import uvicorn
        from app.core.config import settings
    except ImportError as e:
        print(f"导入模块失败: {e}")
        print("请确保依赖已正确安装")
        sys.exit(1)

    path_prefix = settings.PATH_PREFIX
    # O2/O3 修复：host/port 从环境变量读取，默认 0.0.0.0:1059
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "1059"))

    print("\n" + "=" * 50)
    print(f"启动 {settings.APP_NAME} 服务端")
    print("=" * 50)
    print(f"  调试模式: {settings.DEBUG}")
    print(f"  数据库: {settings.DATABASE_URL}")
    print(f"  路径前缀: {path_prefix or '(无，根路径)'}")
    print(f"  HTTPS: 由 Cloudflare 隧道边缘自动配置，本地监听 HTTP")
    print(f"  API 文档: http://localhost:{port}/docs")
    print(f"  健康检查: http://localhost:{port}/health")
    print("=" * 50)
    print("\n按 Ctrl+C 停止服务\n")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )


def main():
    """主入口函数"""
    print("老人用药管理智能助手 - 服务端")
    print("=" * 50)

    # 启动时检查更新（启用自动拉取）
    try:
        from updater import check_for_update
        check_for_update(auto_pull=True)
    except Exception as e:
        logging.warning(f"自动更新检查失败: {e}")

    check_and_install_dependencies()
    create_app_dirs()

    try:
        start_server()
    except KeyboardInterrupt:
        print("\n\n服务已停止")
    except Exception as e:
        print(f"\n启动失败: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()