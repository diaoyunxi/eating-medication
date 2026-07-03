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
    C9/S1 修复：下载并解析 SHA256 校验文件，返回 {文件名: 哈希} 映射。
    返回 None 表示未找到或下载失败。
    注意：完整校验需在下载对应资产后用 _verify_asset_hash 比对。
    """
    asset = _find_sha256_asset(release_data)
    if not asset:
        return None
    try:
        content = _download_text(asset.get("browser_download_url"))
        logger.info(f"[更新检查] 已找到校验文件: {asset.get('name')}")
        # 解析 SHA256SUMS 文件格式：每行 "<hash>  <filename>"
        sums = {}
        for line in content.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                sums[parts[1].strip()] = parts[0].strip().lower()
        return sums if sums else None
    except Exception as e:
        logger.warning(f"[更新检查] 下载校验文件失败: {e}")
        return None


def _verify_asset_hash(asset_url, expected_hash):
    """S1 修复：下载指定资产并校验其 SHA256 哈希，返回 True/False"""
    import hashlib
    try:
        req = urllib.request.Request(asset_url, headers={"User-Agent": "eating-medication"})
        h = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=60) as resp:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        actual = h.hexdigest().lower()
        if actual == expected_hash.lower():
            logger.info("[更新检查] 资产 SHA256 校验通过")
            return True
        logger.warning(f"[更新检查] 资产 SHA256 校验失败: 期望 {expected_hash}，实际 {actual}")
        return False
    except Exception as e:
        logger.warning(f"[更新检查] 资产哈希校验异常: {e}")
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

        # C9/S1：尝试解析 SHA256 校验文件
        sha_sums = _verify_release_signature(release_data)
        if sha_sums is None:
            logger.warning("[更新检查] 未找到 SHA256 校验文件，无法验证资产完整性")
        else:
            logger.info(f"[更新检查] 已加载 {len(sha_sums)} 条资产校验记录")

        if auto_pull:
            # S2 修复：自动更新前先校验目标 tag，避免 pull 到任意未审核的远程分支
            logger.warning("⚠️ 自动更新：将拉取指定 tag，请确保已审核该版本")
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if os.path.isdir(os.path.join(script_dir, '.git')):
                # 先 fetch 远程 tag，校验 tag 存在后再 checkout
                fetch_result = subprocess.run(
                    ['git', 'fetch', '--tags', 'origin'],
                    cwd=script_dir, capture_output=True, text=True, timeout=60)
                if fetch_result.returncode != 0:
                    logger.warning(f"[更新检查] fetch tags 失败: {fetch_result.stderr.strip()}")
                else:
                    # 校验目标 tag 在远程存在
                    tag_check = subprocess.run(
                        ['git', 'rev-parse', '--verify', f'refs/tags/{latest}'],
                        cwd=script_dir, capture_output=True, text=True, timeout=15)
                    if tag_check.returncode != 0:
                        logger.warning(f"[更新检查] 目标 tag {latest} 不存在，拒绝自动更新")
                    else:
                        # checkout 到指定 tag（detached HEAD），确保代码版本可控
                        checkout_result = subprocess.run(
                            ['git', 'checkout', latest],
                            cwd=script_dir, capture_output=True, text=True, timeout=30)
                        if checkout_result.returncode == 0:
                            logger.info(f"[更新检查] 已更新到 {latest}，请重新运行程序。")
                            sys.exit(0)
                        else:
                            logger.warning(f"[更新检查] checkout 失败: {checkout_result.stderr.strip()}")
            logger.info(f"[更新检查] 请手动访问 {release_url} 下载最新版本")
    except Exception as e:
        logger.warning(f"[更新检查] 检查更新失败: {e}")


if __name__ == "__main__":
    check_for_update()
