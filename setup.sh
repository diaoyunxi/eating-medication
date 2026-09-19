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
# 说明：本引导器只负责「下载并执行」平台脚本。具体安装内容
#   （老人端 elderly_assistant / 服务端 server + 子女端 family_monitor）
#   由 deploy/setup-linux.sh 自动判定：检测到 aarch64/arm64 + Debian 10
#   (buster) 即视为老人端（行空板 M10），仅安装老人端依赖与系统工具；
#   其余环境走完整服务端流程。
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
#   2. gh.my-website.ccwu.cc 镜像
#   3. gh-proxy.com 镜像
# ============================================================

# 仓库常量
REPO_OWNER="diaoyunxi"
REPO_NAME="eating-medication"
REPO_BRANCH="main"

# GitHub raw 基础 URL
RAW_BASE="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${REPO_BRANCH}"

# 镜像站列表（GitHub raw 失败时依次尝试）
# 注意：每个镜像站会将完整 raw URL 拼接到其后，如
#   https://gh.my-website.ccwu.cc/https://raw.githubusercontent.com/...
# 用空格分隔的字符串；下载时由 download_file 逐词读取（兼容 bash/zsh/dash，
# 不依赖未加引号变量的默认单词拆分，因为 zsh 默认不开启 SH_WORD_SPLIT）。
MIRROR_LIST="https://gh.my-website.ccwu.cc https://gh-proxy.com"

# 平台脚本相对路径
LINUX_SCRIPT="deploy/setup-linux.sh"
MAC_SCRIPT="deploy/setup-mac.sh"

# 临时目录
# 注意：mktemp 在部分 busybox/dash 环境下可能返回空或不可写路径，
# 这里改用「显式 mkdir + 回退路径」，确保目录一定存在且可写。
TMP_DIR=""
if command -v mktemp >/dev/null 2>&1; then
    TMP_DIR=$(mktemp -d 2>/dev/null)
fi
if [ -z "$TMP_DIR" ] || [ ! -d "$TMP_DIR" ] || [ ! -w "$TMP_DIR" ]; then
    TMP_DIR="/tmp/em_setup_$$"
    mkdir -p "$TMP_DIR" 2>/dev/null || true
fi
# 兜底：若仍无效，则直接用 /tmp（绝不放空，避免写到当前目录或根）
if [ -z "$TMP_DIR" ] || [ ! -d "$TMP_DIR" ] || [ ! -w "$TMP_DIR" ]; then
    TMP_DIR="/tmp"
fi
trap 'rm -rf "/tmp/em_setup_$$" 2>/dev/null' EXIT INT TERM

# ============================================================
# 日志函数（POSIX 兼容，不依赖 echo -e）
#   颜色：stdout 为终端且 TERM 非 dumb 时启用，否则自动降级为无色
# ============================================================
# 是否启用颜色：仅当标准输出是 TTY 且终端类型不是 dumb
if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
    _USE_COLOR=1
else
    _USE_COLOR=0
fi
if [ "$_USE_COLOR" -eq 1 ]; then
    C_RESET='\033[0m'
    C_BOLD='\033[1m'
    C_GREEN='\033[32m'
    C_YELLOW='\033[33m'
    C_RED='\033[31m'
    C_CYAN='\033[36m'
else
    C_RESET=''; C_BOLD=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_CYAN=''
fi

log_info() {
    printf "${C_GREEN}[INFO]${C_RESET} %s\n" "$1"
}

log_warn() {
    printf "${C_YELLOW}[WARN]${C_RESET} %s\n" "$1" >&2
}

log_error() {
    printf "${C_RED}[ERROR]${C_RESET} %s\n" "$1" >&2
}

log_step() {
    printf "\n${C_CYAN}${C_BOLD}==> %s${C_RESET}\n" "$1"
}

log_separator() {
    printf "${C_BOLD}============================================================${C_RESET}\n"
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
    # 镜像站拼接规则：<mirror>/<完整 raw URL>，例如
    #   https://gh.my-website.ccwu.cc/https://raw.githubusercontent.com/...
    # 兼容说明：zsh 默认不按空格拆分未加引号的变量，故不能写 "$VAR" 后靠 for 拆分。
    # 这里用「逐行写入临时文件 + while read 逐行读取」的方式，bash/zsh/dash 行为完全一致。

    # 生成镜像 URL 列表文件（每行一个完整 URL）
    : > "${TMP_DIR}/_mirror_urls.tmp"
    # 用 tr 将空格转为换行（外部命令，不依赖 shell 的单词拆分规则，
    # 因此 bash / zsh / dash 下行为完全一致），再逐行读取。
    echo "$MIRROR_LIST" | tr ' ' '\n' | while IFS= read -r _mirror; do
        [ -z "$_mirror" ] && continue
        _mirror_trim="${_mirror%/}"
        echo "${_mirror_trim}/https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${REPO_BRANCH}/${rel_path}"
    done >> "${TMP_DIR}/_mirror_urls.tmp" 2>/dev/null || true

    # 组合完整 URL 列表：raw 直连在前，镜像在后
    : > "${TMP_DIR}/_all_urls.tmp"
    echo "${RAW_BASE}/${rel_path}" >> "${TMP_DIR}/_all_urls.tmp"
    [ -s "${TMP_DIR}/_mirror_urls.tmp" ] && cat "${TMP_DIR}/_mirror_urls.tmp" >> "${TMP_DIR}/_all_urls.tmp"

    # 防御：URL 列表文件无效时明确报错，避免静默走到「所有源失败」造成误判
    if [ ! -s "${TMP_DIR}/_all_urls.tmp" ]; then
        log_error "下载源列表为空（临时目录不可写？TMP_DIR=${TMP_DIR}），无法继续"
        return 1
    fi

    # 调试：打印本次将尝试的所有下载源，便于网络排查
    log_info "本次候选下载源："
    while IFS= read -r _dbg_url; do
        [ -z "$_dbg_url" ] && continue
        printf '    - %s\n' "$_dbg_url"
    done < "${TMP_DIR}/_all_urls.tmp"

    # 尝试下载工具：curl 优先，wget 后备
    # 用 while read 逐行读取 URL（避免 zsh 对未加引号变量的拆分差异）
    while IFS= read -r url; do
        [ -z "$url" ] && continue
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
    done < "${TMP_DIR}/_all_urls.tmp"

    log_error "所有下载源均失败: ${rel_path}"
    return 1
}

# ============================================================
# 主流程
# ============================================================
main() {
    log_separator
    printf "${C_BOLD}${C_CYAN}  eating-medication 一键部署引导器${C_RESET}\n"
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
    # curl|sh 模式下 stdin 是管道（已耗尽），read 会立即收到 EOF。
    # 检测策略：有真实终端则重定向到 /dev/tty，无则走向 /dev/null（非交互）。
    if [ -t 0 ]; then
        # stdin 已是终端（先下载再执行），直接执行，read 正常交互
        exec "$executor" "$script_path" "$@"
    elif stty < /dev/tty >/dev/null 2>&1; then
        # stdin 是管道，但 /dev/tty 可用（真实终端，如 curl|sh 但用户有交互终端）
        # 将 stdin 指向 /dev/tty，read 命令从终端读取用户输入
        exec "$executor" "$script_path" "$@" </dev/tty
    else
        # /dev/tty 不可用（沙箱/CI/无交互环境），stdin 指向 /dev/null
        # 平台脚本中的 read 遇到 EOF 时通过 || true 使用默认值
        exec "$executor" "$script_path" "$@" </dev/null
    fi
}

# 入口：检测 --uninstall / -u 参数，直接透传给平台脚本
main "$@"
