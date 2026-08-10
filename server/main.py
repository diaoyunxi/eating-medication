#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务端启动脚本
仿照老人端 main.py 的风格：自动检查依赖、创建必要目录、启动服务
"""

import sys
import os
import re
import subprocess
import importlib
import json
import traceback
import logging
from pathlib import Path


# 确保仓库根目录在 sys.path（以便 import common 共享包）
# 注意：必须 append 而非 insert(0)。仓库根目录下存在统一启动入口 main.py，
# 若把根目录排在脚本目录之前，uvicorn 以 "main:app" 重新导入时会解析到
# 根目录的 main.py（其中没有 app 属性），导致 ASGI 应用加载失败。
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))


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


def _in_venv():
    """判断当前解释器是否运行在虚拟环境中（venv/virtualenv 通用判据）"""
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _venv_python_path():
    """返回仓库根 .venv 内 python 解释器路径（按平台区分 Scripts/bin）"""
    project_root = Path(__file__).resolve().parent.parent
    if os.name == "nt":
        return project_root / ".venv" / "Scripts" / "python.exe"
    return project_root / ".venv" / "bin" / "python"


def _clean_pkg_name(line):
    """从 requirements.txt 单行中解析出干净的 PyPI 包名

    去除行内注释、环境标记(;)、extras([...]) 与版本限定符(==/>=/等)，
    例如 `uvicorn[standard]==0.32.0` -> `uvicorn`。
    """
    line = line.split("#", 1)[0].split(";", 1)[0].strip()
    line = re.sub(r"\[.*?\]", "", line)  # 去 extras
    for sep in ("==", ">=", "<=", "~=", "!=", ">", "<"):
        line = line.split(sep, 1)[0]
    return line.strip()


def check_and_install_dependencies():
    """检查 requirements.txt 声明的依赖是否已安装，缺失则调用 common/install.py

    设计要点：
    - 依赖检测直接解析 requirements.txt：任何写入 requirements.txt 的新依赖
      （如 pyotp/qrcode/webauthn）都会自动被检测与安装，无需维护硬编码列表
      （硬编码列表会漏检新依赖，导致启动即 `import` 崩溃）
    - 缺失判定复用 common.install.is_package_installed（import 优先，回退 pip show），
      兼容 Pillow(import PIL)、pydantic-settings(import pydantic_settings) 等
      包名与 import 名不一致的情况，避免误报缺失
    - 安装由 common/install.py 统一完成（自动创建/进入 .venv）
    - 安装完成后用 .venv 解释器重启自身（main 顶部也会在 .venv 存在时优先
      re-exec），避免回到系统 Python 导致下一轮再次误报缺失
    - KeyboardInterrupt 单独捕获，避免误写 crash.log
    """
    from common.install import is_package_installed

    req_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    if not os.path.exists(req_path):
        print(f"未找到 requirements.txt: {req_path}")
        return

    # 解析出全部需检测的 PyPI 包名
    pkg_names = []
    with open(req_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            name = _clean_pkg_name(line)
            if name:
                pkg_names.append(name)

    missing = [n for n in pkg_names if not is_package_installed(n)]

    if not missing:
        return

    print(f"检测到缺失依赖: {missing}")
    print("正在调用common/install.py 安装依赖...")

    # 根目录统一安装脚本，传入本模块 requirements.txt 路径
    project_root = str(Path(__file__).resolve().parent.parent)
    root_install = os.path.join(project_root, "common", "install.py")
    if not os.path.exists(root_install):
        print("未找到common/install.py，请手动安装依赖:")
        print(f"pip install -r {req_path}")
        sys.exit(1)

    # 安装脚本会自动进入 .venv（不存在则创建），依赖装在 .venv 内。
    # 但 subprocess.run 是子进程，不影响当前进程的 sys.executable；
    # 因此安装完成后必须显式用 .venv 的解释器重启自身，否则重启又回到
    # 系统 Python，下一轮再次误报缺失（历史死循环根因）。
    venv_python = _venv_python_path()

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
    # 安装发生在 .venv 内；优先用 .venv 解释器重启，否则维持当前解释器
    if venv_python.exists():
        print(f"正在使用虚拟环境重启服务端: {venv_python}")
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)
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
    """启动 FastAPI 服务（本地监听 HTTP；对外访问方式由 setup.sh / setup.ps1 配置）"""
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
    # 若仓库根 .venv 已存在但当前未在 venv 中运行，优先用 venv 解释器重启自身，
    # 确保依赖检测与全部导入都在 venv 内进行。
    # 修复两类历史问题：
    #   1) 依赖装进 .venv，服务却用系统 Python 启动，导致新依赖（pyotp/qrcode/
    #      webauthn）检测不到、启动即 `import` 崩溃（即「没自动加载 venv 配置」）；
    #   2) 仅当「检测缺失并安装后」才切 venv 不够——系统内已装部分包时会直接跳过，
    #      仍用系统 Python 运行。
    # 本步在任何副作用（更新检查/建目录/启动）之前执行，保证全程位于 venv。
    venv_py = _venv_python_path()
    if venv_py.exists() and not _in_venv():
        try:
            os.execv(str(venv_py), [str(venv_py)] + sys.argv)
        except Exception as e:
            print(f"切换到虚拟环境失败，继续以当前解释器运行: {e}")

    print("老人用药管理智能助手 - 服务端")
    print("=" * 50)

    # 重置运行时数据模式（--reset）：在任何副作用（更新检查 / 建目录 / 启动）之前
    # 执行并退出，删除用户密码库与老人端设备数据等本地文件，
    # 仅保留 .env / config.json / logs，使工作树接近全新 clone 状态
    if "--reset" in sys.argv:
        _root = str(Path(__file__).resolve().parent.parent)
        from updater import reset_runtime_data, confirm_reset
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