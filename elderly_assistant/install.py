#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import subprocess
import os
import shutil
import importlib


def read_requirements():
    """读取 requirements.txt 解析依赖包列表（跳过空行与注释行）"""
    req_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'requirements.txt')
    packages = []
    with open(req_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                packages.append(line)
    return packages


def is_package_installed(pkg_name):
    package_name = pkg_name.split('>')[0].split('=')[0].replace('-', '_')
    try:
        importlib.import_module(package_name)
        return True
    except ImportError:
        try:
            result = subprocess.run([sys.executable, '-m', 'pip', 'show', pkg_name.split('>')[0].split('=')[0]], capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False

def install_package(pkg):
    pkg_name = pkg.split('>')[0].split('=')[0]
    if is_package_installed(pkg_name):
        return True
    print('  [INSTALL] ' + pkg_name)
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])
        return True
    except subprocess.CalledProcessError:
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--break-system-packages', pkg])
            return True
        except Exception:
            print('  [FAIL] ' + pkg_name)
            return False

def install_requirements():
    # 不再硬编码依赖列表，统一从 requirements.txt 读取
    packages = read_requirements()
    for pkg in packages:
        install_package(pkg)

if __name__ == '__main__':
    install_requirements()
    print('[OK] Done')