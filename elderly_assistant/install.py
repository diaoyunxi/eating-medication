#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依赖安装脚本

执行流程:
1. 检测 pip 是否存在, 无则自动安装
   - Linux 优先 apt (apt-get install python3-pip)
   - Windows 使用 get-pip.py 引导安装
   - 通用后备: python -m ensurepip --upgrade
2. 读取 requirements.txt 逐个安装依赖
3. 若 pip 输出包含 --break-system-packages (PEP 668 错误),
   自动加上该参数重新执行 pip install

建议在虚拟环境中运行。
"""

import sys
import os
import subprocess
import tempfile
import shutil
import importlib
import urllib.request


# 默认镜像源 (可通过环境变量 PIP_INDEX_URL 覆盖)
PIP_INDEX_URL = os.environ.get("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple")
# get-pip.py 下载地址 (可被 GET_PIP_URL 环境变量覆盖)
GET_PIP_URL = os.environ.get("GET_PIP_URL", "https://bootstrap.pypa.io/get-pip.py")

# dfrobot_huskylensv2 是 PyPI 未发布的单文件模块, 需从官方仓库自动下载安装
# 官方仓库单文件模块路径: python/pinpong/dfrobot_huskylensv2.py
# 该文件不纳入仓库 (运行时下载), install.py 负责落地。
HUSKYLENS_RAW_URL = os.environ.get(
    "HUSKYLENS_RAW_URL",
    "https://raw.githubusercontent.com/DFRobot/DFRobot_HuskylensV2/master/python/pinpong/dfrobot_huskylensv2.py",
)
# 下载镜像前缀 (如 https://gh-proxy.com), 设置后下载走镜像, 规避网络限制。
# 同时兼容 GH_PROXY 环境变量。
HUSKYLENS_MIRROR = os.environ.get(
    "HUSKYLENS_MIRROR", os.environ.get("GH_PROXY", "")
).rstrip("/")
HUSKYLENS_PKG = "dfrobot_huskylensv2"


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
        # 先尝试 sudo, 失败再尝试直接执行
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
    # macOS / 其他平台直接进入 ensurepip 后备

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

    # 第一次: 正常 pip
    code, out, err = _run_pip(base_cmd)
    if code == 0:
        print("  ", pkg_name, "安装完成")
        return True

    # 失败: 检查输出是否提示需要 --break-system-packages
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

    # 其他错误
    print(f"  安装失败 {pkg_name} 返回码: {code}")
    tail = combined[-1000:]
    if tail.strip():
        print("  --- 错误尾部 ---\n" + tail)
    print("  提示: 建议使用虚拟环境安装依赖:")
    print("    python -m venv venv")
    print("    source venv/bin/activate  # Linux/macOS")
    print("    venv\\Scripts\\activate     # Windows")
    print("    python install.py")
    return False


# ------------------------------------------------------------------
# 3.5 特殊包: dfrobot_huskylensv2 (PyPI 未发布, 自动下载安装)
# ------------------------------------------------------------------
def _huskylens_download_url():
    """拼接最终下载地址, 支持镜像前缀 (HUSKYLENS_MIRROR / GH_PROXY)"""
    if HUSKYLENS_MIRROR:
        return f"{HUSKYLENS_MIRROR}/{HUSKYLENS_RAW_URL}"
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
    # 完整性校验: 必须包含 camera.py 依赖的关键类与算法常量
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
    """返回当前环境可用的 site-packages 目录, 优先用户级, 回退系统级

    无可用目录时返回 None。
    """
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


def install_dfrobot_huskylensv2():
    """安装 dfrobot_huskylensv2 (PyPI 未发布, 从官方仓库自动下载)

    部署策略 (兜底):
      1. 优先下载到 elderly_assistant/ 目录 (运行 install.py 时 cwd 即该目录,
         与 ``from utils.logger`` 同机制, 模块可直接 import, 运行即生效)
      2. 若失败 (无写权限 / 导入校验失败), 安装到 Python 环境 site-packages

    注意: 该文件不纳入仓库 (运行时下载), 由本函数负责落地到本地。
    """
    if is_package_installed(HUSKYLENS_PKG):
        print("  ", HUSKYLENS_PKG, "已安装, 跳过")
        return True

    print("  正在安装", HUSKYLENS_PKG, "(PyPI 未发布, 从官方仓库下载) ...")
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # 策略 1: 下载到 elderly_assistant/ 目录
    local_path = os.path.join(script_dir, f"{HUSKYLENS_PKG}.py")
    if _download_huskylens(local_path):
        # 确保 elderly_assistant 在 sys.path (install.py 已 chdir 至此)
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        # 清除可能的损坏缓存, 确保重新导入
        sys.modules.pop(HUSKYLENS_PKG, None)
        if is_package_installed(HUSKYLENS_PKG):
            print("  ", HUSKYLENS_PKG, "已下载至 elderly_assistant/ 并验证可导入")
            return True
        print("    本地文件已下载, 但当前环境导入失败 "
              "(可能缺少 pinpong 依赖), 继续尝试 site-packages 兜底")

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
# 4. 入口
# ------------------------------------------------------------------
def install_requirements():
    """从 requirements.txt 逐个安装依赖"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    req_file = "requirements.txt"
    if not os.path.exists(req_file):
        print("错误: 找不到", req_file)
        return False
    print("=" * 50)
    print("正在安装依赖 (镜像源:", PIP_INDEX_URL, ") ...")
    print("=" * 50)
    packages = []
    with open(req_file, "r", encoding="utf-8") as f:
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
    # 特殊包: dfrobot_huskylensv2 (PyPI 未发布, 自动下载安装)
    if not install_dfrobot_huskylensv2():
        failed_count += 1
    print()
    print("=" * 50)
    print("安装结果:")
    print("  新安装:", installed_count)
    print("  已跳过:", skipped_count)
    print("  失败:  ", failed_count)
    print("=" * 50)
    return failed_count == 0


if __name__ == "__main__":
    try:
        print("=" * 60)
        print("    依赖安装脚本")
        print("=" * 60)
        print()
        if not ensure_pip():
            sys.exit(1)
        print()
        if install_requirements():
            print()
            print("安装完成。")
        else:
            print()
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
