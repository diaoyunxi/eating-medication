# -*- coding: utf-8 -*-
"""运行时受保护文件规则 —— 所有「文件删除 / 覆盖 / 重置」操作的唯一事实来源。

合并了原先散落在三处的重复定义：
- updater.py 的 ``PROTECTED_*``（更新 / 部署时不被覆盖）
- reset_runtime.py 的 ``PRESERVE_*``（重置时保留）
- 本文件原有定义

集中管理可消除「受保护边界漂移」风险：未来任何保护范围调整只需改这里。

对外提供两组判定（语义不同，**不可互相替代**）：
- ``is_protected_path``：更新 / 部署场景，保护 ``.env``、``data/``、``logs/``、``*.db``
  等运行时数据不被覆盖（范围广，含用户数据）。
- ``is_reset_preserved_path``：重置场景，仅保留 ``.env`` 与 ``logs/``；
  其余运行时数据（含 ``data/``、``*.db``）会被主动删除（范围窄，刻意如此）。

使用方式：
    from common.runtime_protection import is_protected_path, is_reset_preserved_path

    if is_protected_path("server/.env"):       # 更新时跳过覆盖
        ...
    if is_reset_preserved_path(("logs", "x")):  # 重置时跳过删除
        ...
"""
import fnmatch
from pathlib import Path

# ---------------------------------------------------------------------------
# 一、更新 / 部署保护：这些文件 / 目录在自动更新时不会被覆盖
# ---------------------------------------------------------------------------
# 文件名或目录名（精确匹配，任意一级路径段命中即保护）
PROTECTED_NAMES = {
    ".env",
    "data",
    "logs",
    "certs",
    "captures",
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    ".workbuddy",
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

# 子目录保护：这些目录下的所有文件均受保护（不含与目录同名的普通文件）
PROTECTED_SUBDIRS = {
    "data",
    "logs",
    "certs",
    "captures",
    "__pycache__",
}

# 大小写不敏感匹配（运行时文件后缀大小写不可控，统一小写比较）
_PROTECTED_NAMES_LOWER = {n.lower() for n in PROTECTED_NAMES}
_PROTECTED_SUBDIRS_LOWER = {s.lower() for s in PROTECTED_SUBDIRS}
_PROTECTED_PATTERNS_LOWER = [p.lower() for p in PROTECTED_PATTERNS]


def _as_parts(rel_path):
    """统一将输入转为小写路径段列表。

    兼容三种形态：
    - str / Path：按分隔符切分
    - tuple / list（如 ``pathlib.Path.parts``）：直接转为小写字符串列表
    """
    if isinstance(rel_path, (str, Path)):
        text = str(rel_path).replace("\\", "/")
        parts = text.split("/") if text else []
    else:
        parts = [str(p) for p in rel_path]
    return [p.lower() for p in parts]


def is_protected_path(rel_path) -> bool:
    """判断相对路径是否属于更新 / 部署受保护范围。

    对路径的每一级目录段和文件名分别做精确匹配（PROTECTED_NAMES）和
    通配符匹配（PROTECTED_PATTERNS），以及子目录前缀匹配（PROTECTED_SUBDIRS）。
    大小写不敏感。

    :param rel_path: 相对仓库根的路径（str / Path / 路径段元组），如 "server/.env"
    :return: True 表示应受保护（更新时不应覆盖）
    """
    parts = _as_parts(rel_path)
    if not parts:
        return False
    # 任意一级路径段为受保护文件名 / 目录名
    if any(part in _PROTECTED_NAMES_LOWER for part in parts):
        return True
    # 文件名模式匹配（仅最后一段）
    filename = parts[-1]
    if any(fnmatch.fnmatch(filename, pattern) for pattern in _PROTECTED_PATTERNS_LOWER):
        return True
    # 子目录保护：data/、logs/ 等下的所有文件均保护
    if any(sub in parts[:-1] for sub in _PROTECTED_SUBDIRS_LOWER):
        return True
    return False


# ---------------------------------------------------------------------------
# 二、重置保护：重置工具仅保留 .env 与 logs/，其余运行时数据会被主动删除
# ---------------------------------------------------------------------------
# 注意：此集合刻意远小于更新保护——重置工具的目标是「抹除」用户数据，因此
# data/、*.db 等不在保留之列；切勿为图省事直接复用 is_protected_path。
RESET_PRESERVE_NAMES = {".env"}
RESET_PRESERVE_DIRS = {"logs"}


def is_reset_preserved_path(rel_path) -> bool:
    """判断相对路径在重置时是否应保留（仅 ``.env`` 与 ``logs/``）。

    与 ``is_protected_path`` 语义不同：重置会主动删除 ``data/``、``*.db`` 等用户
    数据，仅保留 ``.env``（任意层级）与 ``logs/``（含其内部所有内容）。

    :param rel_path: 相对仓库根的路径（str / Path / 路径段元组）
    :return: True 表示重置时应保留、不删除
    """
    parts = set(_as_parts(rel_path))
    return bool(RESET_PRESERVE_NAMES & parts) or bool(RESET_PRESERVE_DIRS & parts)
