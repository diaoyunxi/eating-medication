#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install script for family_monitor"""

import sys
import subprocess
import os
import shutil
import importlib


def is_package_installed(pkg_name):
    package_name = pkg_name.split(">")[0].split("=")[0]
    name_mapping = {
        "python-multipart": "multipart",
        "python-dotenv": "dotenv",
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


def check_system_requirements():
    print("=" * 50)
    print("Check environment...")
    print("=" * 50)
    missing = []
    if sys.version_info < (3, 8):
        print("Python version too low, need 3.8+")
        return False
    print("  Python:", sys.version.split()[0])
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True, text=True)
        if result.returncode == 0:
            print("  pip OK:", result.stdout.strip())
        else:
            missing.append("pip")
    except Exception:
        missing.append("pip")
    if missing:
        print("Missing deps:", ", ".join(missing))
        return False
    return True


def get_pip_conf_path():
    if sys.platform == "win32":
        pip_dir = os.path.expanduser("~\pip")
        return os.path.join(pip_dir, "pip.ini")
    else:
        pip_dir = os.path.expanduser("~/.pip")
        return os.path.join(pip_dir, "pip.conf")


def backup_pip_source():
    pip_conf_path = get_pip_conf_path()
    backup_path = pip_conf_path + ".bak"
    tsinghua = "https://pypi.tuna.tsinghua.edu.cn/simple"
    if os.path.exists(pip_conf_path):
        if not os.path.exists(backup_path):
            shutil.copy(pip_conf_path, backup_path)
            print("Backup pip config to", backup_path)
    else:
        pip_dir = os.path.dirname(pip_conf_path)
        if pip_dir:
            os.makedirs(pip_dir, exist_ok=True)
    with open(pip_conf_path, "w", encoding="utf-8") as f:
        f.write("[global]\nindex-url = " + tsinghua + "\n")
    print("Switched pip source to Tsinghua mirror")


def install_package(pkg):
    pkg_name = pkg.split(">")[0].split("=")[0]
    if is_package_installed(pkg_name):
        print("  ", pkg_name, "already installed, skip")
        return True
    print("  Installing", pkg_name, "...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pkg])
        print("  ", pkg_name, "installed")
        return True
    except subprocess.CalledProcessError:
        print("  Trying with --break-system-packages ...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install",
                 "--break-system-packages", pkg])
            print("  ", pkg_name, "installed")
            return True
        except subprocess.CalledProcessError as e2:
            print("  FAILED", pkg_name, "rc:", e2.returncode)
            return False


def install_requirements():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    req_file = "requirements.txt"
    if not os.path.exists(req_file):
        print("ERROR: cannot find", req_file)
        return False
    print("=" * 50)
    print("Installing dependencies ...")
    print("=" * 50)
    packages = []
    with open(req_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                packages.append(line)
    if not packages:
        print("Nothing to install")
        return True
    print()
    print("Total", len(packages), "packages:")
    for pkg in packages:
        print("  -", pkg)
    print()
    installed_count = 0
    skipped_count = 0
    failed_count = 0
    for pkg in packages:
        pkg_name = pkg.split(">")[0].split("=")[0]
        if is_package_installed(pkg_name):
            print("  ", pkg_name, "already installed, skip")
            skipped_count += 1
        else:
            if install_package(pkg):
                installed_count += 1
            else:
                failed_count += 1
    print()
    print("=" * 50)
    print("Summary:")
    print("  newly installed:", installed_count)
    print("  skipped:        ", skipped_count)
    print("  failed:         ", failed_count)
    print("=" * 50)
    return failed_count == 0


if __name__ == "__main__":
    try:
        print("=" * 60)
        print("    family_monitor installer")
        print("=" * 60)
        print()
        if not check_system_requirements():
            sys.exit(1)
        backup_pip_source()
        print()
        if install_requirements():
            print()
            print("Install completed.")
            print()
            print("Next step:")
            print("  python main.py")
            print()
            print("Default port: 4430")
        else:
            print()
            print("Some packages failed.")
    except Exception as e:
        print()
        print("Install script failed:", e)
        sys.exit(1)