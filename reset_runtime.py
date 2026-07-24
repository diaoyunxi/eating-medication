# -*- coding: utf-8 -*-
"""运行时数据重置工具。

通过 ``main.py --reset`` 调用：删除仓库内所有「未跟踪」或「被 .gitignore 忽略」的
运行时文件 / 目录，但**保留** ``.env``、``config.json`` 与 ``logs/`` 文件夹，
使工作树与一次全新 ``git clone`` 的差异仅剩这三项。

典型清理对象：
- 用户密码库：server 的 SQLAlchemy 数据库（User 表）、family_monitor 的 ``users.json``
- 老人端设备数据：``elderly_assistant/device_id.txt`` 及其 ``data/`` 目录
- 其他运行时产物：各模块 ``data/``、``*.db`` / ``*.sqlite*``、由 install.py 下载的
  ``dfrobot_huskylensv2.py``、``__pycache__`` 与 ``*.pyc`` 等

删除策略：优先基于 ``git status --ignored`` 精确枚举被忽略 / 未跟踪项；
即便 git 不可用，也会按显式模式兜底清理核心数据，确保关键运行时数据被清除。

删除采用「保留感知」递归策略：当某个被忽略目录内同时含有需保留的文件
（如 ``server/.env``）时，不会整目录删除，而是仅清理其中的非保留内容，
从而安全保留 ``.env`` / ``config.json`` / ``logs/``。
"""

import os
import subprocess
import sys
from pathlib import Path

# 必须保留的运行时文件名（任意层级）
PRESERVE_NAMES = {".env", "config.json"}
# 必须保留的目录名（任意层级，含其内部所有内容），即 logs 文件夹
PRESERVE_DIR_NAMES = {"logs"}

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


def _is_preserved(parts):
    """判断相对路径片段中是否包含需保留项（.env / config.json / logs 目录）。"""
    if any(p in PRESERVE_NAMES for p in parts):
        return True
    if PRESERVE_DIR_NAMES & set(parts):
        return True
    return False


def _delete_path(path: Path, deleted: list, skipped: list):
    """保留感知的删除：文件直接删（保留项跳过），目录递归清理后视情况删空目录。

    符号链接按文件处理（不跟随、不递归其目标）。
    """
    if not path.exists() and not path.is_symlink():
        return
    try:
        # 符号链接优先处理，避免被 is_dir() 跟随到目标目录
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
            # 整个目录均为受保护项（如 logs/）时完全不动
            if _is_preserved(path.parts):
                return
            # 递归处理子项，仅清理非保留内容
            for child in sorted(path.iterdir()):
                _delete_path(child, deleted, skipped)
            # 子项清理后若目录已空，则删除该空目录
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
    """基于 ``git status --ignored`` 枚举被忽略 / 未跟踪项并删除。

    成功返回 True；git 不可用或执行失败时返回 False（交由兜底逻辑清理）。
    """
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
        # 已跟踪文件永远不会出现在 ?? / !! 中，无需额外判断
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
    """重置运行时数据。

    :param repo_root_str: 仓库根目录路径
    :return: (已删除列表, 跳过列表)
    """
    repo_root = Path(repo_root_str).resolve()
    deleted, skipped = [], []

    # 优先用 git 精确枚举
    _reset_via_git(repo_root, deleted, skipped)
    # 兜底：无论 git 是否可用，再次按显式模式清理核心数据
    _reset_via_patterns(repo_root, deleted, skipped)

    # 去重并保持顺序
    seen, deduped = set(), []
    for p in deleted:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped, skipped


def confirm_reset():
    """交互式二次确认，避免误删运行时数据。

    非交互环境（标准输入不可读）默认取消，确保安全。
    """
    try:
        ans = input(
            "确认重置运行时数据？将删除用户密码库、老人端设备数据等本地数据"
            "（保留 .env / config.json / logs）。输入 YES 继续: "
        ).strip()
    except (EOFError, OSError):
        return False
    return ans == "YES"


if __name__ == "__main__":
    # 允许 `python reset_runtime.py` 直接运行（需指定仓库根目录，默认当前目录）
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    if not confirm_reset():
        print("已取消。")
        sys.exit(0)
    d, s = reset_runtime_data(root)
    print(f"已删除 {len(d)} 项；跳过 {len(s)} 项。")
