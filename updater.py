#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
项目级自动更新检查与安全更新模块（统一位于仓库根目录）

启动时检查 GitHub 仓库是否有新版本，发现新版本时：
- 默认启用安全自动更新（可由项目根目录 config.json 的 auto_pull 字段关闭）
- auto_pull=False 时，仅提示、手动更新

【与旧版（各模块内 updater.py）的区别】
1. 仅从 GitHub Release 拉取「完整发布包」 eating-medication-vX.Y.Z.zip 及其 SHA256
   校验文件；不再单独处理各模块分包（如 server_v*.zip / family_monitor_v*.zip）。
2. 读取仓库根目录 config.json 的 github_proxy 字段，通过该代理/镜像下载
   （兼容 gh-proxy.com 镜像前缀形式，亦兼容 http(s)://host:port 正向代理）。

【安全更新机制】
1. 下载 release 完整 zip 到临时目录
2. 解压到临时子目录
3. 仅复制非保护文件到项目根目录（保护文件列表见 PROTECTED_PATTERNS）
4. 保护文件：.env、config.json、data/、logs/、*.db、*.sqlite* 等运行时数据
5. 更新失败时自动回滚到备份
6. 更新后尝试重启相关 systemd 服务

【保护文件清单】
- .env（含 server/.env、family_monitor/.env 等嵌套路径）
- config.json、config.yaml
- data/ 整个目录（含数据库、用户数据、会话、缓存）
- logs/ 整个目录
- *.db / *.sqlite / *.sqlite3
- 任何与 .gitignore 中匹配的文件
"""
import os
import sys
import json
import time
import shutil
import zipfile
import tempfile
import hashlib
import subprocess
import logging
import fnmatch
from pathlib import Path
from urllib.parse import urlparse
import urllib.request
import urllib.error

# ============================================================
# 版本与仓库常量
# ============================================================
def _load_version():
    """从仓库根目录 VERSION 文件读取版本号（避免版本号写死在代码中）。

    :return: 版本号字符串；缺失时回退 "0.0.0"
    """
    version_file = Path(__file__).resolve().parent / "VERSION"
    try:
        if version_file.is_file():
            ver = version_file.read_text(encoding="utf-8").strip()
            if ver:
                return ver
    except Exception:
        pass
    return "0.0.0"


__version__ = _load_version()
GITHUB_REPO = "diaoyunxi/eating-medication"

logger = logging.getLogger(__name__)


# ============================================================
# GitHub 请求头（注入可选 PAT 提升速率限制）
# ============================================================
def _gh_headers():
    """构建 GitHub API 请求头，优先注入 PAT 提升速率限制并认证"""
    headers = {"User-Agent": "eating-medication-updater"}
    gh_token = os.environ.get("GITHUB_TOKEN")
    if gh_token:
        headers["Authorization"] = f"token {gh_token}"
    return headers


# ============================================================
# 代理配置：读取仓库根目录 config.json 的 github_proxy 字段
# ============================================================
def _load_github_proxy():
    """读取仓库根目录 config.json 的 github_proxy 字段。

    支持两种形式：
    1. 镜像前缀（如 https://gh-proxy.com）：下载 URL 改写为 {proxy}/{原始URL}
    2. 正向代理（如 http://127.0.0.1:7890）：通过 urllib ProxyHandler 透明转发
    未配置或文件不存在时返回 None，走直连。
    """
    config_path = Path(__file__).resolve().parent / "config.json"
    try:
        if config_path.is_file():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            proxy = data.get("github_proxy")
            if isinstance(proxy, str) and proxy.strip():
                return proxy.strip()
    except Exception as e:
        logger.warning(f"[更新检查] 读取 config.json 的 github_proxy 失败: {e}")
    return None


_GITHUB_PROXY = _load_github_proxy()


# ============================================================
# 自动更新开关：读取仓库根目录 config.json 的 auto_pull 字段
# ============================================================
def _load_auto_pull():
    """读取仓库根目录 config.json 的 auto_pull 字段，决定是否启用安全自动更新。

    优先级：config.json 的 auto_pull 字段 > 缺省值 True。
    - 文件不存在 / 字段缺失 / 解析失败：回退 True（默认启用安全自动更新）
    - 支持 bool 值与字符串 "true"/"false"（大小写不敏感）解析
    """
    config_path = Path(__file__).resolve().parent / "config.json"
    try:
        if config_path.is_file():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            val = data.get("auto_pull", True)
            if isinstance(val, bool):
                return val
            if isinstance(val, str) and val.strip():
                return val.strip().lower() == "true"
            logger.warning(f"[更新检查] config.json 的 auto_pull 类型无效（{type(val).__name__}），回退为 True")
            return True
    except Exception as e:
        logger.warning(f"[更新检查] 读取 config.json 的 auto_pull 失败: {e}，回退为 True")
    return True


_AUTO_PULL = _load_auto_pull()


def _configure_opener():
    """根据 github_proxy 构建 urllib opener，返回 (opener, is_mirror, mirror_base)。"""
    proxy = _GITHUB_PROXY
    if not proxy:
        return urllib.request.build_opener(), False, None
    parsed = urlparse(proxy)
    # 正向代理：仅 scheme + netloc，无路径（如 http://127.0.0.1:7890）
    if parsed.scheme in ("http", "https") and parsed.netloc and parsed.path in ("", "/"):
        handler = urllib.request.ProxyHandler({parsed.scheme: proxy})
        return urllib.request.build_opener(handler), False, None
    # 镜像前缀形式（如 https://gh-proxy.com）
    base = proxy.rstrip("/")
    return urllib.request.build_opener(), True, base


_OPENER, _IS_MIRROR, _MIRROR_BASE = _configure_opener()


def _build_url(url):
    """若配置了镜像前缀形式的 github_proxy，将目标 URL 改写为通过镜像访问。"""
    if _IS_MIRROR and _MIRROR_BASE:
        return f"{_MIRROR_BASE}/{url}"
    return url


def _open_url(url, timeout, headers=None):
    """发起 HTTP 请求，自动套用 github_proxy（镜像前缀或正向代理）。"""
    target = _build_url(url)
    req = urllib.request.Request(target, headers=headers or _gh_headers())
    return _OPENER.open(req, timeout=timeout)


# ============================================================
# 保护文件配置：自动更新时这些文件/目录不会被覆盖
# ============================================================
# 文件名或目录名（精确匹配，任意一级路径段命中即保护）
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

# 文件名模式（通配符匹配，仅对文件名本身）
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
    """判断相对路径是否属于受保护范围。

    完整发布包解压后路径形如 server/.env、family_monitor/config.json、
    server/data/db.sqlite，因此需对任意一级路径段做受保护判定，
    避免嵌套的 .env / config.json / data/ 等被覆盖。
    """
    parts = rel_path.replace("\\", "/").split("/")
    if not parts:
        return False
    filename = parts[-1]
    # 任意一级路径段为受保护文件名/目录名
    for part in parts:
        if part in PROTECTED_NAMES:
            return True
    # 文件名模式匹配
    for pattern in PROTECTED_PATTERNS:
        if fnmatch.fnmatch(filename.lower(), pattern.lower()):
            return True
    # 子目录保护：data/、logs/ 等下的所有文件均保护
    for sub in PROTECTED_SUBDIRS:
        if sub in parts:
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
    with _open_url(url, 10) as resp:
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
        with _open_url(url, 10) as resp:
            data = json.loads(resp.read().decode())
            if data:
                tag = data[0].get("name")
                return tag, f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}", None
    except Exception as e:
        logger.warning(f"获取 Tags 失败: {e}")
    return None, None, None


def _find_release_zip(release_data):
    """在 Release 资产中查找「完整发布包」zip 文件。

    仅匹配 eating-medication-*.zip（如 eating-medication-v2.12.4.zip），
    不再匹配各模块分包（如 server_v*.zip），确保统一拉取整体发布包。
    """
    if not release_data:
        return None
    assets = release_data.get("assets", []) or []
    for asset in assets:
        name = asset.get("name", "")
        if name.startswith("eating-medication-") and name.endswith(".zip"):
            return asset
    return None


def _find_sha256_assets(release_data):
    """在 Release 资产中查找完整发布包的 SHA256 校验文件（*.sha256）。"""
    if not release_data:
        return []
    assets = release_data.get("assets", []) or []
    return [a for a in assets if (a.get("name") or "").lower().endswith(".sha256")]


def _download_text(url):
    """下载文本内容"""
    with _open_url(url, 15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _verify_release_signature(release_data):
    """下载并解析所有 SHA256 校验文件，合并返回 {文件名: 哈希} 映射。

    返回 None 表示未找到任何校验文件或全部下载失败。
    """
    sha_assets = _find_sha256_assets(release_data)
    if not sha_assets:
        return None
    sums = {}
    found_names = []
    for asset in sha_assets:
        try:
            content = _download_text(asset.get("browser_download_url"))
            found_names.append(asset.get("name"))
            for line in content.strip().splitlines():
                parts = line.split(None, 1)
                if len(parts) == 2:
                    sums[parts[1].strip()] = parts[0].strip().lower()
        except Exception as e:
            logger.warning(f"[更新检查] 下载校验文件失败 {asset.get('name')}: {e}")
    if found_names:
        logger.info(f"[更新检查] 已找到校验文件: {', '.join(found_names)}")
    return sums if sums else None


def _download_file_with_hash(url, target_path, expected_hash=None):
    """下载文件到 target_path，可选校验 SHA256"""
    h = hashlib.sha256()
    try:
        with _open_url(url, 300) as resp:
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

    if not expected_hash:
        logger.warning("[更新检查] 缺少期望哈希，拒绝未校验的下载")
        if os.path.exists(target_path):
            os.remove(target_path)
        return False
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
    """安全解压 zip，处理 zip slip 漏洞"""
    extract_to = Path(extract_to).resolve()
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for member in zf.namelist():
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
    """执行安全更新：解压完整发布包到临时目录，跳过保护文件，复制到项目根目录。

    :param zip_path: 下载的 release 完整 zip 文件路径
    :param project_dir: 项目根目录路径（即本 updater.py 所在目录）
    :return: (success: bool, updated_count: int, skipped_count: int)
    """
    project_dir = Path(project_dir).resolve()
    zip_path = Path(zip_path).resolve()

    if not zip_path.exists():
        logger.error(f"[更新检查] zip 文件不存在: {zip_path}")
        return False, 0, 0

    # 创建临时解压目录
    tmp_dir = Path(tempfile.mkdtemp(prefix="update_"))
    # 更新前备份整个项目目录，便于失败时回滚
    backup_dir = f"{project_dir}.bak.{int(time.time())}"
    shutil.copytree(project_dir, backup_dir)
    try:
        logger.info(f"[更新检查] 解压到临时目录: {tmp_dir}")
        _safe_extract_zip(str(zip_path), str(tmp_dir))

        # 完整发布包顶层即为各模块目录（server/、family_monitor/、elderly_assistant/）
        # 及 VERSION、README.md、deploy/ 等仓库文件，直接以解压目录为源根
        extracted_items = list(tmp_dir.iterdir())
        if len(extracted_items) == 1 and extracted_items[0].is_dir():
            source_root = extracted_items[0]
        else:
            source_root = tmp_dir

        logger.info(f"[更新检查] 源根目录: {source_root}")

        updated_count = 0
        skipped_count = 0

        # 遍历源目录的所有文件
        for src_file in Path(source_root).rglob("*"):
            if not src_file.is_file():
                continue

            # 计算相对路径
            try:
                rel_path = src_file.relative_to(Path(source_root))
            except ValueError:
                continue

            rel_str = str(rel_path).replace("\\", "/")

            # 检查是否保护（源路径视角）
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

        # 校验关键文件存在，确认更新完整性
        if not (project_dir / "updater.py").exists():
            raise RuntimeError("更新后 updater.py 缺失")

        logger.info(f"[更新检查] 更新完成: 复制 {updated_count} 个文件，跳过 {skipped_count} 个保护文件")
        # 更新成功，清理备份
        shutil.rmtree(backup_dir, ignore_errors=True)
        logger.info("[更新] 完成，已清理备份")
        return True, updated_count, skipped_count

    except Exception as e:
        logger.error(f"[更新] 失败，回滚: {e}")
        # 回滚：用备份恢复项目目录
        shutil.rmtree(project_dir, ignore_errors=True)
        shutil.move(backup_dir, str(project_dir))
        return False, 0, 0
    finally:
        # 清理临时目录
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _restart_service():
    """尝试重启所有处于 active 状态的相关 systemd 服务。

    完整发布包会同时更新多个模块，因此重启所有被检测到的服务。
    """
    service_names = [
        "eating-medication-server",
        "eating-medication-family",
        "eating-medication",
    ]
    restarted = []
    for name in service_names:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", name],
                capture_output=True, text=True, timeout=5
            )
        except Exception:
            continue
        if result.returncode == 0:
            logger.info(f"[更新检查] 检测到 systemd 服务: {name}，尝试重启")
            r = subprocess.run(
                ["systemctl", "restart", name],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                restarted.append(name)
                logger.info(f"[更新检查] 服务 {name} 已重启")
            else:
                logger.warning(f"[更新检查] 重启服务 {name} 失败: {r.stderr.strip()}")
    if restarted:
        return True
    logger.info("[更新检查] 未检测到 systemd 服务，请手动重启应用")
    return False


# ============================================================
# 入口
# ============================================================
def check_for_update(auto_pull=None):
    """
    启动时检查 GitHub 是否有新版本。
    - auto_pull 默认由 config.json 控制（缺省 True）：启用安全自动更新
    - auto_pull=False：仅打印提示，手动更新
    - 显式传入 auto_pull 可覆盖 config.json 配置与默认值

    【安全机制】
    1. 不使用 git checkout，避免误删未被跟踪的配置文件
    2. 下载 zip 到临时目录，解压后逐文件判断
    3. 保护文件（.env、config.json、data/、logs/、*.db 等）不会被覆盖
    4. SHA256 校验确保资产完整性（缺少校验文件时拒绝自动更新）
    """
    # 未显式指定时，使用 config.json 配置（缺省 True）
    if auto_pull is None:
        auto_pull = _AUTO_PULL
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
            logger.info("[更新检查] 提示：如需启用安全自动更新，可在 config.json 设置 auto_pull: true（保留配置文件与数据库）")
            return

        # 自动更新流程：缺少校验文件时拒绝自动更新（安全要求）
        if sha_sums is None:
            logger.error("[更新检查] 未找到SHA256校验文件，出于安全考虑拒绝自动更新")
            logger.info(f"[更新检查] 请手动访问 {release_url} 下载并人工校验")
            return

        logger.warning("⚠️ 自动更新：将下载并安装新版本")
        logger.info("[更新检查] 保护文件将保留：.env、config.json、data/、logs/、*.db 等")
        if _GITHUB_PROXY:
            logger.info(f"[更新检查] 通过代理下载: {_GITHUB_PROXY}")

        zip_asset = _find_release_zip(release_data)
        if not zip_asset:
            logger.error("[更新检查] 未在 Release 资产中找到完整发布包 zip，无法自动更新")
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

            # 执行安全更新（项目根目录即本 updater.py 所在目录）
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
