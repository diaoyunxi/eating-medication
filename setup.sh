#!/bin/sh
# -*- coding: utf-8 -*-
# ============================================================
# eating-medication 一键部署引导器（POSIX sh 兼容）
#
# 功能：检测操作系统，下载并执行对应平台脚本
#   - Linux  → deploy/setup-linux.sh（bash）
#   - macOS  → deploy/setup-mac.sh（zsh）
#   - Windows → 提示使用 setup.ps1
#
# 用法（curl 一键部署）：
#   curl -fsSL https://raw.githubusercontent.com/diaoyunxi/eating-medication/main/setup.sh | sh
#
# 或先下载再执行：
#   curl -fsSL https://raw.githubusercontent.com/diaoyunxi/eating-medication/main/setup.sh -o setup.sh
#   sh setup.sh
#
# 下载源回退顺序：
#   1. GitHub raw 直连
#   2. gh.llkk.cc 镜像
#   3. gh-proxy.com 镜像
# ============================================================

# 仓库常量
REPO_OWNER="diaoyunxi"
REPO_NAME="eating-medication"
REPO_BRANCH="main"

# GitHub raw 基础 URL
RAW_BASE="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${REPO_BRANCH}"

# 镜像站列表（GitHub raw 失败时依次尝试）
MIRRORS="
https://gh.llkk.cc
https://gh-proxy.com
"

# 平台脚本相对路径
LINUX_SCRIPT="deploy/setup-linux.sh"
MAC_SCRIPT="deploy/setup-mac.sh"

# 临时目录
TMP_DIR=$(mktemp -d 2>/dev/null || /tmp/em_setup_$$)
trap 'rm -rf "$TMP_DIR" 2>/dev/null' EXIT INT TERM

# ============================================================
# 日志函数（POSIX 兼容，不依赖 echo -e）
# ============================================================
log_info() {
    printf '[INFO] %s\n' "$1"
}

log_warn() {
    printf '[WARN] %s\n' "$1" >&2
}

log_error() {
    printf '[ERROR] %s\n' "$1" >&2
}

log_separator() {
    printf '============================================================\n'
}

# ============================================================
# 检测操作系统
# ============================================================
detect_os() {
    uname_s=$(uname -s 2>/dev/null)
    case "$uname_s" in
        Linux*)
            echo "linux"
            ;;
        Darwin*)
            echo "macos"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            echo "windows"
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

# ============================================================
# 检测系统架构
# ============================================================
detect_arch() {
    uname_m=$(uname -m 2>/dev/null)
    case "$uname_m" in
        x86_64|amd64)
            echo "amd64"
            ;;
        aarch64|arm64)
            echo "arm64"
            ;;
        armv7l|armv6l)
            echo "arm"
            ;;
        i386|i686)
            echo "386"
            ;;
        *)
            echo "$uname_m"
            ;;
    esac
}

# ============================================================
# 下载文件（依次尝试 GitHub raw 与镜像站）
# ============================================================
download_file() {
    # 参数：$1 = 相对路径，$2 = 保存路径
    rel_path="$1"
    save_path="$2"

    # 构建下载源列表（GitHub raw 在前，镜像站在后）
    urls="${RAW_BASE}/${rel_path}"
    for mirror in $MIRRORS; do
        urls="${urls}
${mirror}/https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${REPO_BRANCH}/${rel_path}"
    done

    # 尝试下载工具：curl 优先，wget 后备
    for url in $urls; do
        log_info "尝试下载: ${url}"
        if command -v curl >/dev/null 2>&1; then
            if curl -fsSL --connect-timeout 15 --max-time 60 "$url" -o "$save_path" 2>/dev/null; then
                log_info "下载成功"
                return 0
            fi
        elif command -v wget >/dev/null 2>&1; then
            if wget -q --timeout=15 "$url" -O "$save_path" 2>/dev/null; then
                log_info "下载成功"
                return 0
            fi
        fi
        log_warn "下载失败，尝试下一个源..."
    done

    log_error "所有下载源均失败: ${rel_path}"
    return 1
}

# ============================================================
# 主流程
# ============================================================
main() {
    log_separator
    printf '  eating-medication 一键部署引导器\n'
    log_separator
    printf '\n'

    # 检测操作系统
    os_type=$(detect_os)
    arch=$(detect_arch)
    log_info "操作系统: ${os_type}"
    log_info "系统架构: ${arch}"
    printf '\n'

    case "$os_type" in
        linux)
            log_info "Linux 系统，将下载并执行 deploy/setup-linux.sh（bash）"
            script_rel="$LINUX_SCRIPT"
            executor="bash"
            ;;
        macos)
            log_info "macOS 系统，将下载并执行 deploy/setup-mac.sh（zsh）"
            script_rel="$MAC_SCRIPT"
            # macOS 自带 zsh
            if command -v zsh >/dev/null 2>&1; then
                executor="zsh"
            else
                log_warn "未检测到 zsh，回退使用 bash"
                executor="bash"
            fi
            ;;
        windows)
            log_error "检测到 Windows / MSYS2 / Cygwin 环境"
            log_error "请使用 PowerShell 执行 setup.ps1："
            printf '\n'
            printf '  irm https://raw.githubusercontent.com/%s/%s/%s/setup.ps1 | iex\n' \
                "$REPO_OWNER" "$REPO_NAME" "$REPO_BRANCH"
            printf '\n'
            exit 1
            ;;
        *)
            log_error "不支持的操作系统: ${os_type} ($(uname -s))"
            log_error "请手动克隆仓库并参照 README.md 部署"
            exit 1
            ;;
    esac

    # 检查执行器是否存在
    if ! command -v "$executor" >/dev/null 2>&1; then
        log_error "未找到 ${executor}，请安装后重试"
        exit 1
    fi

    # 下载平台脚本
    log_separator
    printf '  下载平台脚本: %s\n' "$script_rel"
    log_separator
    printf '\n'

    script_path="${TMP_DIR}/$(basename "$script_rel")"
    if ! download_file "$script_rel" "$script_path"; then
        log_error "无法下载平台脚本，请检查网络后重试"
        log_error "也可手动克隆仓库后执行: ${executor} ${script_rel}"
        exit 1
    fi

    # 设置可执行权限
    chmod +x "$script_path" 2>/dev/null || true

    # 传递环境变量与参数给平台脚本
    log_separator
    printf '  执行平台脚本: %s %s\n' "$executor" "$script_path"
    log_separator
    printf '\n'

    # 透传所有参数
    # curl|sh 模式下 stdin 是管道（已耗尽），需重定向到 /dev/tty 以支持交互式 read
    if [ -t 0 ]; then
        # stdin 已是终端，直接执行
        exec "$executor" "$script_path" "$@"
    elif (exec </dev/tty) 2>/dev/null; then
        # stdin 非终端（curl|sh 模式），但 /dev/tty 可用（真实终端环境）
        exec "$executor" "$script_path" "$@" </dev/tty
    else
        # /dev/tty 不可用（沙箱/CI 等无交互环境），stdin 指向 /dev/null
        exec "$executor" "$script_path" "$@" </dev/null
    fi
}

# 执行主流程
main "$@"
