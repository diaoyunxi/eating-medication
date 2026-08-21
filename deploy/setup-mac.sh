#!/usr/bin/env zsh
# -*- coding: utf-8 -*-
#
# eating-medication macOS 一键部署脚本（zsh）
#
# 功能：检测系统 → Homebrew 更新 → 询问访问模式（cloudflared/DDNS/仅内网）
#       → git clone（GitHub→Gitee 回退）→ 装依赖 → 生成 .env → launchd 服务
#
# 适用：macOS（Intel + Apple Silicon）
# 默认部署目录 /usr/local/eating-medication，运行用户当前用户。
#
# 用法：
#   sudo zsh deploy/setup-mac.sh                 # 默认域名 my-website.ccwu.cc
#   sudo DOMAIN=你的域名 zsh deploy/setup-mac.sh  # 自定义域名
#
# 幂等：可重复执行（更新代码 + 重装依赖 + 重启服务）。
#       .env 仅在不存在时生成，已存在则保留你的配置。

set -euo pipefail

# ===== 可配置变量 =====
DEPLOY_DIR="${DEPLOY_DIR:-/usr/local/eating-medication}"
DEPLOY_USER="${SUDO_USER:-$(whoami)}"
REPO_GITHUB="https://github.com/diaoyunxi/eating-medication.git"
REPO_GITEE="https://gitee.com/diaoyunxi/eating-medication.git"
DOMAIN="${DOMAIN:-my-website.ccwu.cc}"
SERVER_PREFIX="/eating-medication/server"
FAMILY_PREFIX="/eating-medication/family"
SERVER_PORT=1059
FAMILY_PORT=4430

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
        x86_64)  ARCH_NORM="amd64" ;;
        arm64)   ARCH_NORM="arm64" ;;
        *)       ARCH_NORM="$ARCH" ;;
    esac
    log_info "系统架构: ${ARCH} (${ARCH_NORM})"

    # macOS 版本
    local macos_ver
    macos_ver=$(sw_vers -productVersion 2>/dev/null || echo "unknown")
    log_info "macOS 版本: ${macos_ver}"

    # 检测 Homebrew
    if command -v brew >/dev/null 2>&1; then
        log_info "Homebrew: $(brew --version 2>/dev/null | head -1)"
    else
        log_warn "未检测到 Homebrew，正在安装..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || {
            log_error "Homebrew 安装失败，请手动安装: https://brew.sh"
            exit 1
        }
        # Apple Silicon 需要设置 PATH
        if [ "$ARCH_NORM" = "arm64" ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        else
            eval "$(/usr/local/bin/brew shellenv)"
        fi
        log_info "Homebrew 安装完成"
    fi
}

# ============================================================
# Homebrew 更新 + 安装系统依赖
# ============================================================
install_system_deps() {
    log_step "[1/9] 更新 Homebrew 并安装系统依赖"

    brew update 2>/dev/null || true
    brew install git python3 curl 2>/dev/null || true

    # 安装 gh CLI
    if ! command -v gh >/dev/null 2>&1; then
        log_info "安装 gh CLI..."
        brew install gh 2>/dev/null || true
    else
        log_info "gh CLI 已安装: $(gh --version | head -n1)"
    fi

    PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0)"
    log_info "Python 版本: ${PY_VER}"
}

# ============================================================
# 询问访问模式
# ============================================================
ask_access_mode() {
    log_step "[2/9] 选择公网访问模式"

    # 非交互模式：通过环境变量 ACCESS_MODE 指定
    if [ -n "${ACCESS_MODE:-}" ]; then
        log_info "使用环境变量 ACCESS_MODE=${ACCESS_MODE}"
        case "$ACCESS_MODE" in
            1) log_info "已选择: Cloudflare 隧道" ;;
            2) log_info "已选择: DDNS + Caddy" ;;
            3) log_info "已选择: 仅内网访问" ;;
            *) log_warn "无效选择，使用默认: Cloudflare 隧道"; ACCESS_MODE="1" ;;
        esac
        return 0
    fi

    printf '\n'
    printf '  1) Cloudflare 隧道（cloudflared）—— 推荐，本地无需公网IP\n'
    printf '  2) 动态域名解析（DDNS + Caddy 自动 HTTPS）—— 需公网IP\n'
    printf '  3) 仅内网访问 —— 不配置公网\n'
    printf '\n'
    printf '  请选择 [1/2/3] (默认 1): '
    read ACCESS_MODE || true
    ACCESS_MODE="${ACCESS_MODE:-1}"

    case "$ACCESS_MODE" in
        1) log_info "已选择: Cloudflare 隧道" ;;
        2) log_info "已选择: DDNS + Caddy" ;;
        3) log_info "已选择: 仅内网访问" ;;
        *) log_warn "无效选择，使用默认: Cloudflare 隧道"; ACCESS_MODE="1" ;;
    esac
}

# ============================================================
# Cloudflared 安装与配置
# ============================================================
install_cloudflared() {
    log_step "[3/9] 安装与配置 Cloudflare 隧道"

    # 安装 cloudflared
    if command -v cloudflared >/dev/null 2>&1; then
        log_info "cloudflared 已安装: $(cloudflared --version 2>&1 || echo '已存在')"
    else
        log_info "通过 Homebrew 安装 cloudflared..."
        brew install cloudflared 2>/dev/null || {
            log_warn "Homebrew 安装失败，尝试 GitHub Release 下载..."
            local cf_url=""
            case "$ARCH_NORM" in
                amd64) cf_url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz" ;;
                arm64) cf_url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz" ;;
                *)
                    log_error "不支持的架构: ${ARCH_NORM}"
                    return 1
                    ;;
            esac

            # 下载（GitHub 直连 → 镜像回退）
            local downloaded=false
            for url in "$cf_url" "https://gh.my-website.ccwu.cc/$cf_url" "https://gh-proxy.com/$cf_url"; do
                log_info "尝试下载: ${url}"
                if curl -fsSL --connect-timeout 15 --max-time 120 "$url" -o /tmp/cloudflared.tgz 2>/dev/null; then
                    downloaded=true
                    break
                fi
            done

            if [ "$downloaded" = true ]; then
                $SUDO tar -xzf /tmp/cloudflared.tgz -C /usr/local/bin/
                $SUDO chmod +x /usr/local/bin/cloudflared
                rm -f /tmp/cloudflared.tgz
                log_info "cloudflared 已安装到 /usr/local/bin/cloudflared"
            else
                log_error "下载 cloudflared 失败，请手动安装"
                return 1
            fi
        }
    fi

    # 选择认证方式
    printf '\n'
    printf '  Cloudflare 隧道认证方式:\n'
    printf '  1) Token（推荐）—— 在 Zero Trust 控制台创建隧道后粘贴 token\n'
    printf '  2) Login（交互式）—— 需浏览器授权\n'
    printf '\n'
    printf '  请选择 [1/2] (默认 1): '
    read CF_AUTH_MODE || true
    CF_AUTH_MODE="${CF_AUTH_MODE:-1}"

    local launch_agent_dir="/Library/LaunchDaemons"
    local cf_plist="$launch_agent_dir/com.cloudflare.cloudflared.plist"

    case "$CF_AUTH_MODE" in
        1)
            # Token 方式
            printf '  请粘贴隧道 Token（从 Cloudflare Zero Trust 控制台复制）:\n'
            printf '  > '
            read CF_TUNNEL_TOKEN || true

            if [ -z "$CF_TUNNEL_TOKEN" ]; then
                log_warn "Token 为空，跳过 cloudflared 服务创建"
                return 0
            fi

            # 创建 launchd plist
            $SUDO mkdir -p "$launch_agent_dir"
            $SUDO tee "$cf_plist" >/dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cloudflare.cloudflared</string>
    <key>ProgramArguments</key>
    <array>
        <string>cloudflared</string>
        <string>tunnel</string>
        <string>--no-autoupdate</string>
        <string>run</string>
        <string>--token</string>
        <string>${CF_TUNNEL_TOKEN}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/var/log/cloudflared.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/cloudflared.err.log</string>
</dict>
</plist>
EOF
            $SUDO chmod 644 "$cf_plist"
            $SUDO launchctl load -w "$cf_plist" 2>/dev/null || true
            log_info "Cloudflare 隧道已配置（Token 模式，launchd 守护）"
            log_info "请在 Zero Trust 控制台添加路由:"
            log_info "  ${SERVER_PREFIX} -> http://localhost:${SERVER_PORT}"
            log_info "  ${FAMILY_PREFIX} -> http://localhost:${FAMILY_PORT}"
            ;;
        2)
            # Login 方式
            log_info "执行 cloudflared tunnel login（将打开浏览器授权）..."
            cloudflared tunnel login || {
                log_error "cloudflared tunnel login 失败"
                log_error "请稍后手动执行: cloudflared tunnel login"
            }

            printf '  请输入隧道名称 (默认 eating-medication): '
            read CF_TUNNEL_NAME || true
            CF_TUNNEL_NAME="${CF_TUNNEL_NAME:-eating-medication}"

            cloudflared tunnel create "$CF_TUNNEL_NAME" 2>/dev/null && \
                log_info "隧道 ${CF_TUNNEL_NAME} 创建成功" || \
                log_warn "隧道创建失败，请手动执行: cloudflared tunnel create ${CF_TUNNEL_NAME}"

            log_info "请在 Zero Trust 控制台或 config.yml 中配置路由:"
            log_info "  ${SERVER_PREFIX} -> http://localhost:${SERVER_PORT}"
            log_info "  ${FAMILY_PREFIX} -> http://localhost:${FAMILY_PORT}"
            ;;
    esac
}

# ============================================================
# DDNS + Caddy 配置
# ============================================================
setup_ddns_caddy() {
    log_step "[3/9] 配置 DDNS + Caddy 自动 HTTPS"

    # 安装 Caddy
    log_info "通过 Homebrew 安装 Caddy..."
    brew install caddy 2>/dev/null || {
        log_error "Caddy 安装失败，请手动安装: brew install caddy"
        return 1
    }
    log_info "Caddy 已安装: $(caddy version 2>/dev/null || echo '已存在')"

    # 配置 Caddyfile
    printf '\n  请输入你的域名 (默认 %s): ' "$DOMAIN"
    read DDNS_DOMAIN || true
    DDNS_DOMAIN="${DDNS_DOMAIN:-$DOMAIN}"

    local caddyfile="/usr/local/etc/caddy/Caddyfile"
    $SUDO mkdir -p "$(dirname "$caddyfile")"
    $SUDO tee "$caddyfile" >/dev/null <<EOF
# eating-medication Caddy 反向代理配置
# 自动申请 Let's Encrypt 证书，HTTPS 由 Caddy 边缘终止

${DDNS_DOMAIN} {
    handle_path ${SERVER_PREFIX}/* {
        reverse_proxy localhost:${SERVER_PORT}
    }
    handle_path ${FAMILY_PREFIX}/* {
        reverse_proxy localhost:${FAMILY_PORT}
    }
    handle {
        reverse_proxy localhost:${SERVER_PORT}
    }
}
EOF
    log_info "Caddyfile 已写入 ${caddyfile}"

    # 创建 Caddy launchd 服务
    local caddy_plist="/Library/LaunchDaemons/com.caddy.server.plist"
    local caddy_bin
    caddy_bin=$(which caddy 2>/dev/null || echo "/opt/homebrew/bin/caddy")

    $SUDO tee "$caddy_plist" >/dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.caddy.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>${caddy_bin}</string>
        <string>run</string>
        <string>--config</string>
        <string>${caddyfile}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/var/log/caddy.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/caddy.err.log</string>
</dict>
</plist>
EOF
    $SUDO chmod 644 "$caddy_plist"
    $SUDO launchctl load -w "$caddy_plist" 2>/dev/null || true
    log_info "Caddy 服务已启动（launchd 守护）"

    # DDNS 配置
    printf '\n  DDNS 更新方式:\n'
    printf '  1) Cloudflare API（需 API Token + Zone ID）\n'
    printf '  2) 自定义命令（支持 $ip 占位符）\n'
    printf '\n'
    printf '  请选择 [1/2] (默认 1): '
    read DDNS_MODE || true
    DDNS_MODE="${DDNS_MODE:-1}"

    local ddns_script="/usr/local/bin/em-ddns-update.sh"

    case "$DDNS_MODE" in
        1)
            printf '  请输入 Cloudflare API Token: '
            read CF_API_TOKEN || true
            printf '  请输入 Zone ID: '
            read CF_ZONE_ID || true
            printf '  请输入 DNS 记录名 (如 eating.example.com): '
            read CF_DNS_NAME || true

            $SUDO tee "$ddns_script" >/dev/null <<DDNSEOF
#!/usr/bin/env zsh
# DDNS 更新脚本 - Cloudflare API 方式

CF_API_TOKEN="${CF_API_TOKEN}"
CF_ZONE_ID="${CF_ZONE_ID}"
CF_DNS_NAME="${CF_DNS_NAME}"

CURRENT_IP=\$(curl -fsSL --connect-timeout 10 https://ifconfig.me 2>/dev/null || \\
              curl -fsSL --connect-timeout 10 https://api.ipify.org 2>/dev/null)

if [ -z "\$CURRENT_IP" ]; then
    echo "[DDNS] 无法获取公网 IP" >&2
    exit 1
fi

CACHE_FILE="/var/lib/em-ddns/last_ip"
mkdir -p /var/lib/em-ddns 2>/dev/null
LAST_IP=""
[ -f "\$CACHE_FILE" ] && LAST_IP=\$(cat "\$CACHE_FILE" 2>/dev/null)

if [ "\$CURRENT_IP" = "\$LAST_IP" ]; then
    exit 0
fi

echo "[DDNS] 公网 IP 变化: \$LAST_IP -> \$CURRENT_IP"

RECORD_ID=\$(curl -fsSL -X GET \\
    "https://api.cloudflare.com/client/v4/zones/\$CF_ZONE_ID/dns_records?name=\$CF_DNS_NAME&type=A" \\
    -H "Authorization: Bearer \$CF_API_TOKEN" \\
    -H "Content-Type: application/json" 2>/dev/null | \\
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result'][0]['id'] if d.get('result') else '')" 2>/dev/null)

if [ -z "\$RECORD_ID" ]; then
    curl -fsSL -X POST \\
        "https://api.cloudflare.com/client/v4/zones/\$CF_ZONE_ID/dns_records" \\
        -H "Authorization: Bearer \$CF_API_TOKEN" \\
        -H "Content-Type: application/json" \\
        --data "{\"type\":\"A\",\"name\":\"\$CF_DNS_NAME\",\"content\":\"\$CURRENT_IP\",\"ttl\":60,\"proxied\":false}" \\
        >/dev/null 2>&1 && echo "[DDNS] 已创建 DNS 记录" || echo "[DDNS] 创建失败" >&2
else
    curl -fsSL -X PUT \\
        "https://api.cloudflare.com/client/v4/zones/\$CF_ZONE_ID/dns_records/\$RECORD_ID" \\
        -H "Authorization: Bearer \$CF_API_TOKEN" \\
        -H "Content-Type: application/json" \\
        --data "{\"type\":\"A\",\"name\":\"\$CF_DNS_NAME\",\"content\":\"\$CURRENT_IP\",\"ttl\":60,\"proxied\":false}" \\
        >/dev/null 2>&1 && echo "[DDNS] 已更新 DNS 记录" || echo "[DDNS] 更新失败" >&2
fi

echo "\$CURRENT_IP" > "\$CACHE_FILE"
DDNSEOF
            ;;
        2)
            printf '  请输入自定义命令（用 $ip 表示公网IP占位符）:\n'
            printf '  > '
            read CUSTOM_CMD || true

            $SUDO tee "$ddns_script" >/dev/null <<DDNSEOF
#!/usr/bin/env zsh
# DDNS 更新脚本 - 自定义命令方式

CUSTOM_CMD='${CUSTOM_CMD}'

CURRENT_IP=\$(curl -fsSL --connect-timeout 10 https://ifconfig.me 2>/dev/null || \\
              curl -fsSL --connect-timeout 10 https://api.ipify.org 2>/dev/null)

if [ -z "\$CURRENT_IP" ]; then
    echo "[DDNS] 无法获取公网 IP" >&2
    exit 1
fi

echo "[DDNS] 当前公网 IP: \$CURRENT_IP"
eval "\${CUSTOM_CMD//\\\$ip/\$CURRENT_IP}"
DDNSEOF
            ;;
    esac

    $SUDO chmod +x "$ddns_script"

    # 创建 launchd 定时任务（每 5 分钟执行）
    local ddns_plist="/Library/LaunchDaemons/com.eatingmedication.ddns.plist"
    $SUDO tee "$ddns_plist" >/dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.eatingmedication.ddns</string>
    <key>ProgramArguments</key>
    <array>
        <string>${ddns_script}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>StandardOutPath</key>
    <string>/var/log/em-ddns.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/em-ddns.err.log</string>
</dict>
</plist>
EOF
    $SUDO chmod 644 "$ddns_plist"
    $SUDO launchctl load -w "$ddns_plist" 2>/dev/null || true
    log_info "DDNS 定时任务已创建（每 5 分钟执行，launchd 守护）"

    DOMAIN="$DDNS_DOMAIN"
}

# ============================================================
# git clone（GitHub → Gitee 回退）
# ============================================================
clone_repo() {
    log_step "[4/9] 克隆仓库"

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
            log_warn "GitHub 克隆失败，尝试 Gitee 镜像..."
            log_info "尝试从 Gitee 克隆: ${REPO_GITEE}"
            if $SUDO git clone --depth 1 "$REPO_GITEE" "$DEPLOY_DIR" 2>/dev/null; then
                log_info "Gitee 克隆成功"
            else
                log_error "GitHub 和 Gitee 均克隆失败"
                exit 1
            fi
        fi
    fi

    $SUDO chown -R "$DEPLOY_USER" "$DEPLOY_DIR"
}

# ============================================================
# 创建 venv + Python 依赖
# ============================================================
setup_python_env() {
    log_step "[5/9] 创建虚拟环境并安装 Python 依赖"

    PIP_MIRROR="${PIP_MIRROR:-}"
    PIP_EXTRA=""
    [ -n "$PIP_MIRROR" ] && PIP_EXTRA="-i $PIP_MIRROR"
    PIP_FALLBACK="-i https://pypi.org/simple"

    VENV="$DEPLOY_DIR/venv"
    if [ ! -x "$VENV/bin/python" ]; then
        log_info "创建虚拟环境 ${VENV} ..."
        python3 -m venv "$VENV"
    fi

    log_info "升级 pip ..."
    "$VENV/bin/python" -m pip install --upgrade pip $PIP_EXTRA 2>/dev/null || \
        "$VENV/bin/python" -m pip install --upgrade pip $PIP_FALLBACK 2>/dev/null || \
        "$VENV/bin/python" -m pip install --upgrade pip

    log_info "安装 server 依赖 ..."
    "$VENV/bin/python" -m pip install -r "$DEPLOY_DIR/server/requirements.txt" $PIP_EXTRA 2>/dev/null || \
        "$VENV/bin/python" -m pip install -r "$DEPLOY_DIR/server/requirements.txt" $PIP_FALLBACK

    log_info "安装 family_monitor 依赖 ..."
    "$VENV/bin/python" -m pip install -r "$DEPLOY_DIR/family_monitor/requirements.txt" $PIP_EXTRA 2>/dev/null || \
        "$VENV/bin/python" -m pip install -r "$DEPLOY_DIR/family_monitor/requirements.txt" $PIP_FALLBACK
}

# ============================================================
# 生成生产环境 .env
# ============================================================
gen_key() { python3 -c "import secrets; print(secrets.token_urlsafe(32))"; }

generate_env_files() {
    log_step "[6/9] 生成生产环境 .env（server / family_monitor）"

    local server_env="$DEPLOY_DIR/server/.env"
    local family_env="$DEPLOY_DIR/family_monitor/.env"

    if [ -f "$server_env" ]; then
        log_info "$server_env 已存在，保留原配置"
    else
        local sk; sk="$(gen_key)"
        $SUDO tee "$server_env" >/dev/null <<EOF
# 生产环境配置（由 deploy/setup-mac.sh 自动生成，请按需修改后重启服务）
APP_NAME=老年人用药管理系统
DEBUG=false
API_V1_PREFIX=/api/v1
PATH_PREFIX=$SERVER_PREFIX
SERVER_HOST=0.0.0.0
SERVER_PORT=$SERVER_PORT
DATABASE_URL=sqlite:///./data/elderly_care.db
SECRET_KEY=$sk
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
ALLOWED_ORIGINS=https://$DOMAIN$FAMILY_PREFIX
GITHUB_OAUTH_CALLBACK_URL=https://$DOMAIN$SERVER_PREFIX/api/v1/auth/oauth/github/callback
GITEE_OAUTH_CALLBACK_URL=https://$DOMAIN$SERVER_PREFIX/api/v1/auth/oauth/gitee/callback
FAMILY_WEB_URL=https://$DOMAIN$FAMILY_PREFIX
# 可选服务留空则自动降级
EOF
        $SUDO chmod 600 "$server_env"
        log_info "已生成 $server_env"
    fi

    if [ -f "$family_env" ]; then
        log_info "$family_env 已存在，保留原配置"
    else
        local sk2; sk2="$(gen_key)"
        $SUDO tee "$family_env" >/dev/null <<EOF
# 生产环境配置（由 deploy/setup-mac.sh 自动生成，请按需修改后重启服务）
SERVER_HOST=0.0.0.0
SERVER_PORT=$FAMILY_PORT
ELDERLY_SERVER_URL=https://$DOMAIN$SERVER_PREFIX
PATH_PREFIX=$FAMILY_PREFIX
APP_NAME=子女守护中心
DEBUG=false
COOKIE_SECURE=true
PRODUCTION=true
SECRET_KEY=$sk2
DEVICE_SECRET=
TURNSTILE_SITE_KEY=
ALLOWED_ORIGINS=https://$DOMAIN$FAMILY_PREFIX
DISPLAY_THEME=light
DISPLAY_COLOR=purple
DISPLAY_LANGUAGE=zh-CN
DISPLAY_ANIMATIONS=True
DISPLAY_COMPACT=False
EOF
        $SUDO chmod 600 "$family_env"
        log_info "已生成 $family_env"
    fi
}

# ============================================================
# 创建运行时目录与权限
# ============================================================
setup_runtime_dirs() {
    log_step "[7/9] 创建运行时目录并修正权限"

    mkdir -p \
        "$DEPLOY_DIR/server/data" "$DEPLOY_DIR/server/logs" \
        "$DEPLOY_DIR/family_monitor/data" "$DEPLOY_DIR/family_monitor/logs"

    chown -R "$DEPLOY_USER" "$DEPLOY_DIR"
}

# ============================================================
# 创建 launchd 服务并启动
# ============================================================
setup_launchd_services() {
    log_step "[8/9] 安装 launchd 服务并启动"

    local daemon_dir="/Library/LaunchDaemons"

    # server launchd plist
    $SUDO tee "$daemon_dir/com.eatingmedication.server.plist" >/dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.eatingmedication.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV}/bin/python</string>
        <string>main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${DEPLOY_DIR}/server</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${DEPLOY_DIR}/server/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>${DEPLOY_DIR}/server/logs/launchd.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
EOF

    # family launchd plist
    $SUDO tee "$daemon_dir/com.eatingmedication.family.plist" >/dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.eatingmedication.family</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV}/bin/python</string>
        <string>main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${DEPLOY_DIR}/family_monitor</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${DEPLOY_DIR}/family_monitor/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>${DEPLOY_DIR}/family_monitor/logs/launchd.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
EOF

    # 卸载旧的（如果存在）再加载
    $SUDO launchctl unload "$daemon_dir/com.eatingmedication.server.plist" 2>/dev/null || true
    $SUDO launchctl unload "$daemon_dir/com.eatingmedication.family.plist" 2>/dev/null || true
    $SUDO launchctl load -w "$daemon_dir/com.eatingmedication.server.plist" 2>/dev/null || true
    $SUDO launchctl load -w "$daemon_dir/com.eatingmedication.family.plist" 2>/dev/null || true

    log_info "launchd 服务已启动"
    log_info "查看日志: tail -f ${DEPLOY_DIR}/server/logs/launchd.log"
    log_info "查看日志: tail -f ${DEPLOY_DIR}/family_monitor/logs/launchd.log"
}

# ============================================================
# 提示编辑 .env 并等待确认
# ============================================================
prompt_edit_env() {
    log_step "[9/9] 提示编辑配置文件"

    sleep 2
    printf '\n'
    printf '============================================================\n'
    printf '  部署即将完成！请编辑以下配置文件后按 Enter 继续：\n'
    printf '============================================================\n'
    printf '\n'
    printf '  1) 服务端配置:\n'
    printf '     sudo nano %s/server/.env\n' "$DEPLOY_DIR"
    printf '     关键项: SECRET_KEY(已自动生成)、TURNSTILE_SECRET_KEY、\n'
    printf '             ZHIPUAI_API_KEY、GITHUB/GITEE OAuth 凭据\n'
    printf '\n'
    printf '  2) 子女端配置:\n'
    printf '     sudo nano %s/family_monitor/.env\n' "$DEPLOY_DIR"
    printf '     关键项: SECRET_KEY(已自动生成)、TURNSTILE_SITE_KEY\n'
    printf '\n'

    # 非交互模式（stdin 非 tty）自动跳过等待
    if [ -t 0 ]; then
        printf '  编辑完成后按 Enter 重启服务...\n'
        printf '  （或按 Ctrl+C 跳过，稍后手动重启）\n'
        read || true
    else
        log_info "非交互模式，跳过等待用户编辑（请稍后手动编辑 .env 并重启服务）"
    fi

    # 重启服务
    log_info "重启服务以加载新配置..."
    $SUDO launchctl unload "/Library/LaunchDaemons/com.eatingmedication.server.plist" 2>/dev/null || true
    $SUDO launchctl unload "/Library/LaunchDaemons/com.eatingmedication.family.plist" 2>/dev/null || true
    $SUDO launchctl load -w "/Library/LaunchDaemons/com.eatingmedication.server.plist" 2>/dev/null || true
    $SUDO launchctl load -w "/Library/LaunchDaemons/com.eatingmedication.family.plist" 2>/dev/null || true
}

# ============================================================
# 卸载：停止并删除 launchd 服务、删除部署目录
# 保留：系统包（git/python3/curl 等）、cloudflared、Caddy、Homebrew
# ============================================================
uninstall() {
    printf '\n'
    printf '============================================================\n'
    printf '  eating-medication 卸载\n'
    printf '  部署目录: %s\n' "$DEPLOY_DIR"
    printf '  运行用户: %s\n' "$DEPLOY_USER"
    printf '============================================================\n'

    # 1. 停止并卸载 launchd 服务
    log_step "[1/5] 停止并卸载 launchd 服务"
    $SUDO launchctl unload -w "/Library/LaunchDaemons/com.eatingmedication.server.plist" 2>/dev/null || true
    $SUDO launchctl unload -w "/Library/LaunchDaemons/com.eatingmedication.family.plist" 2>/dev/null || true
    log_info "launchd 服务已停止"

    # 2. 删除 launchd plist 文件
    log_step "[2/5] 删除 launchd plist 文件"
    $SUDO rm -f /Library/LaunchDaemons/com.eatingmedication.server.plist \
                 /Library/LaunchDaemons/com.eatingmedication.family.plist 2>/dev/null || true
    log_info "plist 文件已删除"

    # 3. 删除部署目录
    log_step "[3/5] 删除部署目录"
    if [ -d "$DEPLOY_DIR" ]; then
        $SUDO rm -rf "$DEPLOY_DIR"
        log_info "已删除部署目录: ${DEPLOY_DIR}"
    else
        log_info "部署目录不存在，跳过"
    fi

    # 4. 删除 DDNS 脚本与 Caddyfile
    log_step "[4/5] 删除 DDNS 脚本与 Caddyfile"
    $SUDO rm -f /usr/local/bin/em-ddns-update.sh 2>/dev/null || true
    $SUDO rm -f /var/lib/em-ddns/last_ip 2>/dev/null || true
    $SUDO rmdir /var/lib/em-ddns 2>/dev/null || true
    if [ -f /etc/caddy/Caddyfile ] && grep -q "eating-medication" /etc/caddy/Caddyfile 2>/dev/null; then
        $SUDO rm -f /etc/caddy/Caddyfile
        log_info "已删除 /etc/caddy/Caddyfile（本脚本生成的配置）"
    fi
    log_info "DDNS 脚本与 Caddyfile 清理完成"

    # 5. 删除 DDNS launchd plist（如果存在）
    log_step "[5/5] 删除 DDNS launchd 服务"
    $SUDO launchctl unload -w "/Library/LaunchDaemons/com.eatingmedication.ddns.plist" 2>/dev/null || true
    $SUDO rm -f /Library/LaunchDaemons/com.eatingmedication.ddns.plist 2>/dev/null || true
    log_info "DDNS launchd 服务已清理"

    # 完成提示
    printf '\n'
    printf '============================================================\n'
    printf '  卸载完成！\n'
    printf '============================================================\n'
    printf '\n'
    printf '  已删除:\n'
    printf '    - 部署目录: %s\n' "$DEPLOY_DIR"
    printf '    - launchd 服务（server/family/ddns）\n'
    printf '    - DDNS 脚本与 Caddyfile\n'
    printf '\n'
    printf '  保留（未删除）:\n'
    printf '    - 系统包: git, python3, curl, cloudflared, caddy\n'
    printf '    - cloudflared 凭证: ~/.cloudflared/\n'
    printf '    - Homebrew 及其他系统配置\n'
    printf '%s\n' '------------------------------------------------------------'
}

# ============================================================
# 主流程
# ============================================================
main() {
    printf '\n'
    printf '============================================================\n'
    printf '  eating-medication macOS 一键部署\n'
    printf '  部署目录: %s\n' "$DEPLOY_DIR"
    printf '  运行用户: %s\n' "$DEPLOY_USER"
    printf '  域名:     %s\n' "$DOMAIN"
    printf '============================================================\n'

    detect_system
    install_system_deps
    ask_access_mode

    case "$ACCESS_MODE" in
        1) install_cloudflared ;;
        2) setup_ddns_caddy ;;
        3) log_info "跳过公网访问配置" ;;
    esac

    clone_repo
    setup_python_env
    generate_env_files
    setup_runtime_dirs
    setup_launchd_services
    prompt_edit_env

    sleep 2
    printf '\n'
    printf '============================================================\n'
    printf '  部署完成！\n'
    printf '============================================================\n'
    printf '\n'
    printf '  后续步骤:\n'
    printf '  1) 查看日志:\n'
    printf '     tail -f %s/server/logs/launchd.log\n' "$DEPLOY_DIR"
    printf '     tail -f %s/family_monitor/logs/launchd.log\n' "$DEPLOY_DIR"
    printf '  2) 更新代码: sudo zsh %s/deploy/setup-mac.sh\n' "$DEPLOY_DIR"
    case "$ACCESS_MODE" in
        1)
            printf '  3) Cloudflare 隧道路由:\n'
            printf '     %s -> http://localhost:%s\n' "$SERVER_PREFIX" "$SERVER_PORT"
            printf '     %s -> http://localhost:%s\n' "$FAMILY_PREFIX" "$FAMILY_PORT"
            ;;
        2)
            printf '  3) Caddy 反代已配置，访问: https://%s\n' "$DOMAIN"
            ;;
        3)
            printf '  3) 内网访问:\n'
            printf '     http://localhost:%s%s\n' "$SERVER_PORT" "$SERVER_PREFIX"
            printf '     http://localhost:%s%s\n' "$FAMILY_PORT" "$FAMILY_PREFIX"
            ;;
    esac
    printf '%s\n' '------------------------------------------------------------'
}

# 入口：检测 --uninstall 参数
if [ "${1:-}" = "--uninstall" ] || [ "${1:-}" = "-u" ]; then
    uninstall
    exit 0
fi

main "$@"
