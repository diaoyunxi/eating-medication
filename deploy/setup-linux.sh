#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# eating-medication Linux 一键部署脚本（bash）
#
# 功能：检测系统 → 包管理器更新 → 询问访问模式（cloudflared/DDNS/仅内网）
#       → git clone（GitHub→Gitee 回退）→ 装依赖 → 生成 .env → systemd 服务
#
# 适用：Debian/Ubuntu（apt）、Fedora/RHEL（dnf/yum）、Arch（pacman）、Alpine（apk）
# 默认部署目录 /opt/eating-medication，运行用户 deploy。
#
# 用法：
#   sudo bash deploy/setup-linux.sh                 # 默认域名 my-website.ccwu.cc
#   sudo DOMAIN=你的域名 bash deploy/setup-linux.sh  # 自定义域名
#
# 幂等：可重复执行（更新代码 + 重装依赖 + 重启服务）。
#       .env 仅在不存在时生成，已存在则保留你的配置。

set -euo pipefail

# ===== 可配置变量 =====
DEPLOY_DIR="${DEPLOY_DIR:-/opt/eating-medication}"
DEPLOY_USER="deploy"
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
    log_step "[1/9] 更新包管理器索引并安装系统依赖"

    case "$PM" in
        apt)
            $SUDO apt-get update -y 2>/dev/null || log_warn "apt-get update 失败（镜像源同步中？），继续安装..."
            $SUDO apt-get install -y git python3 python3-pip python3-venv curl
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
# 询问访问模式
# ============================================================
ask_access_mode() {
    log_step "[2/9] 选择公网访问模式"

    # 非交互模式：通过环境变量 ACCESS_MODE 指定（1=cloudflared 2=DDNS 3=仅内网）
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
    read -r ACCESS_MODE || true
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

    # 检查是否已安装
    if command -v cloudflared >/dev/null 2>&1; then
        log_info "cloudflared 已安装: $(cloudflared --version 2>&1 || echo '已存在')"
    else
        log_info "通过包管理器或 GitHub Release 安装 cloudflared..."

        # 方式1：Cloudflare 官方包仓库（Debian/Ubuntu）
        local cf_installed=false
        if [ "$PM" = "apt" ]; then
            # 添加 Cloudflare GPG key 和仓库
            $SUDO mkdir -p /etc/apt/keyrings 2>/dev/null || true
            if curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | \
               $SUDO gpg --yes --dearmor --output /etc/apt/keyrings/cloudflare-main.gpg 2>/dev/null; then
                echo "deb [signed-by=/etc/apt/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs 2>/dev/null || echo jammy) main" | \
                    $SUDO tee /etc/apt/sources.list.d/cloudflared.list >/dev/null
                $SUDO apt-get update -y 2>/dev/null
                if $SUDO apt-get install -y cloudflared 2>/dev/null; then
                    cf_installed=true
                fi
            fi
        fi

        # 方式2：GitHub Release 下载二进制
        if [ "$cf_installed" = false ]; then
            log_info "从 GitHub Release 下载 cloudflared 二进制..."
            local cf_url=""
            case "$ARCH_NORM" in
                amd64) cf_url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
                arm64) cf_url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64" ;;
                arm)   cf_url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm" ;;
                *)
                    log_error "不支持的架构: ${ARCH_NORM}"
                    log_error "请手动安装 cloudflared: https://github.com/cloudflare/cloudflared/releases"
                    return 1
                    ;;
            esac

            # 下载（GitHub 直连 → 镜像回退）
            local cf_bin="/usr/local/bin/cloudflared"
            local downloaded=false
            for url in "$cf_url" \
                       "https://gh.my-website.ccwu.cc/$cf_url" \
                       "https://gh-proxy.com/$cf_url"; do
                log_info "尝试下载: ${url}"
                if curl -fsSL --connect-timeout 15 --max-time 120 "$url" -o /tmp/cloudflared 2>/dev/null; then
                    downloaded=true
                    break
                fi
            done

            if [ "$downloaded" = false ]; then
                log_error "下载 cloudflared 失败，请手动安装"
                return 1
            fi

            $SUDO mv /tmp/cloudflared "$cf_bin"
            $SUDO chmod +x "$cf_bin"
            log_info "cloudflared 已安装到 ${cf_bin}"
        fi
    fi

    # 选择认证方式（非交互模式：通过 CF_AUTH_MODE / CF_TUNNEL_TOKEN 环境变量指定）
    if [ -n "${CF_TUNNEL_TOKEN:-}" ]; then
        # 直接提供了 Token，跳过交互
        log_info "使用环境变量 CF_TUNNEL_TOKEN（Token 模式）"
        CF_AUTH_MODE="1"
    elif [ -n "${CF_AUTH_MODE:-}" ]; then
        log_info "使用环境变量 CF_AUTH_MODE=${CF_AUTH_MODE}"
    else
        printf '\n'
        printf '  Cloudflare 隧道认证方式:\n'
        printf '  1) Token（推荐）—— 在 Zero Trust 控制台创建隧道后粘贴 token\n'
        printf '  2) Login（交互式）—— 需浏览器授权，适合有图形界面的环境\n'
        printf '\n'
        printf '  请选择 [1/2] (默认 1): '
        read -r CF_AUTH_MODE || true
        CF_AUTH_MODE="${CF_AUTH_MODE:-1}"
    fi

    case "$CF_AUTH_MODE" in
        1)
            # Token 方式
            if [ -z "${CF_TUNNEL_TOKEN:-}" ]; then
                printf '  请粘贴隧道 Token（从 Cloudflare Zero Trust 控制台复制）:\n'
                printf '  > '
                read -r CF_TUNNEL_TOKEN || true
            fi

            if [ -z "$CF_TUNNEL_TOKEN" ]; then
                log_warn "Token 为空，跳过 cloudflared 服务创建"
                log_warn "请稍后手动配置: 创建 /etc/cloudflared/cloudflared.env 并填写 TUNNEL_TOKEN"
                return 0
            fi

            # 创建环境文件
            $SUDO mkdir -p /etc/cloudflared
            echo "TUNNEL_TOKEN=${CF_TUNNEL_TOKEN}" | $SUDO tee /etc/cloudflared/cloudflared.env >/dev/null
            $SUDO chmod 0600 /etc/cloudflared/cloudflared.env

            # 创建 cloudflared 用户（如果不存在）
            if ! id cloudflared >/dev/null 2>&1; then
                $SUDO useradd -r -s /usr/sbin/nologin cloudflared 2>/dev/null || \
                $SUDO useradd -r -s /sbin/nologin cloudflared 2>/dev/null || true
            fi
            $SUDO chown cloudflared:cloudflared /etc/cloudflared/cloudflared.env

            # 安装 systemd 服务
            if [ -f "${DEPLOY_DIR}/deploy/cloudflared.service" ]; then
                $SUDO cp "${DEPLOY_DIR}/deploy/cloudflared.service" /etc/systemd/system/
            else
                # 引导器场景：仓库尚未 clone，直接写服务文件
                $SUDO tee /etc/systemd/system/cloudflared.service >/dev/null <<'EOF'
[Unit]
Description=Cloudflare Tunnel (cloudflared)
After=network-online.target
Wants=network-online.target

[Service]
User=cloudflared
Group=cloudflared
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
TimeoutStartSec=0
Type=notify
EnvironmentFile=/etc/cloudflared/cloudflared.env
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate run
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF
            fi

            $SUDO systemctl daemon-reload 2>/dev/null || true
            $SUDO systemctl enable --now cloudflared 2>/dev/null || \
                log_warn "cloudflared 服务启动失败（systemd 未运行或 Token 无效），请稍后手动启动"
            log_info "Cloudflare 隧道已配置（Token 模式）"
            log_info "请在 Zero Trust 控制台添加路由:"
            log_info "  ${SERVER_PREFIX} -> http://localhost:${SERVER_PORT}"
            log_info "  ${FAMILY_PREFIX} -> http://localhost:${FAMILY_PORT}"
            ;;
        2)
            # Login 方式（交互式）
            log_info "执行 cloudflared tunnel login（需浏览器授权）..."
            log_warn "在无图形界面的服务器上，请通过 SSH 端口转发访问授权链接"
            log_warn "  ssh -L 8081:localhost:8081 user@server"
            # cloudflared 单文件版将凭证写入 ~/.cloudflared，无需 sudo
            cloudflared tunnel login || {
                log_error "cloudflared tunnel login 失败"
                log_error "请稍后手动执行: cloudflared tunnel login"
            }

            # 创建隧道
            printf '  请输入隧道名称 (默认 eating-medication): '
            read -r CF_TUNNEL_NAME || true
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
    log_info "安装 Caddy..."
    if [ "$PM" = "apt" ]; then
        $SUDO apt-get install -y debian-keyring debian-archive-keyring apt-transport-https 2>/dev/null || true
        curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | \
            $SUDO gpg --yes --dearmor --output /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null || true
        echo "deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb.debian.net any main" | \
            $SUDO tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
        $SUDO apt-get update -y 2>/dev/null
        $SUDO apt-get install -y caddy 2>/dev/null || {
            log_error "Caddy 安装失败，请手动安装: https://caddyserver.com/docs/install"
            return 1
        }
    else
        # 非 Debian 系统尝试直接下载二进制
        local caddy_url=""
        case "$ARCH_NORM" in
            amd64) caddy_url="https://github.com/caddyserver/caddy/releases/latest/download/caddy_${ARCH_NORM}_linux" ;;
            arm64) caddy_url="https://github.com/caddyserver/caddy/releases/latest/download/caddy_${ARCH_NORM}_linux" ;;
            *)     caddy_url="https://github.com/caddyserver/caddy/releases/latest/download/caddy_${ARCH_NORM}_linux" ;;
        esac
        local downloaded=false
        for url in "$caddy_url" "https://gh.my-website.ccwu.cc/$caddy_url" "https://gh-proxy.com/$caddy_url"; do
            if curl -fsSL "$url" -o /tmp/caddy 2>/dev/null; then
                downloaded=true; break
            fi
        done
        if [ "$downloaded" = true ]; then
            $SUDO mv /tmp/caddy /usr/local/bin/caddy
            $SUDO chmod +x /usr/local/bin/caddy
        else
            log_error "Caddy 下载失败，请手动安装"
            return 1
        fi
    fi
    log_info "Caddy 已安装: $(caddy version 2>/dev/null || echo '已存在')"

    # 配置 Caddyfile（反代 + 自动 HTTPS）
    if [ -n "${DDNS_DOMAIN:-}" ]; then
        log_info "使用环境变量 DDNS_DOMAIN=${DDNS_DOMAIN}"
    else
        printf '\n  请输入你的域名 (默认 %s): ' "$DOMAIN"
        read -r DDNS_DOMAIN || true
        DDNS_DOMAIN="${DDNS_DOMAIN:-$DOMAIN}"
    fi

    $SUDO tee /etc/caddy/Caddyfile >/dev/null <<EOF
# eating-medication Caddy 反向代理配置
# 自动申请 Let's Encrypt 证书，HTTPS 由 Caddy 边缘终止

${DDNS_DOMAIN} {
    # 服务端
    handle_path ${SERVER_PREFIX}/* {
        reverse_proxy localhost:${SERVER_PORT}
    }
    # 家属看护端
    handle_path ${FAMILY_PREFIX}/* {
        reverse_proxy localhost:${FAMILY_PORT}
    }
    # 根路径
    handle {
        reverse_proxy localhost:${SERVER_PORT}
    }
}
EOF
    log_info "Caddyfile 已写入 /etc/caddy/Caddyfile"

    # 启动/重启 Caddy
    if systemctl list-unit-files 2>/dev/null | grep -q caddy; then
        $SUDO systemctl enable --now caddy 2>/dev/null || true
        $SUDO systemctl reload caddy 2>/dev/null || $SUDO systemctl restart caddy 2>/dev/null || true
        log_info "Caddy 服务已启动"
    else
        log_warn "未检测到 Caddy systemd 服务，请手动启动"
    fi

    # DDNS 配置
    printf '\n  DDNS 更新方式:\n'
    printf '  1) Cloudflare API（需 API Token + Zone ID）\n'
    printf '  2) 自定义命令（支持 $ip 占位符）\n'
    printf '\n'
    printf '  请选择 [1/2] (默认 1): '
    read -r DDNS_MODE || true
    DDNS_MODE="${DDNS_MODE:-1}"

    # DDNS 脚本路径
    local ddns_script="/usr/local/bin/em-ddns-update.sh"
    local ddns_service="/etc/systemd/system/em-ddns.timer"
    local ddns_timer_unit="em-ddns.timer"

    case "$DDNS_MODE" in
        1)
            # Cloudflare API 方式
            printf '  请输入 Cloudflare API Token: '
            read -r CF_API_TOKEN || true
            printf '  请输入 Zone ID: '
            read -r CF_ZONE_ID || true
            printf '  请输入 DNS 记录名 (如 eating.example.com): '
            read -r CF_DNS_NAME || true

            $SUDO tee "$ddns_script" >/dev/null <<DDNSEOF
#!/usr/bin/env bash
# DDNS 更新脚本 - Cloudflare API 方式
# 每 5 分钟检测公网 IP 并更新 Cloudflare DNS 记录

CF_API_TOKEN="${CF_API_TOKEN}"
CF_ZONE_ID="${CF_ZONE_ID}"
CF_DNS_NAME="${CF_DNS_NAME}"

# 获取当前公网 IP
CURRENT_IP=\$(curl -fsSL --connect-timeout 10 https://ifconfig.me 2>/dev/null || \\
              curl -fsSL --connect-timeout 10 https://api.ipify.org 2>/dev/null || \\
              curl -fsSL --connect-timeout 10 https://icanhazip.com 2>/dev/null)

if [ -z "\$CURRENT_IP" ]; then
    echo "[DDNS] 无法获取公网 IP" >&2
    exit 1
fi

# 读取上次记录的 IP
CACHE_FILE="/var/lib/em-ddns/last_ip"
mkdir -p /var/lib/em-ddns 2>/dev/null
LAST_IP=""
[ -f "\$CACHE_FILE" ] && LAST_IP=\$(cat "\$CACHE_FILE" 2>/dev/null)

# IP 未变化则跳过
if [ "\$CURRENT_IP" = "\$LAST_IP" ]; then
    exit 0
fi

echo "[DDNS] 公网 IP 变化: \$LAST_IP -> \$CURRENT_IP"

# 查询现有 DNS 记录
RECORD_ID=\$(curl -fsSL -X GET \\
    "https://api.cloudflare.com/client/v4/zones/\$CF_ZONE_ID/dns_records?name=\$CF_DNS_NAME&type=A" \\
    -H "Authorization: Bearer \$CF_API_TOKEN" \\
    -H "Content-Type: application/json" 2>/dev/null | \\
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result'][0]['id'] if d.get('result') else '')" 2>/dev/null)

if [ -z "\$RECORD_ID" ]; then
    # 创建新记录
    curl -fsSL -X POST \\
        "https://api.cloudflare.com/client/v4/zones/\$CF_ZONE_ID/dns_records" \\
        -H "Authorization: Bearer \$CF_API_TOKEN" \\
        -H "Content-Type: application/json" \\
        --data "{\"type\":\"A\",\"name\":\"\$CF_DNS_NAME\",\"content\":\"\$CURRENT_IP\",\"ttl\":60,\"proxied\":false}" \\
        >/dev/null 2>&1 && echo "[DDNS] 已创建 DNS 记录" || echo "[DDNS] 创建失败" >&2
else
    # 更新现有记录
    curl -fsSL -X PUT \\
        "https://api.cloudflare.com/client/v4/zones/\$CF_ZONE_ID/dns_records/\$RECORD_ID" \\
        -H "Authorization: Bearer \$CF_API_TOKEN" \\
        -H "Content-Type: application/json" \\
        --data "{\"type\":\"A\",\"name\":\"\$CF_DNS_NAME\",\"content\":\"\$CURRENT_IP\",\"ttl\":60,\"proxied\":false}" \\
        >/dev/null 2>&1 && echo "[DDNS] 已更新 DNS 记录" || echo "[DDNS] 更新失败" >&2
fi

# 缓存当前 IP
echo "\$CURRENT_IP" > "\$CACHE_FILE"
DDNSEOF
            ;;
        2)
            # 自定义命令方式
            printf '  请输入自定义命令（用 $ip 表示公网IP占位符）:\n'
            printf '  > '
            read -r CUSTOM_CMD || true

            $SUDO tee "$ddns_script" >/dev/null <<DDNSEOF
#!/usr/bin/env bash
# DDNS 更新脚本 - 自定义命令方式
# 每 5 分钟检测公网 IP 并执行用户自定义命令

CUSTOM_CMD='${CUSTOM_CMD}'

# 获取当前公网 IP
CURRENT_IP=\$(curl -fsSL --connect-timeout 10 https://ifconfig.me 2>/dev/null || \\
              curl -fsSL --connect-timeout 10 https://api.ipify.org 2>/dev/null || \\
              curl -fsSL --connect-timeout 10 https://icanhazip.com 2>/dev/null)

if [ -z "\$CURRENT_IP" ]; then
    echo "[DDNS] 无法获取公网 IP" >&2
    exit 1
fi

echo "[DDNS] 当前公网 IP: \$CURRENT_IP"

# 执行自定义命令（替换 $ip 占位符）
eval "\${CUSTOM_CMD//\\\$ip/\$CURRENT_IP}"
DDNSEOF
            ;;
    esac

    $SUDO chmod +x "$ddns_script"

    # 创建 systemd timer（每 5 分钟执行）
    $SUDO tee /etc/systemd/system/em-ddns.service >/dev/null <<'EOF'
[Unit]
Description=eating-medication DDNS Update

[Service]
Type=oneshot
ExecStart=/usr/local/bin/em-ddns-update.sh
EOF

    $SUDO tee "$ddns_service" >/dev/null <<'EOF'
[Unit]
Description=eating-medication DDNS Timer (every 5 min)

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
Unit=em-ddns.service

[Install]
WantedBy=timers.target
EOF

    $SUDO systemctl daemon-reload 2>/dev/null || true
    $SUDO systemctl enable --now em-ddns.timer 2>/dev/null || true
    # 立即执行一次
    $SUDO systemctl start em-ddns.service 2>/dev/null || true
    log_info "DDNS 定时任务已创建（每 5 分钟执行）"

    # 更新 DOMAIN 变量供后续 .env 生成使用
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
# 创建运行用户 + venv + Python 依赖
# ============================================================
setup_python_env() {
    log_step "[5/9] 创建用户、虚拟环境并安装 Python 依赖"

    # 创建运行用户
    if id "$DEPLOY_USER" >/dev/null 2>&1; then
        log_info "用户 ${DEPLOY_USER} 已存在，跳过"
    else
        log_info "创建系统用户 ${DEPLOY_USER} ..."
        if command -v useradd >/dev/null 2>&1; then
            $SUDO useradd -r -s /usr/sbin/nologin "$DEPLOY_USER" 2>/dev/null || \
                $SUDO useradd -r -s /sbin/nologin "$DEPLOY_USER"
        else
            $SUDO adduser -S -s /sbin/nologin "$DEPLOY_USER" 2>/dev/null || \
                $SUDO adduser -S "$DEPLOY_USER"
        fi
    fi

    # 创建虚拟环境
    PIP_MIRROR="${PIP_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
    PIP_EXTRA=""
    [ -n "$PIP_MIRROR" ] && PIP_EXTRA="-i $PIP_MIRROR"

    VENV="$DEPLOY_DIR/venv"
    if [ ! -x "$VENV/bin/python" ]; then
        log_info "创建虚拟环境 ${VENV} ..."
        $SUDO python3 -m venv "$VENV"
    fi

    log_info "升级 pip ..."
    $SUDO "$VENV/bin/python" -m pip install --upgrade pip $PIP_EXTRA 2>/dev/null || \
        $SUDO "$VENV/bin/python" -m pip install --upgrade pip

    log_info "安装 server 依赖 ..."
    $SUDO "$VENV/bin/python" -m pip install -r "$DEPLOY_DIR/server/requirements.txt" $PIP_EXTRA 2>/dev/null || \
        $SUDO "$VENV/bin/python" -m pip install -r "$DEPLOY_DIR/server/requirements.txt"

    log_info "安装 family_monitor 依赖 ..."
    $SUDO "$VENV/bin/python" -m pip install -r "$DEPLOY_DIR/family_monitor/requirements.txt" $PIP_EXTRA 2>/dev/null || \
        $SUDO "$VENV/bin/python" -m pip install -r "$DEPLOY_DIR/family_monitor/requirements.txt"

    $SUDO chown -R "$DEPLOY_USER:$DEPLOY_USER" "$VENV"
}

# ============================================================
# 生成生产环境 .env
# ============================================================
gen_key() { python3 -c "import secrets; print(secrets.token_urlsafe(32))"; }

generate_env_files() {
    log_step "[6/9] 生成生产环境 .env（server / family_monitor）"

    local server_env="$DEPLOY_DIR/server/.env"
    local family_env="$DEPLOY_DIR/family_monitor/.env"

    # server/.env
    if [ -f "$server_env" ]; then
        log_info "$server_env 已存在，保留原配置"
    else
        local sk; sk="$(gen_key)"
        $SUDO tee "$server_env" >/dev/null <<EOF
# 生产环境配置（由 deploy/setup-linux.sh 自动生成，请按需修改后重启服务）
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
# 以下为可选服务，留空则自动降级（功能关闭）：
#   MAIL_*        邮件验证码登录/找回密码
#   OCR_*         图片 OCR 识别
#   TURNSTILE_SECRET_KEY  Cloudflare 人机验证
#   GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET  GitHub 登录
#   GITEE_CLIENT_ID / GITEE_CLIENT_SECRET    Gitee 登录
#   ZHIPUAI_API_KEY / ZHIPUAI_MODEL          服务端 AI 全局兜底
EOF
        $SUDO chmod 600 "$server_env"
        log_info "已生成 $server_env"
    fi

    # family_monitor/.env
    if [ -f "$family_env" ]; then
        log_info "$family_env 已存在，保留原配置"
    else
        local sk2; sk2="$(gen_key)"
        $SUDO tee "$family_env" >/dev/null <<EOF
# 生产环境配置（由 deploy/setup-linux.sh 自动生成，请按需修改后重启服务）
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

    $SUDO mkdir -p \
        "$DEPLOY_DIR/server/data" "$DEPLOY_DIR/server/logs" \
        "$DEPLOY_DIR/family_monitor/data" "$DEPLOY_DIR/family_monitor/logs"

    $SUDO chown -R "$DEPLOY_USER:$DEPLOY_USER" \
        "$DEPLOY_DIR/server/data" "$DEPLOY_DIR/server/logs" \
        "$DEPLOY_DIR/family_monitor/data" "$DEPLOY_DIR/family_monitor/logs"

    [ -f "$DEPLOY_DIR/server/.env" ] && \
        $SUDO chown "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_DIR/server/.env" || true
    [ -f "$DEPLOY_DIR/family_monitor/.env" ] && \
        $SUDO chown "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_DIR/family_monitor/.env" || true
}

# ============================================================
# 安装 systemd 服务并启动
# ============================================================
setup_systemd_services() {
    log_step "[8/9] 安装 systemd 服务并启动"

    # 更新 service 文件中的路径（确保与 DEPLOY_DIR 一致）
    local svc_dir="$DEPLOY_DIR/deploy"

    # server service
    $SUDO tee /etc/systemd/system/eating-medication-server.service >/dev/null <<EOF
[Unit]
Description=Eating Medication Server (FastAPI)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$DEPLOY_USER
Group=$DEPLOY_USER
WorkingDirectory=$DEPLOY_DIR/server
ExecStart=$VENV/bin/python main.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$DEPLOY_DIR
EnvironmentFile=-$DEPLOY_DIR/server/.env

[Install]
WantedBy=multi-user.target
EOF

    # family service
    $SUDO tee /etc/systemd/system/eating-medication-family.service >/dev/null <<EOF
[Unit]
Description=Eating Medication Family Monitor (FastAPI Web)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$DEPLOY_USER
Group=$DEPLOY_USER
WorkingDirectory=$DEPLOY_DIR/family_monitor
ExecStart=$VENV/bin/python main.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$DEPLOY_DIR
EnvironmentFile=-$DEPLOY_DIR/family_monitor/.env

[Install]
WantedBy=multi-user.target
EOF

    $SUDO systemctl daemon-reload 2>/dev/null || log_warn "systemctl daemon-reload 失败（非 systemd 环境？）"
    $SUDO systemctl enable --now eating-medication-server eating-medication-family 2>/dev/null || {
        log_warn "systemctl enable 失败，systemd 可能未运行"
        log_warn "服务文件已写入 /etc/systemd/system/，systemd 可用后请手动执行:"
        log_warn "  systemctl daemon-reload && systemctl enable --now eating-medication-server eating-medication-family"
    }

    # 配置免密 sudoers（供 updater.py 自动更新后重启使用）
    log_info "配置 ${DEPLOY_USER} 免密重启服务（自动更新用）..."
    local sudoers_file="/etc/sudoers.d/eating-medication"
    $SUDO tee "$sudoers_file" >/dev/null <<EOF
# eating-medication: 允许 $DEPLOY_USER 免密重启/查看应用服务
$DEPLOY_USER ALL=(root) NOPASSWD: \\
    /usr/bin/systemctl restart eating-medication-server eating-medication-family, \\
    /usr/bin/systemctl status eating-medication-server eating-medication-family, \\
    /bin/systemctl restart eating-medication-server eating-medication-family, \\
    /bin/systemctl status eating-medication-server eating-medication-family
EOF
    $SUDO chmod 440 "$sudoers_file" 2>/dev/null || true
    $SUDO visudo -c -f "$sudoers_file" 2>/dev/null || log_warn "sudoers 语法校验失败，请检查"
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
    printf '     关键项: SECRET_KEY(已自动生成)、TURNSTILE_SITE_KEY、\n'
    printf '             ELDERLY_SERVER_URL(已自动填写)\n'
    printf '\n'

    # 非交互模式（stdin 非 tty）自动跳过等待
    if [ -t 0 ]; then
        printf '  编辑完成后按 Enter 重启服务以加载新配置...\n'
        printf '  （或按 Ctrl+C 跳过，稍后手动重启）\n'
        read -r || true
    else
        log_info "非交互模式，跳过等待用户编辑（请稍后手动编辑 .env 并重启服务）"
    fi

    # 重启服务以加载新配置
    log_info "重启服务以加载新配置..."
    $SUDO systemctl restart eating-medication-server eating-medication-family 2>/dev/null || true
}

# ============================================================
# 卸载：停止并删除服务、删除部署目录、删除用户
# 保留：系统包（git/python3/curl 等）、cloudflared 二进制、Caddy
# ============================================================
uninstall() {
    printf '\n'
    printf '============================================================\n'
    printf '  eating-medication 卸载\n'
    printf '  部署目录: %s\n' "$DEPLOY_DIR"
    printf '  运行用户: %s\n' "$DEPLOY_USER"
    printf '============================================================\n'

    # 1. 停止并禁用 systemd 服务
    log_step "[1/6] 停止并禁用 systemd 服务"
    $SUDO systemctl stop eating-medication-server eating-medication-family 2>/dev/null || true
    $SUDO systemctl disable eating-medication-server eating-medication-family 2>/dev/null || true
    $SUDO systemctl stop cloudflared 2>/dev/null || true
    $SUDO systemctl disable cloudflared 2>/dev/null || true
    $SUDO systemctl stop em-ddns.timer em-ddns.service 2>/dev/null || true
    $SUDO systemctl disable em-ddns.timer em-ddns.service 2>/dev/null || true
    $SUDO systemctl daemon-reload 2>/dev/null || true
    log_info "服务已停止并禁用"

    # 2. 删除 systemd 服务文件
    log_step "[2/6] 删除 systemd 服务文件"
    $SUDO rm -f /etc/systemd/system/eating-medication-server.service \
                 /etc/systemd/system/eating-medication-family.service \
                 /etc/systemd/system/cloudflared.service \
                 /etc/systemd/system/em-ddns.service \
                 /etc/systemd/system/em-ddns.timer 2>/dev/null || true
    $SUDO systemctl daemon-reload 2>/dev/null || true
    log_info "服务文件已删除"

    # 3. 删除 sudoers 规则
    log_step "[3/6] 删除 sudoers 规则"
    $SUDO rm -f /etc/sudoers.d/eating-medication 2>/dev/null || true
    log_info "sudoers 规则已删除"

    # 4. 删除部署目录
    log_step "[4/6] 删除部署目录"
    if [ -d "$DEPLOY_DIR" ]; then
        $SUDO rm -rf "$DEPLOY_DIR"
        log_info "已删除部署目录: ${DEPLOY_DIR}"
    else
        log_info "部署目录不存在，跳过"
    fi

    # 5. 删除 DDNS 脚本与 Caddyfile（仅删除本脚本生成的文件）
    log_step "[5/6] 删除 DDNS 脚本与 Caddyfile"
    $SUDO rm -f /usr/local/bin/em-ddns-update.sh 2>/dev/null || true
    $SUDO rm -f /var/lib/em-ddns/last_ip 2>/dev/null || true
    $SUDO rmdir /var/lib/em-ddns 2>/dev/null || true
    # Caddyfile：仅当内容包含 eating-medication 标记时删除
    if [ -f /etc/caddy/Caddyfile ] && grep -q "eating-medication" /etc/caddy/Caddyfile 2>/dev/null; then
        $SUDO rm -f /etc/caddy/Caddyfile
        log_info "已删除 /etc/caddy/Caddyfile（本脚本生成的配置）"
    fi
    log_info "DDNS 脚本与 Caddyfile 清理完成"

    # 6. 删除运行用户
    log_step "[6/6] 删除运行用户"
    if id "$DEPLOY_USER" >/dev/null 2>&1; then
        $SUDO userdel -r "$DEPLOY_USER" 2>/dev/null || $SUDO userdel "$DEPLOY_USER" 2>/dev/null || true
        log_info "已删除用户: ${DEPLOY_USER}"
    else
        log_info "用户 ${DEPLOY_USER} 不存在，跳过"
    fi

    # 完成提示
    printf '\n'
    printf '============================================================\n'
    printf '  卸载完成！\n'
    printf '============================================================\n'
    printf '\n'
    printf '  已删除:\n'
    printf '    - 部署目录: %s\n' "$DEPLOY_DIR"
    printf '    - systemd 服务（server/family/cloudflared/ddns）\n'
    printf '    - sudoers 规则\n'
    printf '    - DDNS 脚本与 Caddyfile\n'
    printf '    - 运行用户: %s\n' "$DEPLOY_USER"
    printf '\n'
    printf '  保留（未删除）:\n'
    printf '    - 系统包: git, python3, curl, cloudflared, caddy\n'
    printf '    - cloudflared 凭证: ~/.cloudflared/\n'
    printf '    - cloudflared 配置: /etc/cloudflared/\n'
    printf '\n'
    printf '  如需完全清除 cloudflared:\n'
    printf '    sudo apt remove --purge cloudflared   (或删除 /usr/local/bin/cloudflared)\n'
    printf '    sudo rm -rf /etc/cloudflared ~/.cloudflared\n'
    printf '  如需完全清除 Caddy:\n'
    printf '    sudo apt remove --purge caddy\n'
    printf '%s\n' '------------------------------------------------------------'
}

# ============================================================
# 主流程
# ============================================================
main() {
    printf '\n'
    printf '============================================================\n'
    printf '  eating-medication Linux 一键部署\n'
    printf '  部署目录: %s\n' "$DEPLOY_DIR"
    printf '  运行用户: %s\n' "$DEPLOY_USER"
    printf '  域名:     %s\n' "$DOMAIN"
    printf '============================================================\n'

    # 1. 检测系统
    detect_system

    # 2. 安装系统依赖
    install_system_deps

    # 3. 询问访问模式
    ask_access_mode

    # 4. 按选择配置网络访问
    case "$ACCESS_MODE" in
        1) install_cloudflared ;;
        2) setup_ddns_caddy ;;
        3) log_info "跳过公网访问配置" ;;
    esac

    # 5. 克隆仓库
    clone_repo

    # 6. Python 环境
    setup_python_env

    # 7. 生成 .env
    generate_env_files

    # 8. 运行时目录
    setup_runtime_dirs

    # 9. systemd 服务
    setup_systemd_services

    # 提示编辑 .env
    prompt_edit_env

    # 完成
    sleep 2
    printf '\n'
    printf '============================================================\n'
    printf '  部署完成！服务状态：\n'
    printf '============================================================\n'
    $SUDO systemctl status eating-medication-server --no-pager --lines=0 2>/dev/null || true
    $SUDO systemctl status eating-medication-family --no-pager --lines=0 2>/dev/null || true

    printf '\n'
    printf '%s\n' '------------------------------------------------------------'
    printf '  后续步骤:\n'
    printf '  1) 查看日志:\n'
    printf '     journalctl -u eating-medication-server -f\n'
    printf '     journalctl -u eating-medication-family -f\n'
    printf '  2) 更新代码: sudo bash %s/deploy/setup-linux.sh\n' "$DEPLOY_DIR"
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
