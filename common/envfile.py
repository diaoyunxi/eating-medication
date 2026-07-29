# -*- coding: utf-8 -*-
"""跨端共享：扁平 .env 文件的读取与就地更新（保留注释与其它字段）。

避免三端各自手写一遍 key=value 解析逻辑（common/install.py / updater.py /
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
            k = k.strip()
            if not k:
                # 跳过形如 "=value"（无键）的非法行，避免产生空键
                continue
            data[k] = v.strip()
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


def ensure_env_template(path: PathLike, template_text: str) -> bool:
    """若 .env 模板不存在则写入（含 600 权限），已存在则跳过。

    统一三端「首次运行自动生成 .env」的创建逻辑，避免各自重复实现
    ``write_text`` + ``chmod`` 与「存在性守卫」。

    :return: True 表示本次实际写入了文件（可用于决定是否打印提示）
    """
    p = Path(path)
    if p.exists():
        return False
    write_env_text(p, template_text)
    return True


def read_github_proxy(root_dir: PathLike = None) -> str:
    """从根目录 .env 读取 GITHUB_PROXY 配置（common/install.py 与 updater.py 共用源）。

    支持两种形式：
    1. 镜像前缀（如 https://gh-proxy.com）：下载 URL 改写为 {proxy}/{原始URL}
    2. 正向代理（如 http://127.0.0.1:7890）：通过 urllib ProxyHandler 透明转发
    未配置或文件不存在时返回空串，走直连。
    """
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent.parent
    data = read_env_dict(Path(root_dir) / ".env")
    return data.get("GITHUB_PROXY", "")
