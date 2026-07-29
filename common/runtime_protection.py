# -*- coding: utf-8 -*-
"""
运行时受保护文件规则 —— 合并 updater.py 的 PROTECTED_* 与 reset_runtime.py 的 PRESERVE_*。
统一作为所有「文件删除/覆盖/重置」操作的权威来源，确保两套机制保护范围一致。

使用方式：
    from common.runtime_protection import is_protected_path

    if is_protected_path("server/.env"):
        # 跳过删除/覆盖
"""
import fnmatch
import os

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

# 子目录保护：这些目录下的所有文件均受保护
PROTECTED_SUBDIRS = {
    "data",
    "logs",
    "certs",
    "captures",
    "__pycache__",
}


def is_protected_path(rel_path: str) -> bool:
    """判断相对路径是否属于受保护范围。

    对路径的每一级目录段和文件名分别做精确匹配（PROTECTED_NAMES）和
    通配符匹配（PROTECTED_PATTERNS），以及子目录前缀匹配（PROTECTED_SUBDIRS）。

    :param rel_path: 相对于仓库根目录的路径（如 "server/.env"、"data/db.sqlite"）
    :return: True 表示应受保护（不应删除/覆盖）
    """
    # 将路径分割为各段
    parts = rel_path.replace(os.sep, "/").split("/")

    # 精确匹配文件名或目录名
    for part in parts:
        if part in PROTECTED_NAMES:
            return True

    # 通配符匹配文件名（仅对最后一段）
    filename = parts[-1]
    for pattern in PROTECTED_PATTERNS:
        if fnmatch.fnmatch(filename, pattern):
            return True

    # 子目录前缀匹配
    for subdir in PROTECTED_SUBDIRS:
        if subdir in parts[:-1]:
            return True

    return False
