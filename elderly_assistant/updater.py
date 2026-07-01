#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动更新检查模块
启动时检查 GitHub 仓库是否有新版本，发现新版本时打印提示信息。
所有上传到云端的代码均需具备此自动更新检查功能（启动时检查）。
"""
import os
import sys
import json
import subprocess
import urllib.request

__version__ = "2.1.0"
GITHUB_REPO = "diaoyunxi/eating-medication"


def _fetch_latest_version():
    """从 GitHub 获取最新版本号（优先 Releases，回退 Tags）"""
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "eating-medication"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("tag_name"), data.get("html_url")
    except Exception as e:
        # 异常不静默吞掉，打印日志便于排查
        print(f"[更新检查] 获取 Releases 失败: {e}")
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/tags"
        req = urllib.request.Request(url, headers={"User-Agent": "eating-medication"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data:
                tag = data[0].get("name")
                return tag, f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}"
    except Exception as e:
        print(f"[更新检查] 获取 Tags 失败: {e}")
    return None, None


def _compare_versions(v1, v2):
    """比较版本号，返回 1(v1>v2) / -1(v1<v2) / 0(相等)"""
    parts1 = v1.lstrip('v').split('.')
    parts2 = v2.lstrip('v').split('.')
    for i in range(max(len(parts1), len(parts2))):
        try:
            a = int(parts1[i]) if i < len(parts1) else 0
            b = int(parts2[i]) if i < len(parts2) else 0
            if a > b:
                return 1
            if a < b:
                return -1
        except ValueError:
            return 0
    return 0


def check_for_update(auto_pull=False):
    """
    启动时检查 GitHub 是否有新版本。
    - 发现新版本时打印提示信息（非阻塞，不强制更新）。
    - auto_pull=True 时，若当前目录是 git 仓库则尝试 git pull 自动更新。
    - 任何异常均静默处理，不影响主程序启动。
    """
    try:
        latest, release_url = _fetch_latest_version()
        if not latest:
            return
        if _compare_versions(latest, __version__) <= 0:
            print(f"[更新检查] 当前版本 v{__version__}，已是最新版本。")
            return
        print("=" * 50)
        print("  发现新版本！")
        print(f"  当前版本: v{__version__}")
        print(f"  最新版本: {latest}")
        print(f"  下载地址: {release_url}")
        print("=" * 50)
        if auto_pull:
            print("⚠️ 警告：自动更新未启用签名校验，存在供应链攻击风险")
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if os.path.isdir(os.path.join(script_dir, '.git')):
                result = subprocess.run(
                    ['git', 'pull'], cwd=script_dir,
                    capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    print("[更新检查] 自动更新成功！请重新运行程序。")
                    sys.exit(0)
                else:
                    print(f"[更新检查] 自动更新失败: {result.stderr.strip()}")
            print(f"[更新检查] 请手动访问 {release_url} 下载最新版本")
    except Exception as e:
        print(f"[更新检查] 检查更新失败: {e}")


if __name__ == "__main__":
    check_for_update()
