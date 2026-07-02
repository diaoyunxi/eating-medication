#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install script for server
不修改全局 pip 配置，通过 -i 参数临时指定镜像源。
建议在虚拟环境中运行。"""

import sys
import subprocess
import os
import importlib


# 默认镜像源（可通过环境变量 PIP_INDEX_URL 覆盖）
PIP_INDEX_URL = os.environ.get("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")


def is_package_installed(pkg_name):
    """检查包是否已安装"""
    package_name = pkg_name.split("~")[0].split(">")[0].split("=")[0].split("<")[0]
    # 服务端依赖的 import 名与包名存在差异时在此映射
    name_mapping = {
        "python-multipart": "multipart",
        "python-dotenv": "dotenv",
        "python-jose": "jose",
    }
    import_name = name_mapping.get(package_name, package_name)
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", package_name],
                capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False


def install_package(pkg):
    """安装单个包，使用 -i 参数临时指定镜像源，不修改全局 pip 配置"""
    pkg_name = pkg.split("~")[0].split(">")[0].split("=")[0].split("<")[0]
    if is_package_installed(pkg_name):
        print("  ", pkg_name, "已安装，跳过")
        return True
    print("  正在安装", pkg_name, "...")
    try:
        cmd = [sys.executable, "-m", "pip", "install", "-i", PIP_INDEX_URL, pkg]
        # Linux 上某些发行版需要此参数以允许 pip 修改系统环境
        if sys.platform.startswith("linux"):
            cmd.append("--break-system-packages")
        subprocess.check_call(cmd)
        print("  ", pkg_name, "安装完成")
        return True
    except subprocess.CalledProcessError as e:
        print("  安装失败", pkg_name, "返回码:", e.returncode)
        print("  提示：建议使用虚拟环境安装依赖：")
        print("    python -m venv venv")
        print("    source venv/bin/activate  # Linux/macOS")
        print("    venv\\Scripts\\activate     # Windows")
        print("    python install.py")
        return False


def install_requirements():
    """安装依赖包"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    req_file = "requirements.txt"
    if not os.path.exists(req_file):
        print("错误：找不到", req_file)
        return False
    print("=" * 50)
    print("正在安装依赖（镜像源:", PIP_INDEX_URL, ")...")
    print("=" * 50)
    packages = []
    with open(req_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                packages.append(line)
    if not packages:
        print("无需安装的包")
        return True
    print()
    print("共", len(packages), "个包:")
    for pkg in packages:
        print("  -", pkg)
    print()
    installed_count = 0
    skipped_count = 0
    failed_count = 0
    for pkg in packages:
        pkg_name = pkg.split("~")[0].split(">")[0].split("=")[0].split("<")[0]
        if is_package_installed(pkg_name):
            print("  ", pkg_name, "已安装，跳过")
            skipped_count += 1
        else:
            if install_package(pkg):
                installed_count += 1
            else:
                failed_count += 1
    print()
    print("=" * 50)
    print("安装结果:")
    print("  新安装:", installed_count)
    print("  已跳过:", skipped_count)
    print("  失败:  ", failed_count)
    print("=" * 50)
    return failed_count == 0


if __name__ == "__main__":
    try:
        print("=" * 60)
        print("    server 安装脚本")
        print("=" * 60)
        print()
        if install_requirements():
            print()
            print("安装完成。")
            print()
            print("下一步:")
            print("  python main.py")
            print()
            print("默认端口: 1059")
        else:
            print()
            print("部分包安装失败。")
    except Exception as e:
        print()
        print("安装脚本失败:", e)
        sys.exit(1)
