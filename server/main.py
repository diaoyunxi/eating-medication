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


# 确保仓库根目录在 sys.path（以便 import common 共享包）
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


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


def _database_driver_required():
    """根据 DATABASE_URL 方言判断是否需要 MySQL/PostgreSQL 驱动

    本地 SQLite 场景无需 pymysql / psycopg2，避免误报缺失。
    """
    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("mysql"):
        return [("pymysql", "pymysql")]
    if db_url.startswith("postgresql"):
        return [("psycopg2", "psycopg2-binary")]
    return []


def check_and_install_dependencies():
    """检查关键依赖是否已安装，若缺失则调用公共安装脚本 common/install.py

    设计要点：
    - passlib 已废弃（与 bcrypt 4.x 不兼容，代码改用 bcrypt 原生 API），不再列为必需
    - 数据库驱动按 DATABASE_URL 方言按需检测，SQLite 场景不要求 pymysql/psycopg2
    - 安装在 .venv 中完成后，用 .venv 的解释器重启自身，避免重启又回到系统 Python
      导致下一轮再次误报缺失（修复「每次启动都重装」死循环）
    - KeyboardInterrupt 单独捕获，避免误写 crash.log
    """
    required_modules = [
        ('fastapi', 'fastapi'),
        ('uvicorn', 'uvicorn'),
        ('sqlalchemy', 'sqlalchemy'),
        ('pydantic', 'pydantic'),
        ('dotenv', 'python-dotenv'),
        ('jose', 'python-jose'),
        ('httpx', 'httpx'),
        ('apscheduler', 'apscheduler'),
    ]
    # 远程数据库驱动仅在 DATABASE_URL 指向 MySQL/PostgreSQL 时需要
    required_modules.extend(_database_driver_required())

    missing = []
    for module_name, pip_name in required_modules:
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing.append(pip_name)

    if not missing:
        return

    print(f"检测到缺失依赖: {missing}")
    print("正在调用common/install.py 安装依赖...")

    # 根目录统一安装脚本，传入本模块 requirements.txt 路径
    project_root = str(Path(__file__).resolve().parent.parent)
    root_install = os.path.join(project_root, "common", "install.py")
    req_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    if not os.path.exists(root_install):
        print("未找到common/install.py，请手动安装依赖:")
        print(f"pip install {' '.join(missing)}")
        sys.exit(1)

    # 安装脚本会自动进入 .venv（不存在则创建），依赖装在 .venv 内。
    # 但 subprocess.run 是子进程，不影响当前进程的 sys.executable；
    # 因此安装完成后必须显式用 .venv 的解释器重启自身，否则重启又回到
    # 系统 Python，下一轮再次误报缺失（历史死循环根因）。
    venv_python = os.path.join(project_root, ".venv", "bin", "python")
    if os.name == "nt":
        venv_python = os.path.join(project_root, ".venv", "Scripts", "python.exe")

    try:
        result = subprocess.run(
            [sys.executable, root_install, req_path],
            capture_output=False,
            text=True,
            cwd=project_root,
        )
    except KeyboardInterrupt:
        # 用户中断安装，不应视为崩溃；退出码 128+SIGINT(2)=130
        print("\n安装被用户中断")
        sys.exit(130)
    except Exception as e:
        print(f"自动安装失败: {e}")
        print(f"请手动运行: python {root_install} {req_path}")
        sys.exit(1)

    if result.returncode != 0:
        print("依赖安装可能未完全成功，尝试继续运行...")
        return

    print("依赖安装完成")
    # 安装发生在 .venv 内；若 .venv 解释器存在则用它重启，否则维持当前解释器
    if os.path.exists(venv_python):
        print(f"正在使用虚拟环境重启服务端: {venv_python}")
        os.execv(venv_python, [venv_python] + sys.argv)
    else:
        print("正在重新启动服务端...")
        os.execv(sys.executable, [sys.executable] + sys.argv)


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
        from app.core.bootstrap import bootstrap_config
        bootstrap_config()
        print("已确保 .env 配置文件（含全部必填字段）并完成必填项校验")
    except Exception as e:
        print(f"配置引导失败: {e}")


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
    # host/port 纳入 Settings 统一管理（与 APP_NAME/DEBUG 等一致）
    host = settings.SERVER_HOST
    port = settings.SERVER_PORT

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
        # 用户主动中断（Ctrl+C），属正常退出，不应记录为崩溃
        print("\n\n服务已停止")
        sys.exit(0)
    except SystemExit:
        # sys.exit / os.execv 等显式退出，正常传播，不视为崩溃
        raise
    except BaseException as e:
        print(f"\n启动失败: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()