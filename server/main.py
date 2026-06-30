#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务端启动脚本
仿照老人端 main.py 的风格：自动检查依赖、创建必要目录、启动服务
"""

import sys
import os
import subprocess
import importlib
import json
import traceback
import logging
import ssl
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
    except:
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
        default_env = (
            "# 服务端配置\n"
            "APP_NAME=老人用药管理系统\n"
            "DEBUG=True\n"
            "API_V1_PREFIX=/api/v1\n"
            "\n"
            "# 数据库\n"
            "DATABASE_URL=sqlite:///./data/elderly_care.db\n"
            "\n"
            "# JWT 密钥（生产环境请务必修改）\n"
            "SECRET_KEY=your-secret-key-change-this-in-production\n"
            "ALGORITHM=HS256\n"
            "ACCESS_TOKEN_EXPIRE_MINUTES=10080\n"
            "\n"
            "# WebSocket 心跳间隔（秒）\n"
            "WS_HEARTBEAT_INTERVAL=30\n"
            "\n"
            "# SSL证书配置（可选，支持 .pem, .crt, .cer, .key 等格式）\n"
            "# SSL_CERTFILE=certs/server.crt\n"
            "# SSL_KEYFILE=certs/server.key\n"
        )
        env_file.write_text(default_env, encoding='utf-8')
        print("已创建默认 .env 配置文件，请根据实际情况修改里面的 SECRET_KEY。")
    else:
        print("已找到 .env 配置文件")


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
    cert_file_env = os.getenv('SSL_CERTFILE')
    key_file_env = os.getenv('SSL_KEYFILE')

    # 优先检查环境变量配置的证书
    if cert_file_env and key_file_env:
        if os.path.exists(cert_file_env) and os.path.exists(key_file_env):
            try:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(cert_file_env, key_file_env)
                if _cert_has_localhost(cert_file_env):
                    print(f"  找到有效的SSL证书（从配置）: {cert_file_env}")
                    return cert_file_env, key_file_env
                else:
                    print(f"  证书不包含 localhost，跳过 HTTPS: {cert_file_env}")
            except Exception as e:
                print(f"  配置的证书文件无效: {e}")

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
                        print(f"  找到有效的SSL证书: {cert_path}")
                        return cert_path, key_path
                    else:
                        print(f"  证书不包含 localhost，跳过 HTTPS: {cert_path}")
                except Exception as e:
                    print(f"  证书文件无效 {cert_path}: {e}")
                    continue

    return None, None


def start_server():
    """启动 FastAPI 服务"""
    try:
        import uvicorn
        from app.core.config import settings
    except ImportError as e:
        print(f"导入模块失败: {e}")
        print("请确保依赖已正确安装")
        sys.exit(1)

    cert_file, key_file = check_ssl_certificates()

    print("\n" + "=" * 50)
    print(f"启动 {settings.APP_NAME} 服务端")
    print("=" * 50)
    print(f"  调试模式: {settings.DEBUG}")
    print(f"  数据库: {settings.DATABASE_URL}")

    if cert_file and key_file:
        print(f"  HTTPS模式")
        print(f"  API 文档: https://localhost:1059/docs")
        print(f"  健康检查: https://localhost:1059/health")
        print(f"  SSL证书: {cert_file}")
    else:
        print(f"  API 文档: http://localhost:1059/docs")
        print(f"  健康检查: http://localhost:1059/health")
        print(f"  提示: 放置证书文件到项目目录可启用HTTPS")
        print(f"     支持格式: .pem, .crt, .cer + .key")

    print("=" * 50)
    print("\n按 Ctrl+C 停止服务\n")

    if cert_file and key_file:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=1059,
            reload=False,
            log_level="info",
            ssl_certfile=cert_file,
            ssl_keyfile=key_file
        )
    else:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=1059,
            reload=False,
            log_level="info"
        )


def main():
    """主入口函数"""
    print("老人用药管理智能助手 - 服务端")
    print("=" * 50)

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