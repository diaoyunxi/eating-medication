#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动更新检查与安全更新模块

启动时检查 GitHub 仓库是否有新版本，发现新版本时：
- 默认仅提示，手动更新
- auto_pull=True 时，自动下载 release zip 并安全覆盖

【安全更新机制】
1. 下载 release zip 到临时目录
2. 解压到临时子目录
3. 仅复制非保护文件到项目目录（保护文件列表见 PROTECTED_PATTERNS）
4. 保护文件：.env、config.json、data/、logs/、*.db、*.sqlite* 等运行时数据
5. 重启服务进程（由 systemd / supervisor / 外部脚本管理）

【保护文件清单】
- .env
- config.json
- data/ 整个目录（含数据库、用户数据、会话、缓存）
- logs/ 整个目录
- *.db / *.sqlite / *.sqlite3
- 任何与 .gitignore 中匹配的文件
"""
import os
import sys
import json
import shutil
import zipfile
import tempfile
import hashlib
import subprocess
import urllib.request
import urllib.error
import logging
import fnmatch
from pathlib import Path

__version__ = "2.9"
GITHUB_REPO = "diaoyunxi/eating-medication"

logger = logging.getLogger(__name__)


# ============================================================
# 保护文件配置：自动更新时这些文件/目录不会被覆盖
# ============================================================
# 文件名或目录名（精确匹配）
PROTECTED_NAMES = {
    ".env",
    "config.json",
    "config.yaml",  # 老人端使用
    "data",
    "logs",
    "certs",
    "captures",
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    "device_id.txt",
    "bound_device.json",
    "users.json",
    "sessions.json",
    "elderly_care.db",
}

# 文件名模式（通配符匹配）
PROTECTED_PATTERNS = [
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.key",
    "*.cer",
    "*.crt",
    "*.pem",
    "*.log",
    "*.pid",
    "*.sock",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.dll",
    "*.exe",
    "*.egg-info",
    ".DS_Store",
    "Thumbs.db",
    "*.swp",
    "*.swo",
    "*~",
    "*.tmp",
    "*.bak",
]

# 子目录保护：data/ 与 logs/ 下所有文件均保护
PROTECTED_SUBDIRS = {
    "data",
    "logs",
    "certs",
    "captures",
    "__pycache__",
}


def _is_protected_path(rel_path: str) -> bool:
    """
    判断相对路径是否属于受保护范围
    :param rel_path: 相对于项目根目录的路径（如 'data/users.json' 或 '.env'）
    :return: True 表示应保留，不被覆盖
    """
    parts = rel_path.replace("\\", "/").split("/")
    if not parts:
        return False

    # 顶层文件名/目录名匹配
    top = parts[0]
    if top in PROTECTED_NAMES:
        return True

    # 文件名模式匹配
    filename = parts[-1]
    for pattern in PROTECTED_PATTERNS:
        if fnmatch.fnmatch(filename.lower(), pattern.lower()):
            return True

    # 子目录保护：data/、logs/ 等下的所有文件均保护
    if len(parts) >= 2 and parts[0] in PROTECTED_SUBDIRS:
        return True

    # .git 目录及子文件保护
    if ".git" in parts:
        return True

    return False


# ============================================================
# GitHub API 与版本比较
# ============================================================
def _fetch_latest_release():
    """从 GitHub 获取最新 Release 信息（含资产列表）"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "eating-medication"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _fetch_latest_version():
    """从 GitHub 获取最新版本号（优先 Releases，回退 Tags）"""
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


def _find_release_zip(release_data):
    """在 Release 资产中查找 zip 文件（自动更新用）

    匹配优先级：
    1. 本模块专属包：{模块名}_v*.zip（如 elderly_assistant_v2.9.zip）
       —— 避免误下其他模块的包导致目录错乱
    2. 总包：eating-medication-v*.zip（包含所有模块的总发布包）
    3. 回退：任意 zip（仅当上述均未找到时）
    """
    if not release_data:
        return None
    assets = release_data.get("assets", []) or []
    # 通过 updater.py 所在目录名识别当前模块
    module_name = Path(__file__).resolve().parent.name
    # 优先匹配本模块专属包 "{module_name}_v*.zip"
    for asset in assets:
        name = asset.get("name", "")
        if name.startswith(f"{module_name}_v") and name.endswith(".zip"):
            return asset
    # 次选：总包 "eating-medication-v*.zip"
    for asset in assets:
        name = asset.get("name", "")
        if name.startswith("eating-medication-") and name.endswith(".zip"):
            return asset
    # 回退：任意 zip
    for asset in assets:
        name = asset.get("name", "")
        if name.endswith(".zip"):
            return asset
    return None


def _find_sha256_asset(release_data):
    """在 Release 资产中查找 SHA256SUMS 或 SHA256 校验文件"""
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
    """下载并解析 SHA256 校验文件，返回 {文件名: 哈希} 映射。返回 None 表示未找到或下载失败。"""
    asset = _find_sha256_asset(release_data)
    if not asset:
        return None
    try:
        content = _download_text(asset.get("browser_download_url"))
        logger.info(f"[更新检查] 已找到校验文件: {asset.get('name')}")
        sums = {}
        for line in content.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                sums[parts[1].strip()] = parts[0].strip().lower()
        return sums if sums else None
    except Exception as e:
        logger.warning(f"[更新检查] 下载校验文件失败: {e}")
        return None


def _download_file_with_hash(url, target_path, expected_hash=None):
    """下载文件到 target_path，可选校验 SHA256"""
    h = hashlib.sha256()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "eating-medication"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            with open(target_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
                    f.write(chunk)
    except Exception as e:
        logger.warning(f"[更新检查] 下载文件失败: {e}")
        if os.path.exists(target_path):
            os.remove(target_path)
        return False

    if expected_hash:
        actual = h.hexdigest().lower()
        if actual != expected_hash.lower():
            logger.warning(f"[更新检查] SHA256 校验失败: 期望 {expected_hash}，实际 {actual}")
            os.remove(target_path)
            return False
        logger.info("[更新检查] SHA256 校验通过")
    return True


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


# ============================================================
# 安全更新：解压 zip 并跳过保护文件
# ============================================================
def _safe_extract_zip(zip_path, extract_to):
    """
    安全解压 zip，处理 zip slip 漏洞
    """
    extract_to = Path(extract_to).resolve()
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for member in zf.namelist():
            # 安全检查：防止 zip slip
            member_path = (extract_to / member).resolve()
            if not str(member_path).startswith(str(extract_to)):
                raise ValueError(f"非法 zip 成员路径: {member}")
        zf.extractall(extract_to)


def _copy_file_safe(src: Path, dst: Path):
    """安全复制单个文件，自动创建父目录"""
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except Exception as e:
        logger.warning(f"[更新检查] 复制文件失败 {src} -> {dst}: {e}")
        return False


def _perform_update(zip_path, project_dir):
    """
    执行安全更新：解压 zip 到临时目录，跳过保护文件，复制到项目目录
    :param zip_path: 下载的 release zip 文件路径
    :param project_dir: 项目根目录路径
    :return: (success: bool, updated_count: int, skipped_count: int)
    """
    project_dir = Path(project_dir).resolve()
    zip_path = Path(zip_path).resolve()

    if not zip_path.exists():
        logger.error(f"[更新检查] zip 文件不存在: {zip_path}")
        return False, 0, 0

    # 创建临时解压目录
    tmp_dir = Path(tempfile.mkdtemp(prefix="update_"))
    try:
        logger.info(f"[更新检查] 解压到临时目录: {tmp_dir}")
        _safe_extract_zip(str(zip_path), str(tmp_dir))

        # 查找 zip 内的根目录（GitHub 自动打包时会有一个顶层目录）
        extracted_items = list(tmp_dir.iterdir())
        if len(extracted_items) == 1 and extracted_items[0].is_dir():
            source_root = extracted_items[0]
        else:
            source_root = tmp_dir

        # 修复：release zip 包含整个仓库结构（含 family_monitor/、server/ 等子目录）
        # 当前 updater 在某模块目录内运行（如 server/），project_dir 也是该模块目录
        # 若直接用 source_root，复制时路径会变成 server/server/...，文件放错位置
        # 因此检测 source_root 下是否存在与当前模块同名的子目录，存在则进入该子目录
        current_module_name = Path(__file__).resolve().parent.name
        module_subdir = source_root / current_module_name
        if module_subdir.is_dir():
            source_root = module_subdir
            logger.info(f"[更新检查] 检测到模块子目录 {current_module_name}/，使用: {source_root}")

        logger.info(f"[更新检查] 源根目录: {source_root}")

        # 备份关键保护文件路径（用于回滚，尽管概率低）
        updated_count = 0
        skipped_count = 0

        # 遍历源目录的所有文件
        for src_file in source_root.rglob("*"):
            if not src_file.is_file():
                continue

            # 计算相对路径
            try:
                rel_path = src_file.relative_to(source_root)
            except ValueError:
                continue

            rel_str = str(rel_path).replace("\\", "/")

            # 检查是否保护
            if _is_protected_path(rel_str):
                logger.debug(f"[更新检查] 跳过保护文件: {rel_str}")
                skipped_count += 1
                continue

            # 目标路径
            dst_file = project_dir / rel_path

            # 再次检查目标路径是否在保护目录内
            try:
                dst_rel = dst_file.relative_to(project_dir)
            except ValueError:
                continue

            if _is_protected_path(str(dst_rel).replace("\\", "/")):
                logger.debug(f"[更新检查] 目标路径被保护，跳过: {dst_rel}")
                skipped_count += 1
                continue

            # 复制文件
            if _copy_file_safe(src_file, dst_file):
                updated_count += 1
            else:
                skipped_count += 1

        logger.info(f"[更新检查] 更新完成: 复制 {updated_count} 个文件，跳过 {skipped_count} 个保护文件")
        return True, updated_count, skipped_count

    except Exception as e:
        logger.error(f"[更新检查] 更新过程出错: {e}")
        return False, 0, 0
    finally:
        # 清理临时目录
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _restart_service():
    """尝试重启服务（通过 systemd 或 supervisor）"""
    service_name = None
    # 探测可能的服务名
    for name in ["eating-medication-server", "eating-medication-family", "eating-medication"]:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            service_name = name
            break

    if service_name:
        logger.info(f"[更新检查] 检测到 systemd 服务: {service_name}，尝试重启")
        result = subprocess.run(
            ["systemctl", "restart", service_name],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            logger.info(f"[更新检查] 服务 {service_name} 已重启")
            return True
        else:
            logger.warning(f"[更新检查] 重启服务失败: {result.stderr.strip()}")
    else:
        logger.info("[更新检查] 未检测到 systemd 服务，请手动重启应用")
    return False


# ============================================================
# 入口
# ============================================================
def check_for_update(auto_pull=False):
    """
    启动时检查 GitHub 是否有新版本。
    - auto_pull 默认 False：仅打印提示
    - auto_pull=True：下载 release zip 并安全覆盖（跳过保护文件）

    【安全机制】
    1. 不使用 git checkout，避免误删未被跟踪的配置文件
    2. 下载 zip 到临时目录，解压后逐文件判断
    3. 保护文件（.env、config.json、data/、logs/、*.db 等）不会被覆盖
    4. 可选 SHA256 校验确保资产完整性
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

        # 解析 SHA256 校验
        sha_sums = _verify_release_signature(release_data)
        if sha_sums is None:
            logger.warning("[更新检查] 未找到 SHA256 校验文件，无法验证资产完整性")
        else:
            logger.info(f"[更新检查] 已加载 {len(sha_sums)} 条资产校验记录")

        if not auto_pull:
            logger.info(f"[更新检查] 自动更新未启用，请手动访问 {release_url} 下载最新版本")
            logger.info("[更新检查] 提示：设置 auto_pull=True 可启用安全自动更新（保留配置文件与数据库）")
            return

        # 自动更新流程
        logger.warning("⚠️ 自动更新：将下载并安装新版本")
        logger.info("[更新检查] 保护文件将保留：.env、config.json、data/、logs/、*.db 等")

        zip_asset = _find_release_zip(release_data)
        if not zip_asset:
            logger.error("[更新检查] 未在 Release 资产中找到 zip 文件，无法自动更新")
            logger.info(f"[更新检查] 请手动访问 {release_url} 下载")
            return

        zip_url = zip_asset.get("browser_download_url")
        zip_name = zip_asset.get("name", "update.zip")
        logger.info(f"[更新检查] 准备下载: {zip_name}")

        # 创建临时目录存放 zip
        tmp_zip_dir = Path(tempfile.mkdtemp(prefix="upd_zip_"))
        tmp_zip_path = tmp_zip_dir / zip_name

        try:
            # 获取期望的 SHA256
            expected_hash = None
            if sha_sums and zip_name in sha_sums:
                expected_hash = sha_sums[zip_name]

            # 下载 zip
            if not _download_file_with_hash(zip_url, str(tmp_zip_path), expected_hash):
                logger.error("[更新检查] 下载失败")
                return

            # 执行安全更新
            project_dir = Path(__file__).resolve().parent
            success, updated, skipped = _perform_update(str(tmp_zip_path), str(project_dir))

            if success:
                logger.info(f"[更新检查] 自动更新成功！更新了 {updated} 个文件，保护了 {skipped} 个文件")
                logger.info("[更新检查] 尝试重启服务...")
                if _restart_service():
                    logger.info("[更新检查] 服务已重启，更新完成")
                else:
                    logger.info("[更新检查] 请手动重启服务以应用更新")
            else:
                logger.error("[更新检查] 自动更新失败，请手动更新")
                logger.info(f"[更新检查] 手动下载地址: {release_url}")

        finally:
            # 清理临时 zip
            try:
                shutil.rmtree(tmp_zip_dir, ignore_errors=True)
            except Exception:
                pass

    except Exception as e:
        logger.warning(f"[更新检查] 检查更新失败: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    check_for_update()
