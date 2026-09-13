#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
老人用药管理智能助手 - 统一启动入口（仅用于直接以文件方式启动的场景）

用途
----
本脚本按运行设备自动选择要启动的端，避免使用者手动区分 `cd server` / `cd family_monitor`
/ `cd elderly_assistant`：

- 识别为行空板（UNIHIKER M10，基于 Debian 10 buster 的 ARM 单板机）
  -> 启动老人端 `elderly_assistant/main.py`（os.execv 直接替换当前进程，
     不引入多余父进程，信号与 GUI 行为保持原生）
- 其他设备（Windows / macOS / 常规 Linux 服务器）
  -> 以 nohup 语义后台启动服务端 `server/main.py` 与子女端 `family_monitor/main.py`，
     两个子进程脱离当前终端会话，日志分别重定向到 `logs/server.out`、`logs/family.out`，
     本进程打印 PID 后立即退出，关闭终端不影响服务运行。

适用范围
--------
仅面向「直接双击 / 命令行执行文件」的使用方式。生产环境的进程守护（systemd /
launchd / NSSM）与公网访问（Cloudflare 隧道或 DDNS + Caddy）请统一使用
`setup.sh` / `setup.ps1`，本脚本不参与也不重复其职责。

命令行参数
----------
所有未被本脚本消费的参数会原样透传给被启动的子程序，例如：

    python main.py --debug          # 行空板上等价于 elderly_assistant/main.py --debug
    python main.py --force-elderly  # 强制以老人端启动（用于非 M10 设备调试）
    python main.py --force-server   # 强制以服务端 + 子女端启动
    python main.py --check          # 只打印平台识别结果，不启动任何进程
"""

import os
import platform
import re
import socket
import subprocess
import sys
from pathlib import Path

# 仓库根目录：本文件所在目录
PROJECT_ROOT = Path(__file__).resolve().parent

# 子程序相对路径（相对 PROJECT_ROOT）
ELDERLY_ENTRY = PROJECT_ROOT / "elderly_assistant" / "main.py"
SERVER_ENTRY = PROJECT_ROOT / "server" / "main.py"
FAMILY_ENTRY = PROJECT_ROOT / "family_monitor" / "main.py"

# 后台模式的日志目录与文件
LOG_DIR = PROJECT_ROOT / "logs"
SERVER_LOG = LOG_DIR / "server.out"
FAMILY_LOG = LOG_DIR / "family.out"

# 本脚本自身消费、不透传给子程序的参数
_OWN_FLAGS = {"--force-elderly", "--force-server", "--check"}


# --------------------------------------------------------------------------
# 平台识别
# --------------------------------------------------------------------------

def _read_os_release():
    """解析 /etc/os-release 为字典（不存在或不可读时返回空字典）。

    值可能带引号（如 ID="debian"），统一去除首尾引号后返回小写键值。
    """
    info = {}
    path = Path("/etc/os-release")
    try:
        if not path.is_file():
            return info
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                # 跳过空行与注释行，避免把 `# comment` 误解析成键值对
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                info[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        # 权限不足 / IO 异常一律视为「无法识别」，交由后续特征兜底
        return {}
    return info


def _read_device_tree_model():
    """读取 /proc/device-tree/model 的设备树型号字符串。

    该文件以 NUL 结尾（内核导出的 FDT 字符串属性），需去除尾部 \\x00，
    否则字符串比较与打印都会出现异常字符。
    """
    path = Path("/proc/device-tree/model")
    try:
        if not path.is_file():
            return ""
        raw = path.read_bytes()
    except OSError:
        return ""
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()


def _has_unihiker_marker_file():
    """检查出厂配置文件特征：/etc/unihiker* 是否存在。

    行空板出厂镜像会在 /etc 下放置 unihiker 相关配置（如 unihiker.conf、
    unihiker_version 等），文件名不固定，因此用前缀匹配而非精确名匹配。
    """
    etc_dir = Path("/etc")
    try:
        if not etc_dir.is_dir():
            return False
        for entry in etc_dir.iterdir():
            if entry.name.lower().startswith("unihiker"):
                return True
    except OSError:
        return False
    return False


def _hostname_has_unihiker():
    """检查主机名是否含 unihiker（行空板出厂主机名特征）。"""
    try:
        return "unihiker" in socket.gethostname().lower()
    except OSError:
        return False


def detect_unihiker():
    """识别当前设备是否为行空板（UNIHIKER M10）。

    采用「多特征任一命中」策略，逐条列出命中的证据便于排障：

    1. 设备树型号 /proc/device-tree/model 含 unihiker —— 最直接的硬件特征
    2. 主机名含 unihiker —— 出厂主机名特征
    3. /etc/unihiker* 配置文件存在 —— 出厂镜像特征
    4. ARM 架构（aarch64 / armv7l 等）+ Debian 10 buster —— 架构与发行版组合兜底

    第 4 条单独看会误伤「运行 Debian 10 的普通树莓派 / ARM 服务器」，
    但本脚本仅在「直接文件启动」场景使用，且提供 --force-server 显式覆盖，
    误判成本可接受；反之若漏判，行空板将去启动它跑不动的双端服务。

    返回:
        (is_unihiker: bool, reasons: list[str]) —— 命中的特征描述列表；
        非 Linux 平台直接返回 (False, [])，不做任何文件探测。
    """
    reasons = []

    # Windows / macOS 不可能是行空板，提前短路，避免无谓的 /proc、/etc 探测
    if platform.system() != "Linux":
        return False, reasons

    model = _read_device_tree_model()
    if "unihiker" in model.lower():
        reasons.append(f"设备树型号匹配: /proc/device-tree/model = {model}")

    if _hostname_has_unihiker():
        reasons.append(f"主机名匹配: {socket.gethostname()}")

    if _has_unihiker_marker_file():
        reasons.append("出厂配置文件匹配: /etc/unihiker* 存在")

    os_release = _read_os_release()
    distro_id = os_release.get("ID", "").lower()
    version_id = os_release.get("VERSION_ID", "").strip()
    codename = os_release.get("VERSION_CODENAME", "").lower()
    machine = platform.machine().lower()

    # ID 可能是 debian，也可能是基于 debian 的衍生版（ID_LIKE 含 debian）
    id_like = os_release.get("ID_LIKE", "").lower()
    is_debian = distro_id == "debian" or "debian" in id_like
    # VERSION_ID 形如 "10"，也兼容 "10.13" 这类带小版本号的写法
    is_v10 = bool(re.match(r"^10(\.|$)", version_id)) or codename == "buster"
    is_arm = machine.startswith("aarch64") or machine.startswith("arm")

    if is_debian and is_v10 and is_arm:
        reasons.append(
            f"架构与发行版组合匹配: {machine} + {distro_id or '?'} "
            f"{version_id or codename or '?'}"
        )

    return bool(reasons), reasons


# --------------------------------------------------------------------------
# 启动逻辑
# --------------------------------------------------------------------------

def _passthrough_args():
    """返回需要透传给子程序的命令行参数（剔除本脚本自身的控制参数）。"""
    return [a for a in sys.argv[1:] if a not in _OWN_FLAGS]


def _python_executable():
    """返回用于启动子程序的 Python 解释器路径。

    优先使用仓库根 .venv 内的解释器：server / family_monitor 的依赖统一装在
    .venv 中，若用系统 Python 启动会因缺依赖而失败（各子程序虽有自愈重启逻辑，
    但后台模式下重启日志不易察觉，此处提前规避）。
    """
    if os.name == "nt":
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _require_entry(entry):
    """校验子程序入口文件存在，缺失时给出明确提示并退出。"""
    if not entry.is_file():
        print(f"[错误] 未找到启动入口: {entry}")
        print("       请确认仓库文件完整（可执行 git status 检查），或重新克隆仓库。")
        sys.exit(1)


def start_elderly(extra_args):
    """启动老人端：用 os.execv 直接把当前进程替换为 elderly_assistant/main.py。

    使用 exec 而非 subprocess 的原因：
    - 行空板上老人端是 GUI 前台程序，需要直接持有终端与信号（Ctrl+C / SIGTERM），
      多一层父进程会导致信号需要转发、退出码需要透传，徒增复杂度与故障点；
    - 老人端自身已实现依赖检查与 signal_handler，无需外层再包一层守护。
    """
    _require_entry(ELDERLY_ENTRY)

    python_exe = _python_executable()
    argv = [python_exe, str(ELDERLY_ENTRY)] + extra_args

    print("检测结果: 行空板 (UNIHIKER M10) -> 启动老人端")
    print(f"执行: {' '.join(argv)}")
    print("-" * 60)
    sys.stdout.flush()

    # 老人端内部会 chdir 到自身目录，此处无需预先切换工作目录
    try:
        os.execv(python_exe, argv)
    except OSError as e:
        # execv 成功时不会返回；走到这里说明替换失败（如解释器路径失效）
        print(f"[错误] 启动老人端失败: {e}")
        sys.exit(1)


def _spawn_background(entry, log_path, extra_args):
    """以 nohup 语义后台启动一个子程序，返回 (Popen 对象, 日志文件句柄)。

    脱离终端会话的实现按平台区分：
    - POSIX: start_new_session=True 等价于 setsid()，子进程成为新会话首进程，
      终端关闭时发出的 SIGHUP 不会传递给它（即 nohup 的核心效果）；
    - Windows: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP，子进程脱离父控制台，
      不随父窗口关闭而结束，且不接收父进程组的 Ctrl+C / Ctrl+Break。

    stdin 置空、stdout/stderr 重定向到日志文件，避免子进程因终端消失而在
    写日志时收到 EPIPE / EBADF 而异常退出。
    """
    _require_entry(entry)

    python_exe = _python_executable()
    # 传相对文件名而非绝对路径：子程序内部用 uvicorn.run("main:app", ...) 以
    # 「模块名:属性」方式加载 ASGI 应用，uvicorn 会按 sys.path 导入 main 模块。
    # Python 把「脚本所在目录」加入 sys.path[0]，二者结合才能解析到正确的 main；
    # 若此处传绝对路径，虽然 sys.path[0] 仍是该目录，但配合下方 PYTHONPATH
    # 可确保 server / family_monitor 各自的同名 main 模块不串味。
    argv = [python_exe, entry.name] + extra_args

    # 以追加方式打开，保留历史日志便于回溯问题
    log_file = open(log_path, "a", encoding="utf-8", errors="replace")
    log_file.write(
        f"\n{'=' * 60}\n"
        f"工作目录: {entry.parent}\n"
        f"启动命令: {' '.join(argv)}\n"
        f"{'=' * 60}\n"
    )
    log_file.flush()

    # 显式把子程序目录放到 PYTHONPATH 首位：uvicorn 以 "main:app" 字符串加载应用时
    # 会重新 import main 模块，仅靠 cwd 在部分启动方式下不足以保证解析到同目录的 main。
    child_env = os.environ.copy()
    existing_path = child_env.get("PYTHONPATH", "")
    child_env["PYTHONPATH"] = (
        str(entry.parent) + (os.pathsep + existing_path if existing_path else "")
    )

    popen_kwargs = {
        "cwd": str(entry.parent),
        "env": child_env,
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(argv, **popen_kwargs)
    except OSError as e:
        log_file.close()
        print(f"[错误] 启动 {entry.name} 失败: {e}")
        sys.exit(1)

    return proc, log_file


def start_server_and_family(extra_args):
    """后台启动服务端与子女端，打印 PID 后本进程立即退出。

    两个服务互不依赖启动顺序：子女端通过 HTTP 反向代理访问服务端，
    服务端未就绪时子女端只是请求失败并重试，不会启动崩溃，
    因此无需等待与健康检查编排。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("检测结果: 非行空板设备 -> 后台启动服务端与子女端")
    print("-" * 60)

    started = []
    for name, entry, log_path in (
        ("服务端 (server)", SERVER_ENTRY, SERVER_LOG),
        ("子女端 (family_monitor)", FAMILY_ENTRY, FAMILY_LOG),
    ):
        proc, log_file = _spawn_background(entry, log_path, extra_args)
        started.append((name, proc, log_path))
        # 父进程不再需要日志句柄，子进程已持有各自的副本；
        # 及时关闭避免父进程退出前占用文件描述符
        log_file.close()

    for name, proc, log_path in started:
        print(f"  {name}")
        print(f"    PID : {proc.pid}")
        print(f"    日志: {log_path}")

    print("-" * 60)
    print("两个服务已在后台运行，关闭当前终端不会影响其运行。")
    if os.name == "nt":
        print("停止服务: taskkill /PID <pid> /F")
    else:
        print("停止服务: kill <pid>")
    print("查看日志: tail -f logs/server.out  |  tail -f logs/family.out")


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    extra_args = _passthrough_args()

    force_elderly = "--force-elderly" in args
    force_server = "--force-server" in args

    if force_elderly and force_server:
        print("[错误] --force-elderly 与 --force-server 互斥，不能同时指定。")
        sys.exit(2)

    is_unihiker, reasons = detect_unihiker()

    print("=" * 60)
    print(" 老人用药管理智能助手 - 统一启动入口")
    print("=" * 60)
    print(f"  操作系统: {platform.system()} {platform.release()}")
    print(f"  处理器架构: {platform.machine()}")
    os_release = _read_os_release()
    if os_release:
        pretty = os_release.get("PRETTY_NAME") or os_release.get("NAME", "")
        if pretty:
            print(f"  发行版: {pretty}")
    if reasons:
        print("  行空板特征命中:")
        for r in reasons:
            print(f"    - {r}")
    else:
        print("  行空板特征命中: 无")
    print("=" * 60)

    if "--check" in args:
        # 仅做平台识别自检，不产生任何启动副作用
        target = "老人端 (elderly_assistant)" if is_unihiker else "服务端 + 子女端"
        print(f"识别结论: {'行空板' if is_unihiker else '非行空板'}，将启动: {target}")
        print("（--check 模式，未启动任何进程）")
        return

    if force_elderly:
        print("已指定 --force-elderly，跳过自动识别。")
        start_elderly(extra_args)
    elif force_server:
        print("已指定 --force-server，跳过自动识别。")
        start_server_and_family(extra_args)
    elif is_unihiker:
        start_elderly(extra_args)
    else:
        start_server_and_family(extra_args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # 用户主动中断属正常退出，不打印堆栈
        print("\n已取消。")
        sys.exit(130)
