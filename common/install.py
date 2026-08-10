#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公共依赖安装脚本（位于 common/install.py，原仓库根目录 install.py 已迁移至此；各模块 main.py 检测到依赖缺失时调用）。

执行流程:
0. venv 引导（作为脚本运行时优先执行）:
   - 已在 venv 中: 直接正常安装
   - 不在 venv 中:
     * venv 工具可用: 检测仓库根 .venv 目录, 存在则用其解释器
       重新执行本脚本（进入 venv 环境）; 不存在则先创建再进入
     * venv 工具不可用: Linux 尝试 sudo apt 安装 python3-venv 后重试;
       Windows 仅提示（venv 属标准库, 缺失需修复 Python 安装）,
       并降级在当前解释器继续安装
1. 检测 pip 是否存在, 无则自动安装
   - Linux 优先 apt (apt-get install python3-pip)
   - Windows 使用 get-pip.py 引导安装
   - 通用后备: python -m ensurepip --upgrade
2. 读取指定 requirements.txt 逐个安装依赖
3. 若 pip 输出包含 --break-system-packages (PEP 668 错误),
   自动加上该参数重新执行 pip install
4. 可选: 安装 dfrobot_huskylensv2 (PyPI 未发布, 从官方仓库下载, 供老人端使用)

命令行用法:
    python common/install.py <requirements_path> [--huskylens] [--target <dir>]
    - requirements_path: requirements.txt 的路径（必填）
    - --huskylens: 同时安装 dfrobot_huskylensv2（老人端专用）
    - --target <dir>: huskylens 模块落地目录（默认仓库根/elderly_assistant/）

也可被 import 调用:
    from common.install import ensure_venv, ensure_pip, install_requirements, install_dfrobot_huskylensv2

GitHub 下载代理统一读取仓库根目录 .env 的 GITHUB_PROXY 字段（与 updater.py / common.envfile 共用）。
"""

import sys
import os
import subprocess
import tempfile
import shutil
import importlib
import urllib.request
from pathlib import Path

# pip 镜像源策略：默认不使用任何镜像源（走系统/官方默认源），
# 若安装失败则自动回退到官方 PyPI 源 PIP_FALLBACK_URL 重试一次。
# 可用环境变量 PIP_INDEX_URL 强制指定首选源（非空时优先使用，失败仍回退官方源）。
PIP_INDEX_URL = os.getenv("PIP_INDEX_URL", "")
# 回退官方源：系统默认源安装失败时使用
PIP_FALLBACK_URL = "https://pypi.org/simple"

# get-pip.py 下载地址（Windows pip 引导安装用）
GET_PIP_URL = os.environ.get(
    "GET_PIP_URL",
    "https://bootstrap.pypa.io/get-pip.py",
)

# 仓库根目录：本文件位于 common/ 下，parent.parent 即为仓库根目录。
# 将仓库根加入 sys.path，使脚本既可作为 `python common/install.py` 运行，
# 也可被 common 包内其它模块 import（install.py 内部依赖 common.envfile）。
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 安装脚本解析相对 requirements.txt 路径、定位仓库根 .env 时使用的基准目录。
ROOT_DIR = REPO_ROOT

# dfrobot_huskylensv2 是 PyPI 未发布的单文件模块, 需从官方仓库自动下载安装
HUSKYLENS_RAW_URL = os.environ.get(
    "HUSKYLENS_RAW_URL",
    "https://raw.githubusercontent.com/DFRobot/DFRobot_HuskylensV2/master/python/pinpong/dfrobot_huskylensv2.py",
)
HUSKYLENS_PKG = "dfrobot_huskylensv2"


def _load_root_github_proxy():
    """读取根目录 .env 的 GITHUB_PROXY 字段，统一 GitHub 下载代理出口。

    与 updater.py 共用 common.envfile.read_github_proxy()，避免代理配置分散。
    返回代理字符串（镜像前缀或正向代理），未配置返回空串。
    """
    from common.envfile import read_github_proxy
    return read_github_proxy(ROOT_DIR)


# ------------------------------------------------------------------
# 0. venv 检测 / 引导
# ------------------------------------------------------------------
# 统一约定：虚拟环境目录固定为仓库根 .venv（与常见 IDE / 工具链默认一致）
VENV_DIR = REPO_ROOT / ".venv"


def in_venv():
    """判断当前解释器是否运行在虚拟环境中 (venv/virtualenv 通用判据)"""
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _venv_python(venv_dir):
    """返回虚拟环境内 python 解释器路径 (按平台区分 Scripts/bin)"""
    venv_dir = Path(venv_dir)
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_tool_available():
    """检测 venv 工具是否可用

    仅有 venv 模块不够：Debian/Ubuntu 系统 Python 常缺 ensurepip
    （需 apt 安装 python3-venv），此时 python -m venv 会创建失败。
    因此两者同时存在才判定可用。
    """
    import importlib.util
    importlib.invalidate_caches()
    return (
        importlib.util.find_spec("venv") is not None
        and importlib.util.find_spec("ensurepip") is not None
    )


def _apt_install_venv_tool():
    """Linux 下通过 apt 安装 python3-venv (尝试 sudo 与直接执行)"""
    print("  [Linux] 尝试 apt 安装 python3-venv ...")
    if shutil.which("apt-get") is None:
        print("  未检测到 apt-get, 跳过")
        return False
    apt_steps = [
        ["apt-get", "update"],
        ["apt-get", "install", "-y", "python3-venv"],
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
    return _venv_tool_available()


def _create_venv(venv_dir):
    """创建虚拟环境 (--system-site-packages 复用系统级硬件库, 如 pinpong)

    返回 True 表示创建成功且解释器可用。
    """
    print(f"  创建虚拟环境: {venv_dir} ...")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "venv", "--system-site-packages",
             str(venv_dir)],
            timeout=600,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    except Exception as e:
        print(f"  创建虚拟环境失败: {e}")
        return False
    if proc.returncode != 0:
        tail = (proc.stdout or b"")[-2000:].decode("utf-8", errors="ignore")
        print(f"  创建虚拟环境失败 (返回码={proc.returncode})")
        if tail.strip():
            print("  --- 输出尾部 ---\n" + tail)
        return False
    return _venv_python(venv_dir).exists()


def _reexec_in_venv(venv_python):
    """用 .venv 内的解释器重新执行本脚本 (透传原始参数), 完成后退出

    子进程运行于 venv 中 (in_venv() 为 True), 不会再次触发引导, 无递归风险。
    """
    cmd = [str(venv_python), os.path.abspath(__file__)] + sys.argv[1:]
    print("  切换到虚拟环境执行:", " ".join(cmd))
    print()
    try:
        code = subprocess.call(cmd)
    except Exception as e:
        print(f"  虚拟环境内执行失败: {e}")
        sys.exit(1)
    sys.exit(code)


def ensure_venv():
    """确保依赖安装发生在虚拟环境中（不在则自动引导）

    逻辑:
    - 已在 venv: 返回 True, 继续正常安装
    - 不在 venv:
      * venv 工具可用: .venv 存在(且解释器完整) -> re-exec 进入;
        不存在/残缺 -> 创建后 re-exec 进入
      * venv 工具不可用: Linux 走 sudo apt 安装 python3-venv 后重试;
        Windows 仅提示, 降级在当前解释器继续
    返回 True 表示继续在当前解释器安装; re-exec 成功则不会返回 (sys.exit)。
    """
    print("=" * 50)
    print("检查虚拟环境 ...")
    print("=" * 50)
    if in_venv():
        print("  已在虚拟环境中:", sys.prefix)
        return True
    print("  当前不在虚拟环境中")

    if not _venv_tool_available():
        print("  venv 工具不可用 (缺少 venv/ensurepip 模块)")
        if sys.platform.startswith("linux"):
            if not _apt_install_venv_tool():
                print("  警告: python3-venv 自动安装失败, "
                      "降级在当前环境继续安装依赖")
                return True
            print("  python3-venv 安装成功")
        else:
            # Windows: venv 属标准库, 缺失说明 Python 安装不完整, 仅提示
            print("  提示: Windows 下 venv 为标准库, 缺失请修复/重装 Python; "
                  "本次降级在当前环境继续安装依赖")
            return True

    venv_python = _venv_python(VENV_DIR)
    if VENV_DIR.exists() and venv_python.exists():
        print(f"  检测到已有虚拟环境: {VENV_DIR}")
    else:
        if VENV_DIR.exists():
            print(f"  虚拟环境残缺 (缺少解释器), 重新创建: {VENV_DIR}")
            try:
                shutil.rmtree(VENV_DIR)
            except Exception as e:
                print(f"  清理残缺虚拟环境失败: {e}, "
                      "降级在当前环境继续安装依赖")
                return True
        if not _create_venv(VENV_DIR):
            print("  警告: 虚拟环境创建失败, 降级在当前环境继续安装依赖")
            return True
        print("  虚拟环境创建成功")
    _reexec_in_venv(venv_python)  # 不会返回
    return True  # 防御性返回, 正常不可达


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

    安装策略（优先系统默认源，失败回退官方源）：
      1. 优先使用系统默认源（不指定 -i），除非 PIP_INDEX_URL 非空时优先用它；
      2. 若 pip 输出包含 --break-system-packages (PEP 668) 错误，自动追加该参数重试；
      3. 若首选源安装失败，自动回退到官方 PyPI 源 PIP_FALLBACK_URL 重试一次
         （同样兼容 --break-system-packages）。
    """
    pkg_name = _split_pkg_name(pkg)
    if not pkg_name:
        print("  [SKIP] 空包名")
        return True
    if is_package_installed(pkg_name):
        print("  ", pkg_name, "已安装, 跳过")
        return True

    print("  正在安装", pkg_name, "...")

    # 首选源：PIP_INDEX_URL 非空时优先使用，否则走系统默认源（不加 -i）
    primary_extra = ["-i", PIP_INDEX_URL] if PIP_INDEX_URL else []

    def _try(cmd_base):
        code, out, err = _run_pip(cmd_base)
        if code == 0:
            return True
        combined = out + "\n" + err
        if "--break-system-packages" in combined:
            print(f"  {pkg_name} 需要 --break-system-packages, 重新安装 ...")
            rc, ro, re = _run_pip(cmd_base + ["--break-system-packages"])
            if rc == 0:
                return True
            print(f"  安装失败 {pkg_name} 返回码: {rc}")
            tail = (ro + "\n" + re)[-1000:]
            if tail.strip():
                print("  --- 错误尾部 ---\n" + tail)
            return False
        print(f"  安装失败 {pkg_name} 返回码: {code}")
        tail = combined[-1000:]
        if tail.strip():
            print("  --- 错误尾部 ---\n" + tail)
        return False

    base_cmd = [sys.executable, "-m", "pip", "install", pkg] + primary_extra
    if _try(base_cmd):
        print("  ", pkg_name, "安装完成")
        return True

    # 回退：官方 PyPI 源
    print(f"  首选源失败，回退官方源 {PIP_FALLBACK_URL} ...")
    fallback_cmd = [sys.executable, "-m", "pip", "install", pkg, "-i", PIP_FALLBACK_URL]
    if _try(fallback_cmd):
        print("  ", pkg_name, "安装完成")
        return True

    print("  提示: 建议使用虚拟环境安装依赖 (本脚本可自动创建 .venv):")
    print("    python -m venv .venv")
    print("    source .venv/bin/activate  # Linux/macOS")
    print("    .venv\\Scripts\\activate     # Windows")
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
    src = PIP_INDEX_URL if PIP_INDEX_URL else "系统默认源"
    print(f"正在安装依赖 ({req_path}) 首选源: {src}（失败回退官方源 {PIP_FALLBACK_URL}）")
    print("=" * 50)
    packages = []
    # utf-8-sig: 兼容 Windows 记事本等写入的带 BOM 文件, 避免首包名混入 \ufeff
    with open(req_path, "r", encoding="utf-8-sig") as f:
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
        print("用法: python common/install.py <requirements_path> [--huskylens] [--target <dir>]")
        sys.exit(2)
    return requirements_path, huskylens, target


if __name__ == "__main__":
    try:
        print("=" * 60)
        print("    依赖安装脚本（根目录统一）")
        print("=" * 60)
        print()
        requirements_path, huskylens, target = _parse_args(sys.argv)
        # 第 0 步: venv 引导（在 venv 内则直接继续; 否则创建/进入 .venv
        # 后 re-exec, 或按平台降级在当前环境继续）
        ensure_venv()
        print()
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
