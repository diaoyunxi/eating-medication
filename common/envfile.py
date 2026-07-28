# -*- coding: utf-8 -*-
"""跨端共享：扁平 .env 文件的读取与就地更新（保留注释与其它字段）。

避免三端各自手写一遍 key=value 解析逻辑（install.py / updater.py /
family_monitor/core/config.py / elderly_assistant/utils/config_loader.py 均有重复）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Union

PathLike = Union[str, Path]


def read_env_dict(path: PathLike) -> Dict[str, str]:
    """解析扁平 key=value .env，返回 {key: value}（已 strip）。

    跳过空行、注释行(# 开头)、不含 '=' 的行；文件不存在或解析失败返回空 dict。
    """
    p = Path(path)
    data: Dict[str, str] = {}
    if not p.is_file():
        return data
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            data[k.strip()] = v.strip()
    except Exception:
        pass
    return data


def update_env_fields(path: PathLike, updates: Dict[str, str]) -> None:
    """就地更新 .env 中的若干字段，保留注释与其它字段；不存在的键追加到末尾。

    :param updates: {字段名: 新值}
    """
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    existing: Dict[str, int] = {}
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _ = s.split("=", 1)
        existing[k.strip()] = i
    for key, value in updates.items():
        new_line = f"{key}={value}"
        if key in existing:
            lines[existing[key]] = new_line
        else:
            lines.append(new_line)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_env_text(path: PathLike, content: str) -> None:
    """整文件写入 .env 模板内容（覆盖式），并限制权限为 600。"""
    p = Path(path)
    p.write_text(content, encoding="utf-8")
    try:
        p.chmod(0o600)
    except Exception:
        pass
