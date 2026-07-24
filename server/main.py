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
    """创建服务端所需的目录和默认配置文件

    .env 的完整生成与缺失字段补齐统一由 app.core.config._ensure_default_env() 负责，
    避免此处再维护一份「精简版」模板，从而遗漏 Cloudflare Turnstile / GitHub OAuth 等必填字段。
    """
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    print(f"已创建数据目录: {data_dir}")

    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    print(f"已创建日志目录: {logs_dir}")

    # 确保 .env 存在且包含全部必填字段：
    # - 首次运行写入完整模板（含 Turnstile / GitHub OAuth / AI / OCR / CORS 等）
    # - 已存在但缺失关键字段时自动补齐（兼容旧版字段不全的存量 .env）
    try:
        from app.core.config import _ensure_default_env
        _ensure_default_env()
        print("已确保 .env 配置文件（含全部必填字段）")
    except Exception as e:
        print(f"确保 .env 配置文件失败: {e}")


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
    # host/port 优先从环境变量读取，便于部署时覆盖，默认 0.0.0.0:1059
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

    # 重置运行时数据模式（--reset）：在任何副作用（更新检查 / 建目录 / 启动）之前
    # 执行并退出，删除用户密码库与老人端设备数据等本地文件，
    # 仅保留 .env / config.json / logs，使工作树接近全新 clone 状态
    if "--reset" in sys.argv:
        _root = str(Path(__file__).resolve().parent.parent)
        from reset_runtime import reset_runtime_data, confirm_reset
        print("=" * 60)
        print(" 重置运行时数据模式 (--reset)")
        if not confirm_reset():
            print(" 已取消，未做任何修改。")
            sys.exit(0)
        deleted, skipped = reset_runtime_data(_root)
        print(f" 已删除 {len(deleted)} 项运行时文件 / 目录：")
        for p in deleted:
            print("   -", p)
        if skipped:
            print(f" 跳过 {len(skipped)} 项（删除失败）：")
            for p in skipped:
                print("   !", p)
        print(" 已保留: .env / config.json / logs/")
        print(" 工作树现已接近全新 clone 状态（仅上述三项差异）。")
        print("=" * 60)
        sys.exit(0)

    # 启动时检查更新（启用自动拉取）
    try:
        # 统一 updater.py 已迁移至仓库根目录，确保根目录在 sys.path 中
        _root = str(Path(__file__).resolve().parent.parent)
        if _root not in sys.path:
            sys.path.insert(0, _root)
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