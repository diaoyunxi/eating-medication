#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# eating-medication Linux 一键部署脚本（极简版）
#
# 功能：安装系统依赖 + 克隆仓库
#
# 适用：Debian/Ubuntu（apt）、Fedora/RHEL（dnf/yum）、Arch（pacman）、Alpine（apk）
# 默认部署目录 /opt/eating-medication。
#
# 用法：
#   sudo bash deploy/setup-linux.sh                 # 安装
#   sudo bash deploy/setup-linux.sh -u              # 卸载（或 --uninstall）
#
# 幂等：可重复执行（更新代码 + 重装依赖）。

set -euo pipefail

# ===== 可配置变量 =====
DEPLOY_DIR="${DEPLOY_DIR:-/opt/eating-medication}"
REPO_GITHUB="https://github.com/diaoyunxi/eating-medication.git"
REPO_GITEE="https://gitee.com/diaoyunxi/eating-medication.git"

# 当前是否已是 root：是则不加 sudo
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

# ============================================================
# 日志函数
# ============================================================
log_info()  { printf '\033[32m[INFO]\033[0m %s\n' "$1"; }
log_warn()  { printf '\033[33m[WARN]\033[0m %s\n' "$1" >&2; }
log_error() { printf '\033[31m[ERROR]\033[0m %s\n' "$1" >&2; }
log_step()  { printf '\n\033[36m==> %s\033[0m\n' "$1"; }

# ============================================================
# 检测系统信息
# ============================================================
detect_system() {
    log_step "检测系统信息"

    # 检测架构
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64|amd64)  ARCH_NORM="amd64" ;;
        aarch64|arm64) ARCH_NORM="arm64" ;;
        armv7l)        ARCH_NORM="arm" ;;
        *)             ARCH_NORM="$ARCH" ;;
    esac
    log_info "系统架构: ${ARCH} (${ARCH_NORM})"

    # 检测包管理器
    PM=""
    if command -v apt-get >/dev/null 2>&1; then
        PM="apt"
    elif command -v dnf >/dev/null 2>&1; then
        PM="dnf"
    elif command -v yum >/dev/null 2>&1; then
        PM="yum"
    elif command -v pacman >/dev/null 2>&1; then
        PM="pacman"
    elif command -v apk >/dev/null 2>&1; then
        PM="apk"
    else
        log_error "未识别的包管理器，请手动安装 git/python3/pip 后重试"
        exit 1
    fi
    log_info "包管理器: ${PM}"

    # 检测发行版
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        log_info "发行版: ${PRETTY_NAME:-${NAME:-unknown}}"
    fi
}

# ============================================================
# 包管理器更新 + 安装系统依赖
# ============================================================
install_system_deps() {
    log_step "安装系统依赖"

    case "$PM" in
        apt)
            $SUDO apt-get update -y 2>/dev/null || log_warn "apt-get update 失败（镜像源同步中？），继续安装..."
            $SUDO apt-get install -y git python3 python3-pip curl
            ;;
        dnf)
            $SUDO dnf install -y git python3 python3-pip curl
            ;;
        yum)
            $SUDO yum install -y git python3 python3-pip curl
            ;;
        pacman)
            $SUDO pacman -Sy --noconfirm git python python-pip curl
            ;;
        apk)
            $SUDO apk add --no-cache git python3 py3-pip curl
            ;;
    esac

    PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0)"
    log_info "Python 版本: ${PY_VER}"
}

# ============================================================
# git clone（GitHub → Gitee 回退）
# ============================================================
clone_repo() {
    log_step "克隆仓库"

    if [ -d "$DEPLOY_DIR/.git" ]; then
        log_info "仓库已存在，拉取最新代码..."
        $SUDO git -C "$DEPLOY_DIR" pull --ff-only 2>/dev/null || \
            $SUDO git -C "$DEPLOY_DIR" pull 2>/dev/null || \
            log_warn "git pull 失败，继续使用现有代码"
    else
        log_info "尝试从 GitHub 克隆: ${REPO_GITHUB}"
        if $SUDO git clone --depth 1 "$REPO_GITHUB" "$DEPLOY_DIR" 2>/dev/null; then
            log_info "GitHub 克隆成功"
        else
            log_warn "GitHub 克隆失败（超时或网络问题），尝试 Gitee 镜像..."
            log_info "尝试从 Gitee 克隆: ${REPO_GITEE}"
            if $SUDO git clone --depth 1 "$REPO_GITEE" "$DEPLOY_DIR" 2>/dev/null; then
                log_info "Gitee 克隆成功"
            else
                log_error "GitHub 和 Gitee 均克隆失败"
                log_error "请检查网络或手动克隆仓库到 ${DEPLOY_DIR}"
                exit 1
            fi
        fi
    fi
}

# ============================================================
# 创建 Python 虚拟环境并安装依赖
# ============================================================
setup_venv() {
    log_step "配置 Python 虚拟环境"

    # 检测 Python 版本（需 >= 3.8）
    local py_ver py_major py_minor
    py_ver="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0)"
    py_major="${py_ver%%.*}"
    py_minor="${py_ver#*.}"
    if [ "$py_major" -lt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -lt 8 ]; }; then
        log_error "Python 版本过低: ${py_ver}，需要 >= 3.8"
        exit 1
    fi
    log_info "Python 版本: ${py_ver}"

    # 若已有 venv 且 Python 版本不符，删除重建
    if [ -d "$DEPLOY_DIR/venv" ]; then
        local old_py
        old_py="$("$DEPLOY_DIR/venv/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0)"
        if [ "$old_py" != "$py_ver" ]; then
            log_warn "已有 venv (Python ${old_py}) 与当前版本不符，重建..."
            $SUDO rm -rf "$DEPLOY_DIR/venv"
        fi
    fi

    # 创建虚拟环境
    if [ ! -d "$DEPLOY_DIR/venv" ]; then
        log_info "创建虚拟环境..."
        $SUDO python3 -m venv "$DEPLOY_DIR/venv"
    fi

    # 升级 pip
    log_info "升级 pip..."
    $SUDO "$DEPLOY_DIR/venv/bin/pip" install --upgrade pip -q

    # 安装各模块依赖
    log_info "安装 server 依赖..."
    $SUDO "$DEPLOY_DIR/venv/bin/pip" install -r "$DEPLOY_DIR/server/requirements.txt" -q

    log_info "安装 family_monitor 依赖..."
    $SUDO "$DEPLOY_DIR/venv/bin/pip" install -r "$DEPLOY_DIR/family_monitor/requirements.txt" -q

    log_info "安装 elderly_assistant 依赖..."
    $SUDO "$DEPLOY_DIR/venv/bin/pip" install -r "$DEPLOY_DIR/elderly_assistant/requirements.txt" -q

    log_info "虚拟环境配置完成: ${DEPLOY_DIR/venv}"
}

# ============================================================
# 卸载：删除部署目录
# 保留：系统包（git/python3/curl 等）
# ============================================================
uninstall() {
    printf '\n'
    printf '============================================================\n'
    printf '  eating-medication 卸载\n'
    printf '  部署目录: %s\n' "$DEPLOY_DIR"
    printf '============================================================\n'

    if [ ! -d "$DEPLOY_DIR" ]; then
        log_info "未检测到已安装痕迹（部署目录不存在），无需卸载。"
        printf '\n'
        return 0
    fi

    log_info "已检测到安装，将执行卸载（删除部署目录）"

    # 删除部署目录
    log_step "删除部署目录"
    $SUDO rm -rf "$DEPLOY_DIR"
    log_info "已删除部署目录: ${DEPLOY_DIR}"

    # 完成提示
    printf '\n'
    printf '============================================================\n'
    printf '  卸载完成！\n'
    printf '============================================================\n'
    printf '\n'
    printf '  已删除: 部署目录 %s\n' "$DEPLOY_DIR"
    printf '  保留: 系统包 git, python3, curl 等\n'
    printf '\n'
}

# ============================================================
# 主流程
# ============================================================
main() {
    printf '\n'
    printf '============================================================\n'
    printf '  eating-medication Linux 一键部署（极简版）\n'
    printf '============================================================\n'

    # 1. 检测系统
    detect_system

    # 2. 安装系统依赖
    install_system_deps

    # 3. 克隆仓库
    clone_repo

    # 4. 配置 Python 虚拟环境
    setup_venv

    # 完成
    sleep 1
    printf '\n'
    printf '============================================================\n'
    printf '  部署完成！\n'
    printf '============================================================\n'
    printf '\n'
    printf '%s\n' '------------------------------------------------------------'
    printf '  后续步骤:\n'
    printf '  1) 启动服务:\n'
    printf '     cd %s && ./venv/bin/python main.py\n' "$DEPLOY_DIR"
    printf '  2) 更新代码（安全自动更新，保留 .env/data）:\n'
    printf '     cd %s && ./venv/bin/python updater.py\n' "$DEPLOY_DIR"
    printf '     或强制更新: cd %s && ./venv/bin/python updater.py --force\n' "$DEPLOY_DIR"
    printf '     注: 应用启动时也会自动检查更新（AUTO_PULL，默认开启）\n'
    printf '%s\n' '------------------------------------------------------------'
    printf '\n'
    printf '  如需卸载，执行:\n'
    printf '    sudo bash deploy/setup-linux.sh -u\n'
    printf '\n'
}

# 入口：检测 --uninstall 参数
if [ "${1:-}" = "--uninstall" ] || [ "${1:-}" = "-u" ]; then
    uninstall
    exit 0
fi

main "$@"
