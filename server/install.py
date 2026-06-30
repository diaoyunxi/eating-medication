#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import subprocess
import os
import shutil
import importlib

def is_package_installed(pkg_name):
    """检查包是否已安装"""
    package_name = pkg_name.split('>')[0].split('=')[0]
    try:
        importlib.import_module(package_name)
        return True
    except ImportError:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", package_name],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception:
            return False

def get_pip_conf_path():
    """获取 pip 配置文件路径（跨平台）"""
    if sys.platform == "win32":
        pip_dir = os.path.expanduser("~\\pip")
        return os.path.join(pip_dir, "pip.ini")
    else:
        pip_dir = os.path.expanduser("~/.pip")
        return os.path.join(pip_dir, "pip.conf")

def backup_pip_source():
    """备份原 pip 源并切换为清华源"""
    pip_conf_path = get_pip_conf_path()
    backup_path = pip_conf_path + ".bak"
    tsinghua = "https://pypi.tuna.tsinghua.edu.cn/simple"

    if os.path.exists(pip_conf_path):
        if not os.path.exists(backup_path):
            shutil.copy(pip_conf_path, backup_path)
            print(f"已备份原 pip 源至 {backup_path}")
    else:
        pip_dir = os.path.dirname(pip_conf_path)
        if pip_dir:
            os.makedirs(pip_dir, exist_ok=True)

    with open(pip_conf_path, 'w', encoding='utf-8') as f:
        f.write(f"[global]\nindex-url = {tsinghua}\n")
    print("已切换 pip 源为清华源")

def install_package(pkg):
    """安装单个包，返回是否成功"""
    pkg_name = pkg.split('>')[0].split('=')[0]

    if is_package_installed(pkg_name):
        print(f"  ⊘ {pkg_name} 已安装，跳过")
        return True

    print(f"  → 安装 {pkg_name}...")
    try:
        cmd = [sys.executable, "-m", "pip", "install", pkg]
        if sys.platform.startswith("linux"):
            cmd.append("--break-system-packages")
        subprocess.check_call(cmd)
        print(f"  ✓ {pkg_name} 安装成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ✗ {pkg_name} 安装失败，返回码: {e.returncode}")
        return False

def install_requirements():
    """安装依赖包"""
    req_file = "requirements.txt"
    if not os.path.exists(req_file):
        print(f"错误：找不到 {req_file} 文件")
        return False

    print("=" * 50)
    print("检查并安装依赖包...")
    print("=" * 50)

    with open(req_file, 'r',encoding='utf-8') as f:
        packages = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    installed_count = 0
    skipped_count = 0
    failed_count = 0

    for pkg in packages:
        pkg_name = pkg.split('>')[0].split('=')[0]
        if is_package_installed(pkg_name):
            print(f"  ⊘ {pkg_name} 已安装，跳过")
            skipped_count += 1
        else:
            if install_package(pkg):
                installed_count += 1
            else:
                failed_count += 1

    print("\n" + "=" * 50)
    print("安装摘要:")
    print(f"  新安装: {installed_count}")
    print(f"  已跳过: {skipped_count}")
    print(f"  失败:   {failed_count}")
    print("=" * 50)

    return failed_count == 0

if __name__ == "__main__":
    try:
        backup_pip_source()
        if install_requirements():
            print("\n✓ 依赖安装完成！")
            print("\n运行方式: python main.py")
        else:
            print("\n部分依赖安装失败，请检查上面的输出")
    except Exception as e:
        print(f"\n安装脚本执行失败: {e}")
        sys.exit(1)