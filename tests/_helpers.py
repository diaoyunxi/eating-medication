# -*- coding: utf-8 -*-
"""
测试辅助工具：按文件路径加载模块（规避 elderly_assistant 与 family_monitor
同名顶层包 `core`/`utils`/`services` 的导入冲突）。

用法（在测试文件中）：
    from tests._helpers import load_module
    medication = load_module("elderly_core_medication",
                             "elderly_assistant/core/medication.py")
    # 之后使用 medication._parse_dosage(...) 等
"""
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 可能因跨模块加载而冲突的顶层包名，每次加载前清理缓存
_CONFLICT_TOP = ("core", "utils", "services", "routes")


def load_module(unique_name: str, rel_path: str):
    """从仓库内相对路径加载一个模块，返回模块对象。

    :param unique_name: 在当前 pytest 会话中唯一的模块名（避免与同名包冲突）
    :param rel_path: 相对仓库根的路径，例如 "elderly_assistant/core/medication.py"
    :return: 已加载的 module 对象
    """
    target = REPO_ROOT / rel_path
    base = REPO_ROOT / rel_path.split("/", 1)[0]  # elderly_assistant / family_monitor

    # 清理可能已缓存的冲突顶层包，确保重新解析为当前 base 下的版本
    for name in _CONFLICT_TOP:
        sys.modules.pop(name, None)
        # 同时清理子模块缓存（如 core.config / core.session）
        for cached in list(sys.modules):
            if cached == name or cached.startswith(name + "."):
                sys.modules.pop(cached, None)

    sys.path.insert(0, str(base))
    try:
        spec = importlib.util.spec_from_file_location(unique_name, target)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[unique_name] = mod
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    return mod


def require_thirdparty(*module_names):
    """返回未安装的第三方依赖列表，用于 importorskip 判断。"""
    missing = []
    for m in module_names:
        if importlib.util.find_spec(m) is None:
            missing.append(m)
    return missing
