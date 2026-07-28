#!/usr/bin/env bash
# -*- coding: utf-8 -*-
#
# eating-medication 一键部署脚本（server + family_monitor，systemd 托管）
#
# 适用：Debian/Ubuntu（apt）、Fedora/RHEL（dnf/yum）、Alpine（apk）等 systemd Linux。
# 默认部署目录 /opt/eating-medication，运行用户 deploy。
# 公网访问依赖你在 Cloudflare Zero Trust 已配置的隧道（本脚本不处理隧道）。
#
# 用法：
#   sudo bash deploy/setup.sh                 # 使用默认域名 my-website.ccwu.cc
#   sudo DOMAIN=你的域名 bash deploy/setup.sh # 自定义域名
#
# 幂等：可重复执行（更新代码 + 重装依赖 + 重启服务）。
#       .env 仅在不存在时生成，已存在则保留你的配置。

set -euo pipefail

# ===== 可配置变量 =====
DEPLOY_DIR="${DEPLOY_DIR:-/opt/eating-medication}"
DEPLOY_USER="deploy"
REPO_URL="https://github.com/diaoyunxi/eating-medication.git"
DOMAIN="${DOMAIN:-my-website.ccwu.cc}"
SERVER_PREFIX="/eating-medication/server"
FAMILY_PREFIX="/eating-medication/family"

# 当前是否已是 root：是则不加 sudo
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

echo "============================================================"
echo " eating-medication 一键部署"
echo " 部署目录 : $DEPLOY_DIR"
echo " 运行用户 : $DEPLOY_USER"
echo " 域名     : $DOMAIN"
echo " 隧道前缀 : $SERVER_PREFIX / $FAMILY_PREFIX"
echo "============================================================"

# ===== 1. 系统依赖 =====
echo "==> [1/7] 安装系统依赖 (git/python3/pip/curl)..."
if command -v apt-get >/dev/null 2>&1; then
  $SUDO apt-get update -y
  $SUDO apt-get install -y git python3 python3-pip python3-venv curl
elif command -v dnf >/dev/null 2>&1; then
  $SUDO dnf install -y git python3 python3-pip curl
elif command -v yum >/dev/null 2>&1; then
  $SUDO yum install -y git python3 python3-pip curl
elif command -v apk >/dev/null 2>&1; then
  $SUDO apk add --no-cache git python3 py3-pip curl
else
  echo "✗ 未识别的包管理器，请手动安装 git/python3/pip 后重试"
  exit 1
fi

# Python 版本提示（>=3.10 推荐）
PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0)"
echo "    检测到 Python $PY_VER"

# ===== 2. 克隆或更新仓库 =====
if [ -d "$DEPLOY_DIR/.git" ]; then
  echo "==> [2/7] 仓库已存在，拉取最新代码..."
  $SUDO git -C "$DEPLOY_DIR" pull --ff-only || $SUDO git -C "$DEPLOY_DIR" pull
else
  echo "==> [2/7] 克隆仓库 $REPO_URL ..."
  $SUDO git clone "$REPO_URL" "$DEPLOY_DIR"
fi

# ===== 3. 创建运行用户 =====
if id "$DEPLOY_USER" >/dev/null 2>&1; then
  echo "==> [3/7] 用户 $DEPLOY_USER 已存在，跳过"
else
  echo "==> [3/7] 创建系统用户 $DEPLOY_USER ..."
  if command -v useradd >/dev/null 2>&1; then
    $SUDO useradd -r -s /usr/sbin/nologin "$DEPLOY_USER" 2>/dev/null \
      || $SUDO useradd -r -s /sbin/nologin "$DEPLOY_USER"
  else
    $SUDO adduser -S -s /sbin/nologin "$DEPLOY_USER" 2>/dev/null \
      || $SUDO adduser -S "$DEPLOY_USER"
  fi
fi

# ===== 4. 创建虚拟环境并安装 Python 依赖（避免 PEP 668 / 系统 pip 污染）=====
# 可选：通过环境变量 PIP_MIRROR 指定 pip 镜像（默认清华源，国内更快）。
PIP_MIRROR="${PIP_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PIP_EXTRA=""
if [ -n "$PIP_MIRROR" ]; then PIP_EXTRA="-i $PIP_MIRROR"; fi
VENV="$DEPLOY_DIR/venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "==> [4/7] 创建虚拟环境 $VENV ..."
  $SUDO python3 -m venv "$VENV"
fi
echo "==> [4/7] 升级 venv pip ..."
$SUDO "$VENV/bin/python" -m pip install --upgrade pip $PIP_EXTRA || \
  $SUDO "$VENV/bin/python" -m pip install --upgrade pip
echo "==> [4/7] 安装 server 依赖 ..."
$SUDO "$VENV/bin/python" -m pip install -r "$DEPLOY_DIR/server/requirements.txt" $PIP_EXTRA || \
  $SUDO "$VENV/bin/python" -m pip install -r "$DEPLOY_DIR/server/requirements.txt"
echo "==> [4/7] 安装 family_monitor 依赖 ..."
$SUDO "$VENV/bin/python" -m pip install -r "$DEPLOY_DIR/family_monitor/requirements.txt" $PIP_EXTRA || \
  $SUDO "$VENV/bin/python" -m pip install -r "$DEPLOY_DIR/family_monitor/requirements.txt"
# venv 运行时只需被 deploy 读取/执行，归属 deploy 以免权限问题
$SUDO chown -R "$DEPLOY_USER:$DEPLOY_USER" "$VENV"

# ===== 5. 生成生产环境 .env（仅首次） =====
gen_key() { python3 -c "import secrets; print(secrets.token_urlsafe(32))"; }

write_server_env() {
  local f="$DEPLOY_DIR/server/.env"
  if [ -f "$f" ]; then echo "    $f 已存在，保留原配置"; return; fi
  local sk; sk="$(gen_key)"
  cat > "$f" <<EOF
# 生产环境配置（由 deploy/setup.sh 自动生成，请按需修改后重启服务）
APP_NAME=老年人用药管理系统
DEBUG=false
API_V1_PREFIX=/api/v1
PATH_PREFIX=$SERVER_PREFIX
SERVER_HOST=0.0.0.0
SERVER_PORT=1059
DATABASE_URL=sqlite:///./data/elderly_care.db
SECRET_KEY=$sk
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
# 允许的前端来源（子女端地址）；多个用逗号分隔
ALLOWED_ORIGINS=https://$DOMAIN$FAMILY_PREFIX
# OAuth 回调（与 GitHub/Gitee 后台配置一致）
GITHUB_OAUTH_CALLBACK_URL=https://$DOMAIN$SERVER_PREFIX/api/v1/auth/oauth/github/callback
GITEE_OAUTH_CALLBACK_URL=https://$DOMAIN$SERVER_PREFIX/api/v1/auth/oauth/gitee/callback
FAMILY_WEB_URL=https://$DOMAIN$FAMILY_PREFIX
# 以下为可选服务，留空则自动降级（功能关闭）：
#   MAIL_*        邮件验证码登录/找回密码
#   OCR_*         图片 OCR 识别
#   TURNSTILE_SECRET_KEY  Cloudflare 人机验证
#   GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET  GitHub 登录
#   GITEE_CLIENT_ID / GITEE_CLIENT_SECRET    Gitee 登录
#   ZHIPUAI_API_KEY / ZHIPUAI_MODEL          服务端 AI 全局兜底（用户也可在数据库各自配置）
EOF
  chmod 600 "$f"
  echo "    已生成 $f"
}

write_family_env() {
  local f="$DEPLOY_DIR/family_monitor/.env"
  if [ -f "$f" ]; then echo "    $f 已存在，保留原配置"; return; fi
  local sk; sk="$(gen_key)"
  cat > "$f" <<EOF
# 生产环境配置（由 deploy/setup.sh 自动生成，请按需修改后重启服务）
SERVER_HOST=0.0.0.0
SERVER_PORT=4430
# 老人端（服务端）地址，与 Cloudflare 隧道路由一致
ELDERLY_SERVER_URL=https://$DOMAIN$SERVER_PREFIX
PATH_PREFIX=$FAMILY_PREFIX
APP_NAME=子女守护中心
DEBUG=false
COOKIE_SECURE=true
PRODUCTION=true
SECRET_KEY=$sk
# 设备共享密钥（调用后端 X-Device-Secret 鉴权，留空则兼容旧版不发送）
DEVICE_SECRET=
# Cloudflare Turnstile 站点密钥（前端人机验证组件，留空则组件不渲染）
TURNSTILE_SITE_KEY=
ALLOWED_ORIGINS=https://$DOMAIN$FAMILY_PREFIX
DISPLAY_THEME=light
DISPLAY_COLOR=purple
DISPLAY_LANGUAGE=zh-CN
DISPLAY_ANIMATIONS=True
DISPLAY_COMPACT=False
EOF
  chmod 600 "$f"
  echo "    已生成 $f"
}

echo "==> [5/7] 生成生产环境 .env（server / family_monitor）..."
write_server_env
write_family_env

# ===== 6. 运行时目录与权限 =====
echo "==> [6/7] 创建运行时目录并修正权限..."
$SUDO mkdir -p \
  "$DEPLOY_DIR/server/data" "$DEPLOY_DIR/server/logs" \
  "$DEPLOY_DIR/family_monitor/data" "$DEPLOY_DIR/family_monitor/logs"
# 源码保持 root 可读；仅运行时可写目录与密钥文件归属 deploy
$SUDO chown -R "$DEPLOY_USER:$DEPLOY_USER" \
  "$DEPLOY_DIR/server/data" "$DEPLOY_DIR/server/logs" \
  "$DEPLOY_DIR/family_monitor/data" "$DEPLOY_DIR/family_monitor/logs"
[ -f "$DEPLOY_DIR/server/.env" ] && $SUDO chown "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_DIR/server/.env" || true
[ -f "$DEPLOY_DIR/family_monitor/.env" ] && $SUDO chown "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_DIR/family_monitor/.env" || true

# ===== 7. 安装 systemd 服务并启动 =====
echo "==> [7/7] 安装 systemd 服务并启动..."
$SUDO cp "$DEPLOY_DIR/deploy/eating-medication-server.service" /etc/systemd/system/
$SUDO cp "$DEPLOY_DIR/deploy/eating-medication-family.service" /etc/systemd/system/
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now eating-medication-server eating-medication-family

# 配置 deploy 用户免密重启本项目的两个服务（供 updater.py 自动更新后重启使用）
echo "==> [7/7] 配置 $DEPLOY_USER 免密重启服务（自动更新用）..."
SUDOERS_FILE="/etc/sudoers.d/eating-medication"
$SUDO tee "$SUDOERS_FILE" >/dev/null <<EOF
# eating-medication: 允许 $DEPLOY_USER 免密重启/查看应用服务（由 updater.py 自动更新后调用）
$DEPLOY_USER ALL=(root) NOPASSWD: \
    /usr/bin/systemctl restart eating-medication-server eating-medication-family, \
    /usr/bin/systemctl status eating-medication-server eating-medication-family, \
    /bin/systemctl restart eating-medication-server eating-medication-family, \
    /bin/systemctl status eating-medication-server eating-medication-family
EOF
$SUDO chmod 440 "$SUDOERS_FILE"
$SUDO visudo -c -f "$SUDOERS_FILE" || { echo "✗ sudoers 语法校验失败，请检查"; exit 1; }

sleep 3
echo
echo "============================================================"
echo " 部署完成！服务状态："
echo "============================================================"
$SUDO systemctl status eating-medication-server --no-pager --lines=0 || true
$SUDO systemctl status eating-medication-family --no-pager --lines=0 || true

echo
echo "------------------------------------------------------------"
echo " 后续步骤："
echo " 1) 查看日志："
echo "    journalctl -u eating-medication-server -f"
echo "    journalctl -u eating-medication-family -f"
echo " 2) 如需修改配置，编辑后重启："
echo "    sudo nano $DEPLOY_DIR/server/.env"
echo "    sudo nano $DEPLOY_DIR/family_monitor/.env"
echo "    sudo systemctl restart eating-medication-server eating-medication-family"
echo " 3) Cloudflare 隧道（你已配置）需确保两条公网路由指向本机："
echo "    $SERVER_PREFIX  -> http://localhost:1059"
echo "    $FAMILY_PREFIX  -> http://localhost:4430"
echo " 4) 更新代码：sudo bash $DEPLOY_DIR/deploy/setup.sh"
echo "------------------------------------------------------------"
