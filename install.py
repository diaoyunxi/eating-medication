#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根目录统一依赖安装脚本（各模块 main.py 检测到依赖缺失时调用）。

执行流程:
1. 检测 pip 是否存在, 无则自动安装
   - Linux 优先 apt (apt-get install python3-pip)
   - Windows 使用 get-pip.py 引导安装
   - 通用后备: python -m ensurepip --upgrade
2. 读取指定 requirements.txt 逐个安装依赖
3. 若 pip 输出包含 --break-system-packages (PEP 668 错误),
   自动加上该参数重新执行 pip install
4. 可选: 安装 dfrobot_huskylensv2 (PyPI 未发布, 从官方仓库下载, 供老人端使用)

命令行用法:
    python install.py <requirements_path> [--huskylens] [--target <dir>]
    - requirements_path: requirements.txt 的路径（必填）
    - --huskylens: 同时安装 dfrobot_huskylensv2（老人端专用）
    - --target <dir>: huskylens 模块落地目录（默认仓库根/elderly_assistant/）

也可被 import 调用:
    from install import ensure_pip, install_requirements, install_dfrobot_huskylensv2

GitHub 下载代理统一读取根目录 .env 的 GITHUB_PROXY 字段（与 updater.py 共用）。
"""

import sys
import os
import subprocess
import tempfile
import shutil
import importlib
import urllib.request
from pathlib import Path

# pip 镜像源：默认清华源，可用环境变量 PIP_INDEX_URL 覆盖
# （install.py 多处使用，未定义会触发 NameError 导致依赖安装崩溃）
PIP_INDEX_URL = os.getenv("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")

# 仓库根目录（本文件所在目录）
ROOT_DIR = Path(__file__).resolve().parent

# dfrobot_huskylensv2 是 PyPI 未发布的单文件模块, 需从官方仓库自动下载安装
HUSKYLENS_RAW_URL = os.environ.get(
    "HUSKYLENS_RAW_URL",
    "https://raw.githubusercontent.com/DFRobot/DFRobot_HuskylensV2/master/python/pinpong/dfrobot_huskylensv2.py",
)
HUSKYLENS_PKG = "dfrobot_huskylensv2"


def _load_root_github_proxy():
    """读取根目录 .env 的 GITHUB_PROXY 字段，统一 GitHub 下载代理出口。

    与 updater.py 共用同一配置源（common.envfile.read_env_dict），避免代理配置分散。
    返回代理字符串（镜像前缀或正向代理），未配置返回空串。
    """
    from common.envfile import read_env_dict
    return read_env_dict(ROOT_DIR / ".env").get("GITHUB_PROXY", "")


# ------------------------------------------------------------------
# 1. pip 检测 / 自动安装
# ------------------------------------------------------------------
def _check_pip_available():
    """检测 pip 是否可用 (执行 python -m pip --version)"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def _pip_version_string():
    """获取 pip 版本字符串, 失败返回空"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return (result.stdout or "").strip()
    except Exception:
        pass
    return ""


def _install_pip_linux():
    """Linux 优先使用 apt 安装 python3-pip, 尝试 sudo 与直接执行"""
    print("  [Linux] 尝试 apt 安装 python3-pip ...")
    if shutil.which("apt-get") is None:
        print("  未检测到 apt-get, 跳过")
        return False
    apt_steps = [
        ["apt-get", "update"],
        ["apt-get", "install", "-y", "python3-pip"],
    ]
    for apt_cmd in apt_steps:
        for prefix in (["sudo"], []):
            cmd = prefix + apt_cmd
            try:
                print("    执行:", " ".join(cmd))
                proc = subprocess.run(
                    cmd, timeout=900,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                )
                if proc.returncode == 0:
                    break
                print(f"    失败 (返回码={proc.returncode})")
            except FileNotFoundError:
                print("    找不到命令:", cmd[0])
                return False
            except subprocess.TimeoutExpired:
                print("    执行超时")
                continue
            except PermissionError as e:
                print(f"    权限不足: {e}")
                continue
        else:
            return False
    return _check_pip_available()


def _install_pip_windows():
    """Windows 使用 get-pip.py 引导安装 pip (标准库 urllib 下载)"""
    print("  [Windows] 下载 get-pip.py 引导安装 ...")
    print("    URL:", GET_PIP_URL)
    try:
        with urllib.request.urlopen(GET_PIP_URL, timeout=120) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  get-pip.py 下载失败: {e}")
        return False
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".py", delete=False,
        ) as f:
            f.write(data)
            tmp_path = f.name
        proc = subprocess.run(
            [sys.executable, tmp_path],
            timeout=900,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        if proc.returncode != 0:
            print(f"  get-pip.py 执行失败 (返回码={proc.returncode})")
            tail = (proc.stdout or b"")[-2000:].decode("utf-8", errors="ignore")
            if tail:
                print("  --- 输出尾部 ---\n" + tail)
            return False
    except Exception as e:
        print(f"  执行 get-pip.py 失败: {e}")
        return False
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    return _check_pip_available()


def _install_pip_ensurepip():
    """使用 ensurepip 引导安装 pip (跨平台通用后备)"""
    print("  [FALLBACK] 尝试 ensurepip 引导安装 ...")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            timeout=300,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        if proc.returncode != 0:
            tail = (proc.stdout or b"")[-2000:].decode("utf-8", errors="ignore")
            if tail:
                print("  --- 输出尾部 ---\n" + tail)
            return False
    except Exception as e:
        print(f"  ensurepip 执行失败: {e}")
        return False
    return _check_pip_available()


def ensure_pip():
    """检测 pip 是否存在, 无则按平台自动安装, 全部失败则退出脚本"""
    print("=" * 50)
    print("检查 pip 环境 ...")
    print("=" * 50)
    if _check_pip_available():
        print("  pip OK:", _pip_version_string())
        return True
    print("  未检测到 pip, 开始自动安装 ...")

    installed = False
    if sys.platform.startswith("linux"):
        installed = _install_pip_linux()
    elif sys.platform == "win32":
        installed = _install_pip_windows()

    if not installed:
        installed = _install_pip_ensurepip()

    if installed:
        print("  pip 自动安装成功:", _pip_version_string())
        return True
    print("  错误: pip 自动安装失败, 请手动安装 pip 后重试")
    return False


# ------------------------------------------------------------------
# 2. 包检测
# ------------------------------------------------------------------
# 部分 PyPI 包名与 import 名不一致, 在此映射
NAME_MAPPING = {
    "python-multipart": "multipart",
    "python-dotenv": "dotenv",
    "python-jose": "jose",
}


def _split_pkg_name(pkg):
    """从 requirements.txt 行中提取纯包名 (去除版本/路径/extras)"""
    return (
        pkg.split("~")[0]
        .split(">")[0]
        .split("=")[0]
        .split("<")[0]
        .split(";")[0]
        .strip()
    )


def is_package_installed(pkg_name):
    """检查包是否已安装, 优先 import, 回退 pip show"""
    package_name = _split_pkg_name(pkg_name)
    if not package_name:
        return False
    import_name = NAME_MAPPING.get(package_name, package_name)
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", package_name],
                capture_output=True, text=True, timeout=30,
            )
            return result.returncode == 0
        except Exception:
            return False


# ------------------------------------------------------------------
# 3. 包安装 (含 --break-system-packages 自动重试)
# ------------------------------------------------------------------
def _run_pip(cmd):
    """执行一次 pip, 返回 (returncode, stdout, stderr)"""
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=1800,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def install_package(pkg):
    """安装单个包

    若 pip 输出 (stdout+stderr) 包含 --break-system-packages
    (典型 PEP 668 / externally-managed-environment 错误),
    自动追加该参数重试一次。
    """
    pkg_name = _split_pkg_name(pkg)
    if not pkg_name:
        print("  [SKIP] 空包名")
        return True
    if is_package_installed(pkg_name):
        print("  ", pkg_name, "已安装, 跳过")
        return True

    print("  正在安装", pkg_name, "...")
    base_cmd = [
        sys.executable, "-m", "pip", "install", pkg, "-i", PIP_INDEX_URL,
    ]

    code, out, err = _run_pip(base_cmd)
    if code == 0:
        print("  ", pkg_name, "安装完成")
        return True

    combined = out + "\n" + err
    if "--break-system-packages" in combined:
        print(f"  {pkg_name} 需要 --break-system-packages, 重新安装 ...")
        retry_code, retry_out, retry_err = _run_pip(
            base_cmd + ["--break-system-packages"]
        )
        if retry_code == 0:
            print("  ", pkg_name, "安装完成")
            return True
        print(f"  安装失败 {pkg_name} 返回码: {retry_code}")
        tail = (retry_out + "\n" + retry_err)[-1000:]
        if tail.strip():
            print("  --- 错误尾部 ---\n" + tail)
        return False

    print(f"  安装失败 {pkg_name} 返回码: {code}")
    tail = combined[-1000:]
    if tail.strip():
        print("  --- 错误尾部 ---\n" + tail)
    print("  提示: 建议使用虚拟环境安装依赖:")
    print("    python -m venv venv")
    print("    source venv/bin/activate  # Linux/macOS")
    print("    venv\\Scripts\\activate     # Windows")
    return False


# ------------------------------------------------------------------
# 4. requirements 安装（接受任意 requirements.txt 路径）
# ------------------------------------------------------------------
def install_requirements(requirements_path):
    """从指定 requirements.txt 逐个安装依赖

    :param requirements_path: requirements.txt 的路径（绝对或相对仓库根）
    :return: True 表示全部成功
    """
    req_path = Path(requirements_path)
    if not req_path.is_absolute():
        req_path = ROOT_DIR / req_path
    if not req_path.exists():
        print("错误: 找不到", req_path)
        return False
    print("=" * 50)
    print(f"正在安装依赖 ({req_path}) 镜像源: {PIP_INDEX_URL}")
    print("=" * 50)
    packages = []
    with open(req_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                packages.append(line)
    if not packages:
        print("无需安装的包")
        return True
    print()
    print("共", len(packages), "个包:")
    for pkg in packages:
        print("  -", pkg)
    print()
    installed_count = 0
    skipped_count = 0
    failed_count = 0
    for pkg in packages:
        pkg_name = _split_pkg_name(pkg)
        if pkg_name and is_package_installed(pkg_name):
            print("  ", pkg_name, "已安装, 跳过")
            skipped_count += 1
        else:
            if install_package(pkg):
                installed_count += 1
            else:
                failed_count += 1
    print()
    print("=" * 50)
    print("安装结果:")
    print("  新安装:", installed_count)
    print("  已跳过:", skipped_count)
    print("  失败:  ", failed_count)
    print("=" * 50)
    return failed_count == 0


# ------------------------------------------------------------------
# 5. 特殊包: dfrobot_huskylensv2 (PyPI 未发布, 自动下载安装)
# ------------------------------------------------------------------
def _huskylens_download_url():
    """拼接最终下载地址, 支持镜像前缀 (统一读根 .env 的 GITHUB_PROXY)"""
    mirror = _load_root_github_proxy().rstrip("/")
    if mirror:
        return f"{mirror}/{HUSKYLENS_RAW_URL}"
    return HUSKYLENS_RAW_URL


def _download_huskylens(target_path):
    """下载 dfrobot_huskylensv2.py 到 target_path, 含内容完整性校验

    返回 True 表示文件已落盘且包含 camera.py 依赖的关键符号。
    """
    url = _huskylens_download_url()
    print("    下载地址:", url)
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            data = resp.read()
    except Exception as e:
        print(f"    下载失败: {e}")
        return False
    text = data.decode("utf-8", errors="ignore")
    required_markers = (
        "class HuskylensV2_I2C",
        "class HuskylensV2_UART",
        "ALGORITHM_OBJECT_RECOGNITION",
    )
    missing = [m for m in required_markers if m not in text]
    if missing:
        print("    下载内容校验失败, 缺少预期符号:", ", ".join(missing))
        return False
    try:
        with open(target_path, "wb") as f:
            f.write(data)
    except Exception as e:
        print(f"    写入文件失败 ({target_path}): {e}")
        return False
    return True


def _get_site_packages_dir():
    """返回当前环境可用的 site-packages 目录, 优先用户级, 回退系统级"""
    import site
    candidates = []
    try:
        user_site = site.getusersitepackages()
        if user_site:
            candidates.append(user_site)
    except Exception:
        pass
    try:
        candidates.extend(site.getsitepackages() or [])
    except Exception:
        pass
    for d in candidates:
        if not d:
            continue
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except Exception:
            continue
    return None


def install_dfrobot_huskylensv2(target_dir=None):
    """安装 dfrobot_huskylensv2 (PyPI 未发布, 从官方仓库自动下载)

    :param target_dir: 模块落地目录（默认仓库根/elderly_assistant/）
    """
    if is_package_installed(HUSKYLENS_PKG):
        print("  ", HUSKYLENS_PKG, "已安装, 跳过")
        return True

    print("  正在安装", HUSKYLENS_PKG, "(PyPI 未发布, 从官方仓库下载) ...")
    if target_dir is None:
        target_dir = str(ROOT_DIR / "elderly_assistant")
    target_dir = os.path.abspath(target_dir)

    # 策略 1: 下载到目标目录
    local_path = os.path.join(target_dir, f"{HUSKYLENS_PKG}.py")
    if _download_huskylens(local_path):
        if target_dir not in sys.path:
            sys.path.insert(0, target_dir)
        sys.modules.pop(HUSKYLENS_PKG, None)
        if is_package_installed(HUSKYLENS_PKG):
            print("  ", HUSKYLENS_PKG, "已下载至", target_dir, "并验证可导入")
            return True
        print("    本地文件已下载, 但当前环境导入失败, 继续尝试 site-packages 兜底")

    # 策略 2: 安装到 site-packages
    site_dir = _get_site_packages_dir()
    if site_dir:
        site_path = os.path.join(site_dir, f"{HUSKYLENS_PKG}.py")
        if _download_huskylens(site_path):
            sys.modules.pop(HUSKYLENS_PKG, None)
            if is_package_installed(HUSKYLENS_PKG):
                print("  ", HUSKYLENS_PKG, "已安装至", site_dir, "并验证可导入")
                return True
        print("    site-packages 兜底安装失败")
    else:
        print("    无法确定 site-packages 目录, 兜底安装失败")

    print(f"  安装失败 {HUSKYLENS_PKG}, 请手动下载: {HUSKYLENS_RAW_URL}")
    return False


# ------------------------------------------------------------------
# 6. 命令行入口
# ------------------------------------------------------------------
def _parse_args(argv):
    """解析命令行参数: <requirements_path> [--huskylens] [--target <dir>]"""
    requirements_path = None
    huskylens = False
    target = None
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--huskylens":
            huskylens = True
        elif arg == "--target":
            if i + 1 < len(argv):
                target = argv[i + 1]
                i += 1
            else:
                print("错误: --target 需要一个参数")
                sys.exit(2)
        elif not arg.startswith("-") and requirements_path is None:
            requirements_path = arg
        else:
            print(f"未知参数: {arg}")
            sys.exit(2)
        i += 1
    if not requirements_path:
        print("用法: python install.py <requirements_path> [--huskylens] [--target <dir>]")
        sys.exit(2)
    return requirements_path, huskylens, target


if __name__ == "__main__":
    try:
        print("=" * 60)
        print("    依赖安装脚本（根目录统一）")
        print("=" * 60)
        print()
        requirements_path, huskylens, target = _parse_args(sys.argv)
        if not ensure_pip():
            sys.exit(1)
        print()
        ok = install_requirements(requirements_path)
        if huskylens:
            print()
            if not install_dfrobot_huskylensv2(target):
                ok = False
        print()
        if ok:
            print("安装完成。")
        else:
            print("部分包安装失败, 请根据上方错误信息排查。")
            sys.exit(1)
    except KeyboardInterrupt:
        print()
        print("用户中断, 已退出")
        sys.exit(130)
    except Exception as e:
        print()
        print("安装脚本异常:", e)
        sys.exit(1)
