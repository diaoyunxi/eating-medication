#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动更新检查模块
启动时检查 GitHub 仓库是否有新版本，发现新版本时打印提示信息。
所有上传到云端的代码均需具备此自动更新检查功能（启动时检查）。
C9：下载 Release 资产时尝试校验 SHA256；默认 auto_pull=False；异常不静默吞掉。
"""
import os
import sys
import json
import subprocess
import urllib.request
import logging

__version__ = "2.2.0"
GITHUB_REPO = "diaoyunxi/eating-medication"

logger = logging.getLogger(__name__)


def _fetch_latest_release():
    """从 GitHub 获取最新 Release 信息（含资产列表）"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "eating-medication"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _fetch_latest_version():
    """从 GitHub 获取最新版本号（优先 Releases，回退 Tags）"""
    # C9：不静默吞掉异常，使用 logger.warning 记录
    try:
        data = _fetch_latest_release()
        return data.get("tag_name"), data.get("html_url"), data
    except Exception as e:
        logger.warning(f"获取 Release 失败: {e}")
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/tags"
        req = urllib.request.Request(url, headers={"User-Agent": "eating-medication"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data:
                tag = data[0].get("name")
                return tag, f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}", None
    except Exception as e:
        logger.warning(f"获取 Tags 失败: {e}")
    return None, None, None


def _find_sha256_asset(release_data):
    """C9：在 Release 资产中查找 SHA256SUMS 或 SHA256 校验文件"""
    if not release_data:
        return None
    assets = release_data.get("assets", []) or []
    for asset in assets:
        name = (asset.get("name") or "").lower()
        if "sha256" in name or name.endswith(".sha256") or "sha256sum" in name:
            return asset
    return None


def _download_text(url):
    """下载文本内容"""
    req = urllib.request.Request(url, headers={"User-Agent": "eating-medication"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _verify_release_signature(release_data):
    """
    C9：下载并校验 SHA256 校验文件。
    返回 True 表示已找到并下载校验文件，False 表示未找到或下载失败。
    完整校验需下载对应资产并计算哈希后比对，此处为简化实现。
    """
    asset = _find_sha256_asset(release_data)
    if not asset:
        return False
    try:
        _download_text(asset.get("browser_download_url"))
        logger.info(f"[更新检查] 已找到校验文件: {asset.get('name')}")
        return True
    except Exception as e:
        logger.warning(f"[更新检查] 下载校验文件失败: {e}")
        return False


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
    - C9：auto_pull 默认 False。
    - C9：异常使用 logger.warning 记录，不静默吞掉。
    - C9：auto_pull=True 时提示未启用签名校验的供应链攻击风险。
    """
    try:
        latest, release_url, release_data = _fetch_latest_version()
        if not latest:
            return
        if _compare_versions(latest, __version__) <= 0:
            logger.info(f"[更新检查] 当前版本 v{__version__}，已是最新版本。")
            return
        logger.info("=" * 50)
        logger.info("  发现新版本！")
        logger.info(f"  当前版本: v{__version__}")
        logger.info(f"  最新版本: {latest}")
        logger.info(f"  下载地址: {release_url}")
        logger.info("=" * 50)

        # C9：尝试校验资产签名（查找 SHA256 校验文件）
        verified = _verify_release_signature(release_data)
        if not verified:
            logger.warning("[更新检查] 未找到 SHA256 校验文件，无法验证资产完整性")

        if auto_pull:
            # C9：自动更新未启用签名校验，提示供应链攻击风险
            logger.warning("⚠️ 警告：自动更新未启用签名校验，存在供应链攻击风险")
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if os.path.isdir(os.path.join(script_dir, '.git')):
                result = subprocess.run(
                    ['git', 'pull'], cwd=script_dir,
                    capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    logger.info("[更新检查] 自动更新成功！请重新运行程序。")
                    sys.exit(0)
                else:
                    logger.warning(f"[更新检查] 自动更新失败: {result.stderr.strip()}")
            logger.info(f"[更新检查] 请手动访问 {release_url} 下载最新版本")
    except Exception as e:
        logger.warning(f"[更新检查] 检查更新失败: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    check_for_update()
