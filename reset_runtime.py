# -*- coding: utf-8 -*-
"""运行时数据重置工具。

通过 ``main.py --reset`` 调用：删除仓库内所有「未跟踪」或「被 .gitignore 忽略」的
运行时文件 / 目录，但**保留** ``.env`` 与 ``logs/`` 文件夹，
使工作树与一次全新 ``git clone`` 的差异仅剩这两项（各模块的 .env）。

典型清理对象：
- 用户密码库：server 的 SQLAlchemy 数据库（User 表）、family_monitor 的 ``users.json``
- 老人端设备数据：``elderly_assistant/device_id.txt`` 及其 ``data/`` 目录
- 其他运行时产物：各模块 ``data/``、``*.db`` / ``*.sqlite*``、由 common/install.py 下载的
  ``dfrobot_huskylensv2.py``、``__pycache__`` 与 ``*.pyc`` 等

删除策略：优先基于 ``git status --ignored`` 精确枚举被忽略 / 未跟踪项；
即便 git 不可用，也会按显式模式兜底清理核心数据，确保关键运行时数据被清除。

删除采用「保留感知」递归策略：当某个被忽略目录内同时含有需保留的文件
（如 ``server/.env``）时，不会整目录删除，而是仅清理其中的非保留内容，
从而安全保留 ``.env`` / ``logs/``。
"""

import os
import subprocess
import sys
from pathlib import Path

# 保留项判定复用 common 单一事实来源（is_reset_preserved_path 别名 _is_preserved）
from common.runtime_protection import is_reset_preserved_path as _is_preserved


# ---------------------------------------------------------------------------
# 诊断检查项：重置后输出当前项目状态，帮助用户确认问题是否已解决
# ---------------------------------------------------------------------------
# 关键路由文件 → 应包含的导入片段（用于检测源码完整性）
# 同时兼容 ``from core import config`` 和 ``from core.config import config`` 两种写法
_CRITICAL_FILES = {
    "family_monitor/routes/chat.py": ["from core", "import config"],
    "family_monitor/routes/home.py": ["from core", "import config"],
    "family_monitor/routes/auth.py": ["from core", "import config"],
}

# 保留项（.env / logs/）判定已上收至 common.runtime_protection.is_reset_preserved_path
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
            "（保留 .env / logs）。输入 YES 继续: "
        ).strip()
    except (EOFError, OSError):
        return False
    return ans == "YES"


def _print_diagnostics(repo_root: Path, deleted: list, skipped: list):
    """重置完成后输出诊断报告，帮助用户确认问题是否已解决。

    检查项：
    1. 当前 VERSION
    2. 关键路由文件是否存在且包含必要导入（如 config）
    3. 残留 __pycache__ / .pyc 文件数量
    4. .env 文件是否保留
    5. 重置统计（已删除 / 跳过）

    :param repo_root: 仓库根目录
    :param deleted: 已删除文件列表
    :param skipped: 跳过文件列表
    """
    print("\n" + "=" * 60)
    print(" 重置后诊断报告")
    print("=" * 60)

    # 1. 版本号
    version_file = repo_root / "VERSION"
    if version_file.is_file():
        version = version_file.read_text(encoding="utf-8").strip()
        print(f"\n[1] 当前版本: {version}")
    else:
        print(f"\n[1] ✗ VERSION 文件不存在!")

    # 2. 关键文件完整性
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

    # 3. 残留 __pycache__
    remaining_caches = []
    remaining_pyc = []
    for item in repo_root.rglob("__pycache__"):
        if item.is_dir():
            # 跳过 venv 目录
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
        # 提示用户手动清除
        if remaining_caches:
            print(f"  ⚠ 请手动执行: find {repo_root} -type d -name __pycache__ "
                  f"-not -path '*/.venv/*' -not -path '*/venv/*' -exec rm -rf {{}} +")

    # 4. .env 保留状态
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

    # 5. 重置统计
    print(f"\n[5] 重置统计:")
    print(f"  已删除: {len(deleted)} 项")
    print(f"  跳过: {len(skipped)} 项")
    if skipped:
        print(f"  跳过详情（前 5 项）:")
        for s in skipped[:5]:
            print(f"    - {s}")

    # 6. 综合结论
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


if __name__ == "__main__":
    # 允许 `python reset_runtime.py` 直接运行（需指定仓库根目录，默认当前目录）
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    if not confirm_reset():
        print("已取消。")
        sys.exit(0)
    d, s = reset_runtime_data(root)
    # 输出重置后诊断报告
    _print_diagnostics(Path(root).resolve(), d, s)
