#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
项目级自动更新检查与安全更新模块（统一位于仓库根目录）

启动时检查 GitHub 仓库是否有新版本，发现新版本时：
- 默认启用安全自动更新（可由项目根目录 .env 的 AUTO_PULL 字段关闭）
- AUTO_PULL=false 时，仅提示、手动更新

【与旧版（各模块内 updater.py）的区别】
1. 仅从 GitHub Release 拉取「完整发布包」 eating-medication-vX.Y.Z.zip 及其 SHA256
   校验文件；不再单独处理各模块分包（如 server_v*.zip / family_monitor_v*.zip）。
2. 读取仓库根目录 .env 的 GITHUB_PROXY 字段，通过该代理/镜像下载
   （兼容 gh-proxy.com 镜像前缀形式，亦兼容 http(s)://host:port 正向代理）。

【安全更新机制】
1. 下载 release 完整 zip 到临时目录
2. 解压到临时子目录
3. 仅复制非保护文件到项目根目录（保护文件规则见 common.runtime_protection）
4. 保护文件：.env、data/、logs/、*.db、*.sqlite* 等运行时数据
5. 更新失败时自动回滚到备份
6. 更新成功后自动重启相关 systemd 服务（详见 _restart_services：普通部署用户经免密 sudoers 调用 systemctl restart，由 systemd 接管完成 server+family 重启）

【保护文件清单】
- .env（含 server/.env、family_monitor/.env、elderly_assistant/.env 等嵌套路径）
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
import logging
import fnmatch
import subprocess
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
# 根目录 .env 路径与默认内容（全局更新配置，无密钥，纳入版本管理）
# ============================================================
_CONFIG_PATH = Path(__file__).resolve().parent / ".env"

# .env 默认内容；首次运行未检测到 .env 时自动生成
_ENV_DEFAULT_CONTENT = (
    "# 全局更新配置（无密钥，纳入版本管理）\n"
    "# 是否启用安全自动更新（下载完整发布包并保留配置文件与数据库）\n"
    "AUTO_PULL=true\n"
    "# GitHub 代理/镜像前缀（如 https://gh-proxy.com），留空走直连\n"
    "# 同时供 common/install.py 下载 huskylens 模块使用，统一代理出口\n"
    "GITHUB_PROXY=\n"
)


def _load_root_env():
    """解析根目录 .env，返回 dict（复用 common.envfile，避免手写解析重复）。

    .env 为扁平 key=value 格式；处于引导阶段不引入额外依赖（common.envfile 仅标准库）。
    """
    from common.envfile import read_env_dict, write_env_text, ensure_env_template
    return read_env_dict(_CONFIG_PATH)


def _ensure_env_template():
    """若根目录 .env 不存在，自动生成带默认值的配置文件。

    便于首次部署即拥有可编辑的配置骨架；已存在文件不会被覆盖。
    """
    try:
        from common.envfile import ensure_env_template
        if ensure_env_template(_CONFIG_PATH, _ENV_DEFAULT_CONTENT):
            logger.info(f"[更新检查] 已生成配置模板: {_CONFIG_PATH}（默认 AUTO_PULL=true，可手动编辑）")
    except Exception as e:
        logger.warning(f"[更新检查] 生成 .env 模板失败: {e}")


# ============================================================
# 代理配置：读取根目录 .env 的 GITHUB_PROXY 字段
# ============================================================
def _load_github_proxy():
    """读取根目录 .env 的 GITHUB_PROXY 字段。

    与 common/install.py 共用 common.envfile.read_github_proxy()，避免代理配置分散。
    支持两种形式：
    1. 镜像前缀（如 https://gh-proxy.com）：下载 URL 改写为 {proxy}/{原始URL}
    2. 正向代理（如 http://127.0.0.1:7890）：通过 urllib ProxyHandler 透明转发
    未配置或文件不存在时返回 None，走直连。
    """
    from common.envfile import read_github_proxy
    proxy = read_github_proxy(_CONFIG_PATH.parent)
    return proxy if proxy else None


# 首次运行时若根目录无 .env，自动生成模板
_ensure_env_template()

_GITHUB_PROXY = _load_github_proxy()


# ============================================================
# 自动更新开关：读取根目录 .env 的 AUTO_PULL 字段
# ============================================================
def _load_auto_pull():
    """读取根目录 .env 的 AUTO_PULL 字段，决定是否启用安全自动更新。

    优先级：.env 的 AUTO_PULL 字段 > 缺省值 True。
    - 文件不存在 / 字段缺失 / 解析失败：回退 True（默认启用安全自动更新）
    - 支持 bool 值与字符串 "true"/"false"（大小写不敏感）解析
    """
    data = _load_root_env()
    val = data.get("AUTO_PULL", "true")
    if isinstance(val, bool):
        return val
    if isinstance(val, str) and val.strip():
        return val.strip().lower() == "true"
    logger.warning(f"[更新检查] .env 的 AUTO_PULL 类型无效（{type(val).__name__}），回退为 True")
    return True


_AUTO_PULL = _load_auto_pull()


def _configure_opener():
    """根据 github_proxy 构建 urllib opener，返回 (opener, is_mirror, mirror_base)。

    代理类型判定（仅靠 URL 无法 100% 区分，按常用约定识别）：
    - 正向代理（CONNECT 隧道）：netloc 含显式端口，或指向本机
      （如 http://127.0.0.1:7890、http://localhost:8080、socks5://host:1080）。
      这类代理通过 ProxyHandler 透明转发，目标 URL 不变。
    - 镜像前缀（gh-proxy 风格）：普通域名、无端口
      （如 https://gh-proxy.com、https://gh.my-website.ccwu.cc）。
      目标 URL 改写为 {proxy}/{原始URL} 形式访问。
    """
    proxy = _GITHUB_PROXY
    if not proxy:
        return urllib.request.build_opener(), False, None
    parsed = urlparse(proxy)
    if not parsed.scheme or not parsed.netloc:
        # 非法代理配置，回退直连
        logger.warning(f"[更新检查] github_proxy 配置非法（{proxy}），回退直连")
        return urllib.request.build_opener(), False, None
    # 是否为正向代理：含显式端口或本机地址
    hostname = (parsed.hostname or "").lower()
    netloc_no_user = parsed.netloc.split("@")[-1]
    has_port = ":" in netloc_no_user
    is_forward = has_port or hostname in ("127.0.0.1", "localhost", "::1")
    if is_forward:
        handler = urllib.request.ProxyHandler({parsed.scheme: proxy})
        return urllib.request.build_opener(handler), False, None
    # 镜像前缀形式（如 https://gh-proxy.com）
    base = proxy.rstrip("/")
    return urllib.request.build_opener(), True, base


_OPENER, _IS_MIRROR, _MIRROR_BASE = _configure_opener()


def _build_url(url):
    """若配置了镜像前缀形式的 github_proxy，将目标 URL 改写为通过镜像访问。

    注意：gh-proxy 类镜像通常只代理 github.com 的 raw/下载内容，
    并不代理 api.github.com。若对 API 地址套用镜像前缀，镜像会返回空响应，
    导致 json.loads 抛出「Expecting value: line 1 column 1」。
    因此 api.github.com 请求一律走直连（正向代理仍由 opener 透明转发）。
    """
    if _IS_MIRROR and _MIRROR_BASE and not url.startswith("https://api.github.com/"):
        return f"{_MIRROR_BASE}/{url}"
    return url


def _open_url(url, timeout, headers=None):
    """发起 HTTP 请求，自动套用 github_proxy（镜像前缀或正向代理）。"""
    target = _build_url(url)
    req = urllib.request.Request(target, headers=headers or _gh_headers())
    return _OPENER.open(req, timeout=timeout)


# ============================================================
# 保护文件判定：复用 common.runtime_protection 单一事实来源
# （更新 / 部署场景：不覆盖 .env、data/、logs/、*.db 等运行时数据）
# 保留原函数名 _is_protected_path 以兼容内部调用与既有测试。
# ============================================================
from common.runtime_protection import is_protected_path as _is_protected_path, is_reset_preserved_path


# ============================================================
# GitHub API 与版本比较
# ============================================================
def _fetch_json(url, timeout):
    """安全获取并解析 JSON：校验 HTTP 状态、空响应、非 JSON 响应，给出可读错误。"""
    try:
        with _open_url(url, timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # 4xx/5xx：尝试读取响应体以判断原因（如 403 限流、404 无 Release）
        raise RuntimeError(f"HTTP {e.code} 请求 {url} 失败：{e.reason}")
    if not raw.strip():
        raise RuntimeError(f"请求 {url} 返回空响应（可能镜像/代理不支持该地址，或网络异常）")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        snippet = raw[:200].replace("\n", " ")
        raise RuntimeError(f"响应非 JSON（{url}）：{e}；响应片段：{snippet!r}")


def _fetch_latest_release():
    """从 GitHub 获取最新 Release 信息（含资产列表）"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    return _fetch_json(url, 10)


def _fetch_latest_version():
    """从 GitHub 获取最新版本号（优先 Releases，回退 Tags）"""
    try:
        data = _fetch_latest_release()
        return data.get("tag_name"), data.get("html_url"), data
    except Exception as e:
        logger.warning(f"获取 Release 失败: {e}")
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/tags"
        data = _fetch_json(url, 10)
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


def _purge_pycache(project_dir: Path):
    """递归删除项目目录下所有 __pycache__ 目录及其中的 .pyc/.pyo 文件。

    自动更新覆盖 .py 文件后，旧的 .pyc 缓存可能因 mtime 竞态未被 Python 重新编译，
    导致进程加载旧字节码（表现为「VERSION 已更新但行为未变」）。
    更新后主动清除所有 __pycache__ 可彻底消除此隐患。

    :param project_dir: 项目根目录路径
    """
    purged = 0
    for cache_dir in project_dir.rglob("__pycache__"):
        if not cache_dir.is_dir():
            continue
        # 跳过 .venv / venv 等保护目录内的缓存
        try:
            rel = cache_dir.relative_to(project_dir)
        except ValueError:
            continue
        if any(part in (".venv", "venv", "env", ".git") for part in rel.parts):
            continue
        try:
            shutil.rmtree(cache_dir, ignore_errors=True)
            purged += 1
        except Exception as e:
            logger.debug(f"[更新检查] 清除 __pycache__ 失败 {cache_dir}: {e}")
    if purged:
        logger.info(f"[更新检查] 已清除 {purged} 个 __pycache__ 目录")


def _perform_update(zip_path, project_dir, protected_check=_is_protected_path):
    """执行安全更新：解压完整发布包到临时目录，跳过保护文件，复制到项目根目录。

    :param zip_path: 下载的 release 完整 zip 文件路径
    :param project_dir: 项目根目录路径（即本 updater.py 所在目录）
    :param protected_check: 受保护判定函数(rel_path) -> bool，默认 is_protected_path；
                             强制更新场景可传入「is_protected_path 或命中 .gitignore」的合并判定
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
            if protected_check(rel_str):
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

            if protected_check(str(dst_rel).replace("\\", "/")):
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

        # 清除所有 __pycache__ 目录，防止 Python 加载旧 .pyc 缓存导致代码更新未生效
        _purge_pycache(project_dir)

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




def _restart_services():
    """更新成功后自动重启相关 systemd 服务，使新版本代码生效。

    设计要点：
    - 仅 systemd 环境（/run/systemd/system 存在且 systemctl 可用）下生效；
      非 systemd 环境（如本地开发、Windows、容器）仅记录警告并跳过，不报错。
    - 以 root 运行时直接调用 systemctl；以普通部署用户（如 deploy）运行时，
      使用 `sudo -n`（非交互，避免阻塞）调用，依赖部署脚本写入的免密 sudoers 规则
      （见 deploy/setup.sh 步骤 7）。
    - 通过单次 `systemctl restart <svc1> <svc2>` 将重启请求提交给 systemd，
      systemd 会接管 server 与 family 两个单元的停止/启动，即使当前进程（updater
      所在的应用进程）随后被 SIGTERM 终止，重启仍会由 systemd 完成。
    - 服务名集中在函数内，便于扩展。
    """
    service_names = ["eating-medication-server", "eating-medication-family"]
    if not shutil.which("systemctl") or not os.path.exists("/run/systemd/system"):
        logger.warning("[更新] 当前环境非 systemd，无法自动重启服务，请手动重启以应用新版本")
        return False
    cmd = ["systemctl", "restart"] + service_names
    if os.geteuid() != 0:
        cmd = ["sudo", "-n"] + cmd
    logger.info(f"[更新] 即将重启服务以应用新版本: {', '.join(service_names)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            logger.info(f"[更新] 已向 systemd 提交重启请求: {', '.join(service_names)}")
            return True
        logger.warning(f"[更新] 重启服务失败(rc={proc.returncode}): {proc.stderr.strip()}")
        if os.geteuid() != 0:
            logger.warning("[更新] 普通用户重启失败，请确认部署时已配置免密 sudoers（见 deploy/setup.sh）")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("[更新] 重启服务命令超时")
        return False
    except Exception as e:
        logger.warning(f"[更新] 重启服务异常: {e}")
        return False


def get_update_info():
    """查询更新信息，返回结构化字典（供 API 端点 / 前端轮询使用）。

    每次调用时动态读取 VERSION 文件获取当前版本号，避免进程启动后
    VERSION 文件被更新（如 git pull）但进程未重启时返回旧版本号。

    :return: dict，包含以下字段
        - current_version: 本地版本号（动态读取 VERSION 文件）
        - latest_version:  远端最新版本号（无网络时为 None）
        - update_available: bool，是否有可用更新
        - auto_pull:       当前 auto_pull 配置（bool，缺省 True）
        - release_url:     最新版本发布页 URL（无则为 None）
        - checked_at:      ISO 时间戳（本地）
    """
    current_ver = _load_version()
    info = {
        "current_version": current_ver,
        "latest_version": None,
        "update_available": False,
        "auto_pull": _AUTO_PULL,
        "release_url": None,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
    }
    try:
        latest, release_url, _ = _fetch_latest_version()
        info["latest_version"] = latest
        info["release_url"] = release_url
        if latest and _compare_versions(latest, current_ver) > 0:
            info["update_available"] = True
    except Exception as e:
        logger.warning(f"[更新检查] 查询更新信息失败: {e}")
    return info


# ============================================================
# 重置运行时数据（由 reset_runtime.py 迁入，作为 updater.py 的 --reset 模式）
# ============================================================
# 保留项判定复用 common 单一事实来源（is_reset_preserved_path 别名 _is_preserved）
_is_preserved = is_reset_preserved_path

# 诊断检查项：重置后输出当前项目状态，帮助用户确认问题是否已解决
_CRITICAL_FILES = {
    "family_monitor/routes/chat.py": ["from core", "import config"],
    "family_monitor/routes/home.py": ["from core", "import config"],
    "family_monitor/routes/auth.py": ["from core", "import config"],
}

# 兜底显式删除的运行时数据目录（相对仓库根）
EXPLICIT_DATA_DIRS = (
    "server/data",
    "family_monitor/data",
    "elderly_assistant/data",
)
# 兜底显式删除的文件名 / 后缀模式（rglob 匹配）
EXPLICIT_FILE_PATTERNS = (
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "users.json",
    "device_id.txt",
    "dfrobot_huskylensv2.py",
)


def _delete_path(path: Path, deleted: list, skipped: list):
    """保留感知的删除：文件直接删（保留项跳过），目录递归清理后视情况删空目录。

    符号链接按文件处理（不跟随、不递归其目标）。
    """
    if not path.exists() and not path.is_symlink():
        return
    try:
        if path.is_symlink():
            path.unlink()
            deleted.append(str(path))
            return
        if path.is_file():
            if _is_preserved(path.parts):
                return
            path.unlink()
            deleted.append(str(path))
            return
        if path.is_dir():
            if _is_preserved(path.parts):
                return
            for child in sorted(path.iterdir()):
                _delete_path(child, deleted, skipped)
            try:
                if not any(path.iterdir()):
                    path.rmdir()
                    deleted.append(str(path))
            except Exception:
                pass
            return
    except Exception as e:  # 权限等问题不阻断其它项
        skipped.append(f"{path} ({e})")


def _reset_via_git(repo_root: Path, deleted: list, skipped: list) -> bool:
    """基于 ``git status --ignored`` 枚举被忽略 / 未跟踪项并删除。成功返回 True。"""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--ignored"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception:
        return False
    if out.returncode != 0:
        return False
    for line in out.stdout.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        if code not in ("??", "!!"):
            continue
        rel = line[3:].strip().strip('"')
        if not rel:
            continue
        _delete_path(repo_root / rel, deleted, skipped)
    return True


def _reset_via_patterns(repo_root: Path, deleted: list, skipped: list):
    """兜底：按显式模式删除核心运行时数据（不依赖 git）。"""
    for d in EXPLICIT_DATA_DIRS:
        _delete_path(repo_root / d, deleted, skipped)
    for pattern in EXPLICIT_FILE_PATTERNS:
        for match in repo_root.rglob(pattern):
            _delete_path(match, deleted, skipped)
    for cache in repo_root.rglob("__pycache__"):
        _delete_path(cache, deleted, skipped)
    for pyc in repo_root.rglob("*.pyc"):
        _delete_path(pyc, deleted, skipped)


def reset_runtime_data(repo_root_str):
    """重置运行时数据（保留 .env / logs，删除其余运行时产物）。

    :param repo_root_str: 仓库根目录路径
    :return: (已删除列表, 跳过列表)
    """
    repo_root = Path(repo_root_str).resolve()
    deleted, skipped = [], []
    _reset_via_git(repo_root, deleted, skipped)
    _reset_via_patterns(repo_root, deleted, skipped)
    seen, deduped = set(), []
    for p in deleted:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped, skipped


def confirm_reset():
    """交互式二次确认，避免误删运行时数据。非交互环境默认取消。"""
    try:
        ans = input(
            "确认重置运行时数据？将删除用户密码库、老人端设备数据等本地数据"
            "（保留 .env / logs）。输入 YES 继续: "
        ).strip()
    except (EOFError, OSError):
        return False
    return ans == "YES"


def _print_diagnostics(repo_root: Path, deleted: list, skipped: list):
    """重置完成后输出诊断报告，帮助用户确认问题是否已解决。"""
    print("\n" + "=" * 60)
    print(" 重置后诊断报告")
    print("=" * 60)

    version_file = repo_root / "VERSION"
    if version_file.is_file():
        version = version_file.read_text(encoding="utf-8").strip()
        print(f"\n[1] 当前版本: {version}")
    else:
        print(f"\n[1] ✗ VERSION 文件不存在!")

    print(f"\n[2] 关键路由文件检查:")
    all_ok = True
    for rel_path, required_imports in _CRITICAL_FILES.items():
        fpath = repo_root / rel_path
        if not fpath.is_file():
            print(f"  ✗ {rel_path} — 文件不存在!")
            all_ok = False
            continue
        content = fpath.read_text(encoding="utf-8")
        missing = [imp for imp in required_imports if imp not in content]
        if missing:
            print(f"  ✗ {rel_path} — 缺少导入: {missing}")
            all_ok = False
        else:
            print(f"  ✓ {rel_path} — 导入完整")
    if all_ok:
        print("  → 所有关键文件导入正常")

    remaining_caches = []
    remaining_pyc = []
    for item in repo_root.rglob("__pycache__"):
        if item.is_dir():
            try:
                rel = item.relative_to(repo_root)
                if any(p in (".venv", "venv", "env", ".git") for p in rel.parts):
                    continue
            except ValueError:
                continue
            remaining_caches.append(str(item))
            for pyc in item.glob("*.pyc"):
                remaining_pyc.append(str(pyc))
    for pyc in repo_root.rglob("*.pyc"):
        if "__pycache__" not in str(pyc):
            remaining_pyc.append(str(pyc))

    print(f"\n[3] __pycache__ 清理状态:")
    if not remaining_caches and not remaining_pyc:
        print("  ✓ 已全部清除，无残留缓存")
    else:
        print(f"  ✗ 仍有 {len(remaining_caches)} 个 __pycache__ 目录残留")
        print(f"  ✗ 仍有 {len(remaining_pyc)} 个 .pyc 文件残留")
        if remaining_caches:
            print(f"    残留目录示例:")
            for c in remaining_caches[:5]:
                print(f"      - {c}")
            print(f"  ⚠ 请手动执行: find {repo_root} -type d -name __pycache__ "
                  f"-not -path '*/.venv/*' -not -path '*/venv/*' -exec rm -rf {{}} +")

    print(f"\n[4] .env 保留状态:")
    env_files = list(repo_root.rglob(".env"))
    if not env_files:
        print("  ⚠ 未找到任何 .env 文件（首次运行时将由程序自动生成）")
    else:
        for ef in env_files:
            try:
                rel = ef.relative_to(repo_root)
            except ValueError:
                rel = ef
            print(f"  ✓ {rel} 已保留")

    print(f"\n[5] 重置统计:")
    print(f"  已删除: {len(deleted)} 项")
    print(f"  跳过: {len(skipped)} 项")
    if skipped:
        print(f"  跳过详情（前 5 项）:")
        for s in skipped[:5]:
            print(f"    - {s}")

    print(f"\n[6] 结论:")
    issues = []
    if not all_ok:
        issues.append("关键路由文件导入不完整（可能导致 500 错误）")
    if remaining_caches or remaining_pyc:
        issues.append("仍有 __pycache__/.pyc 残留（可能导致旧代码被加载）")
    if not env_files:
        issues.append(".env 文件缺失（首次运行会自动生成）")

    if not issues:
        print("  ✓ 重置完成，未发现问题。请重启服务后验证。")
    else:
        print("  ⚠ 仍存在以下问题:")
        for issue in issues:
            print(f"    - {issue}")
        print("\n  建议操作:")
        if remaining_caches:
            print("    1. 手动清除 __pycache__（见上方命令）")
        print("    2. 检查关键文件是否为最新版本（git pull 或重新下载 release）")
        print("    3. 重启服务: systemctl restart eating-medication-family")

    print("\n" + "=" * 60)


# ============================================================
# .gitignore 保护（强制更新时额外保护被忽略的本地文件）
# ============================================================
def _load_gitignore_patterns():
    """读取仓库根目录 .gitignore，返回模式列表（忽略空行与注释）。"""
    p = Path(__file__).resolve().parent / ".gitignore"
    patterns = []
    if not p.is_file():
        return patterns
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    except Exception:
        pass
    return patterns


_GITIGNORE_PATTERNS = _load_gitignore_patterns()


def _is_gitignored(rel_path: str) -> bool:
    """判断相对路径是否被根目录 .gitignore 命中（简化实现，忽略否定/行内注释等高级语法）。

    - 目录模式（以 / 结尾）：任一层级命中也视为忽略；
    - 文件名模式：仅匹配最后一段文件名；
    - 路径模式：尾部匹配（含前导 / 的精确相对路径）。
    """
    if not _GITIGNORE_PATTERNS:
        return False
    rel = rel_path.replace("\\", "/")
    parts = rel.split("/")
    for pat in _GITIGNORE_PATTERNS:
        if pat.endswith("/"):
            dir_name = pat.rstrip("/").lstrip("/")
            if dir_name in parts:
                return True
            continue
        p = pat.lstrip("/")
        if fnmatch.fnmatch(parts[-1], p):
            return True
        if rel.endswith(p) or ("/" + p) in rel:
            return True
    return False


def _force_protected(rel_path: str) -> bool:
    """强制更新时的保护判定：运行时关键文件 + 根目录 .gitignore 命中项。"""
    return _is_protected_path(rel_path) or _is_gitignored(rel_path)


def force_update():
    """强制从远程拉取并安装最新发布包，忽略版本号比较（新增 updater 功能）。

    即便本地版本号 >= 远端版本号也执行（用于同版本补发修复包 / 热同步）。
    沿用 _perform_update 的受保护机制，并额外保护根目录 .gitignore 命中项，
    不会覆盖 .env、data/、logs/ 及任何被 .gitignore 忽略的本地文件。
    仍需满足 SHA256 校验，缺少校验文件时拒绝（安全要求）。
    """
    info = get_update_info()
    latest = info["latest_version"]
    try:
        if not latest:
            logger.warning("[强制更新] 无法获取最新版本，跳过")
            return info
        release_data = _fetch_latest_release()
        sha_sums = _verify_release_signature(release_data)
        if sha_sums is None:
            logger.error("[强制更新] 未找到 SHA256 校验文件，出于安全考虑拒绝更新")
            return info
        zip_asset = _find_release_zip(release_data)
        if not zip_asset:
            logger.error("[强制更新] 未在 Release 资产中找到完整发布包 zip")
            return info
        zip_url = zip_asset.get("browser_download_url")
        zip_name = zip_asset.get("name", "update.zip")
        tmp_zip_dir = Path(tempfile.mkdtemp(prefix="upd_zip_"))
        tmp_zip_path = tmp_zip_dir / zip_name
        expected_hash = sha_sums.get(zip_name)
        if not _download_file_with_hash(zip_url, str(tmp_zip_path), expected_hash):
            logger.error("[强制更新] 下载失败")
            return info
        project_dir = Path(__file__).resolve().parent
        success, updated, skipped = _perform_update(
            str(tmp_zip_path), str(project_dir), protected_check=_force_protected
        )
        if success:
            logger.info(f"[强制更新] 成功！更新了 {updated} 个文件，保护了 {skipped} 个文件")
            restarted = _restart_services()
            if restarted:
                logger.info("[强制更新] 服务正在重启以应用新版本")
            else:
                logger.warning("[强制更新] 文件已更新，但自动重启失败，请手动重启服务")
        else:
            logger.error("[强制更新] 失败，请手动更新")
        return info
    except Exception as e:
        logger.warning(f"[强制更新] 失败: {e}")
        info["error"] = str(e)
        return info


# ============================================================
# 入口
# ============================================================
def check_for_update(auto_pull=None):
    """
    启动时检查 GitHub 是否有新版本。
    - auto_pull 默认由根目录 .env 的 AUTO_PULL 控制（缺省 True）：启用安全自动更新
    - auto_pull=False：仅打印提示，手动更新
    - 显式传入 auto_pull 可覆盖 .env 配置与默认值

    【安全机制】
    1. 不使用 git checkout，避免误删未被跟踪的配置文件
    2. 下载 zip 到临时目录，解压后逐文件判断
    3. 保护文件（.env、data/、logs/、*.db 等）不会被覆盖
    4. SHA256 校验确保资产完整性（缺少校验文件时拒绝自动更新）
    """
    # 未显式指定时，使用根目录 .env 的 AUTO_PULL 配置（缺省 True）
    if auto_pull is None:
        auto_pull = _AUTO_PULL
    info = get_update_info()
    latest = info["latest_version"]
    release_url = info["release_url"]
    # 动态读取当前版本号（避免进程启动后 VERSION 更新但未重启时使用旧值）
    current_ver = info["current_version"]
    try:
        if not latest:
            logger.warning(f"[更新检查] 无法获取最新版本（网络或 GitHub 异常），跳过检查")
            return info

        if _compare_versions(latest, current_ver) <= 0:
            logger.info(f"[更新检查] 当前版本 v{current_ver}，已是最新版本。")
            return info

        logger.info("=" * 50)
        logger.info("  发现新版本！")
        logger.info(f"  当前版本: v{current_ver}")
        logger.info(f"  最新版本: {latest}")
        logger.info(f"  下载地址: {release_url}")
        logger.info("=" * 50)

        # 解析 SHA256 校验（仅获取一次，供后续 auto_pull 判断与安全校验共用）
        release_data = _fetch_latest_release()
        sha_sums = _verify_release_signature(release_data)
        if sha_sums is None:
            logger.warning("[更新检查] 未找到 SHA256 校验文件，无法验证资产完整性")
        else:
            logger.info(f"[更新检查] 已加载 {len(sha_sums)} 条资产校验记录")

        if not auto_pull:
            logger.info(f"[更新检查] 自动更新未启用，请手动访问 {release_url} 下载最新版本")
            logger.info("[更新检查] 提示：如需启用安全自动更新，可在根目录 .env 设置 AUTO_PULL=true（保留配置文件与数据库）")
            return info

        # 自动更新流程：缺少校验文件时拒绝自动更新（安全要求）
        if sha_sums is None:
            logger.error("[更新检查] 未找到SHA256校验文件，出于安全考虑拒绝自动更新")
            logger.info(f"[更新检查] 请手动访问 {release_url} 下载并人工校验")
            return info

        logger.warning("⚠️ 自动更新：将下载并安装新版本")
        logger.info("[更新检查] 保护文件将保留：.env、data/、logs/、*.db 等")
        if _GITHUB_PROXY:
            logger.info(f"[更新检查] 通过代理下载: {_GITHUB_PROXY}")

        zip_asset = _find_release_zip(release_data)
        if not zip_asset:
            logger.error("[更新检查] 未在 Release 资产中找到完整发布包 zip，无法自动更新")
            logger.info(f"[更新检查] 请手动访问 {release_url} 下载")
            return info

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
                return info

            # 执行安全更新（项目根目录即本 updater.py 所在目录）
            project_dir = Path(__file__).resolve().parent
            success, updated, skipped = _perform_update(str(tmp_zip_path), str(project_dir))

            if success:
                logger.info(f"[更新检查] 自动更新成功！更新了 {updated} 个文件，保护了 {skipped} 个文件")
                restarted = _restart_services()

                if restarted:

                    logger.info("[更新] 服务正在重启以应用新版本（当前进程会由 systemd 重新拉起）")

                else:

                    logger.warning("[更新] 文件已更新，但自动重启失败，请手动重启服务以应用新版本")
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
        info["error"] = str(e)
    return info


def _print_help():
    """打印命令行帮助，并解释 updater 是否会更新自身。"""
    help_text = """\
eating-medication 自动更新器 (updater.py) 使用说明
=================================================
普通运行（检查并应用更新）:
    python updater.py
        比较本地 VERSION 与 GitHub Release 版本号；若有更新，下载发布包
        （必须配套 <包名>.sha256 校验文件，否则出于安全拒绝更新），
        校验通过后解压并覆盖项目文件，最后清理 __pycache__ 并重启业务服务。

强制更新（忽略版本号）:
    python updater.py --force
        即便本地版本号 >= 远端也执行更新（用于同版本补发包 / 热同步）。
        仍受 SHA256 校验与受保护机制约束，不会覆盖 .env、data/、logs/
        及任何被 .gitignore 忽略的本地文件。

重置运行时数据:
    python updater.py --reset
        交互确认后清空运行时数据（保留 .env 与 logs/），并打印诊断信息。
        作用于本 updater.py 所在目录（即仓库根）。

帮助:
    python updater.py -h | --help
        显示本帮助。

updater 是否会更新自己？
-------------------------------------------------
会。updater.py 本身位于仓库根目录、已被 git 追踪且未被 .gitignore 忽略，
因此会被打进发布包（标准打包: git archive HEAD -- . ':!.env'）。
更新时 updater.py 不在受保护名单中（受保护的是 .env / data/ / logs/ /
*.db 等运行时与用户数据），普通更新与 --force 都会用新版本的 updater.py
覆盖旧文件，即「自更新」。

安全性说明:
  - Python 在启动时就已把 updater.py 整个载入内存，更新过程中覆盖磁盘上的
    脚本文件不会影响【当前正在运行】的更新进程；新版本在下一次运行时生效。
  - 更新成功后自动清除全部 __pycache__，避免旧 .pyc 缓存导致更新未生效；
    并重启业务服务（server / family_monitor 等），但 updater 自身进程
    执行完毕即退出，无需也不自我重启。
  - 更新前会对整个项目目录做临时备份（<项目>.bak.<时间戳>），失败可回滚。
"""
    print(help_text)


def _cli():
    """命令行入口：支持普通检查、--force 强制更新、--reset 重置运行时数据、--help 帮助。"""
    logging.basicConfig(level=logging.INFO)
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        _print_help()
        sys.exit(0)
    if "--reset" in args:
        # 重置模式：默认作用于仓库根目录（即本文件所在目录）
        root = Path(__file__).resolve().parent
        if not confirm_reset():
            print("已取消。")
            sys.exit(0)
        d, s = reset_runtime_data(str(root))
        _print_diagnostics(root, d, s)
        sys.exit(0)
    if "--force" in args:
        # 强制更新：忽略版本号比较，仍保护 .gitignore 与运行时关键文件
        force_update()
        sys.exit(0)
    check_for_update()


if __name__ == "__main__":
    _cli()
