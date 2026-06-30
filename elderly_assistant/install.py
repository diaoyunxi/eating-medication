#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import subprocess
import os
import shutil
import importlib

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
        except:
            print('  [FAIL] ' + pkg_name)
            return False

def install_requirements():
    packages = ['pyyaml', 'opencv-python', 'Pillow', 'pyttsx3', 'fuzzywuzzy', 'python-Levenshtein', 'schedule', 'requests', 'playsound3', 'edge-tts', 'pytesseract', 'pinpong']
    for pkg in packages:
        install_package(pkg)

if __name__ == '__main__':
    install_requirements()
    print('[OK] Done')