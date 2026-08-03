# 部署辅助文件

本目录提供生产环境部署所需的守护进程配置、隧道示例文件与一键部署脚本。

## 文件清单

| 文件 | 用途 |
|------|------|
| `setup-linux.sh` | Linux 一键部署脚本（bash，支持 apt/dnf/yum/pacman/apk） |
| `setup-mac.sh` | macOS 一键部署脚本（zsh，Homebrew + launchd） |
| `eating-medication-server.service` | 服务端（FastAPI :1059）systemd 单元 |
| `eating-medication-family.service` | 家属看护端（FastAPI Web :4430）systemd 单元 |
| `cloudflared.service` | Cloudflare 隧道守护进程 systemd 单元 |
| `cloudflared-config.yml` | Cloudflare 隧道路由配置示例（子路径转发） |

> Windows 部署脚本 `setup.ps1` 位于仓库根目录。

## 一键部署（推荐）

### Linux / macOS

通过仓库根目录的 `setup.sh` 引导器，自动检测操作系统并下载执行对应平台脚本：

```bash
# curl 一键部署（Linux / macOS 通用）
curl -fsSL https://raw.githubusercontent.com/diaoyunxi/eating-medication/main/setup.sh | sh

# 或先下载再执行
curl -fsSL https://raw.githubusercontent.com/diaoyunxi/eating-medication/main/setup.sh -o setup.sh
sh setup.sh
```

也可直接运行对应平台脚本：

```bash
# Linux（需 root 或 sudo）
sudo bash deploy/setup-linux.sh
# 自定义域名
sudo DOMAIN=你的域名 bash deploy/setup-linux.sh

# macOS（需 root 或 sudo）
sudo zsh deploy/setup-mac.sh
# 自定义域名
sudo DOMAIN=你的域名 zsh deploy/setup-mac.sh
```

### Windows

以管理员身份运行 PowerShell，执行：

```powershell
# 一键部署（下载并执行）
irm https://raw.githubusercontent.com/diaoyunxi/eating-medication/main/setup.ps1 | iex

# 或先下载再执行
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/diaoyunxi/eating-medication/main/setup.ps1" -OutFile "setup.ps1"
.\setup.ps1

# 自定义参数
.\setup.ps1 -Domain "你的域名" -ServiceMode nssm
```

### 部署脚本功能

脚本会自动完成以下步骤（幂等，可重复执行）：

1. **检测系统**：识别操作系统、架构、包管理器
2. **安装系统依赖**：git、python3、curl（Linux），Homebrew + git + python3（macOS），winget 安装 git + python（Windows）
3. **选择公网访问模式**（三选一）：
   - **Cloudflare 隧道**（推荐）：本地无需公网 IP，cloudflared 建立加密隧道
   - **DDNS + Caddy**：需公网 IP，Caddy 自动申请 Let's Encrypt 证书（Windows 仅创建 DDNS 脚本）
   - **仅内网访问**：不配置公网
4. **克隆仓库**：GitHub 主源，Gitee 镜像回退
5. **创建虚拟环境**：独立 venv，安装 server + family_monitor 的 Python 依赖
6. **生成生产 .env**：仅首次生成（已存在则保留），自动生成 SECRET_KEY
7. **创建运行时目录**：data/、logs/
8. **安装系统服务并启动**：
   - Linux：systemd 服务（eating-medication-server / eating-medication-family）
   - macOS：launchd 服务（com.eatingmedication.server / family）
   - Windows：NSSM Windows 服务 或 计划任务
9. **提示编辑 .env**：等待用户编辑配置后重启服务

### 部署目录与端口

| 平台 | 部署目录 | 服务端端口 | 子女端端口 |
|------|----------|------------|------------|
| Linux | `/opt/eating-medication` | 1059 | 4430 |
| macOS | `/usr/local/eating-medication` | 1059 | 4430 |
| Windows | `C:\eating-medication` | 1059 | 4430 |

### 公网访问路由

Cloudflare 隧道或 Caddy 反代需配置以下路由：

| 路径前缀 | 转发目标 |
|----------|----------|
| `/eating-medication/server` | `http://localhost:1059` |
| `/eating-medication/family` | `http://localhost:4430` |

## 自动更新与自动重启

仓库根目录 `updater.py` 在应用启动时会检查 GitHub Release：当发现新版本且根目录 `.env` 的 `AUTO_PULL=true`（默认）时，自动下载完整发布包并安全更新——仅覆盖代码文件，保留 `.env`、`data/`、`logs/`、`*.db` 等运行时数据，并做 SHA256 校验。

更新完成后，`updater.py` 会自动重启以下服务：

- Linux：`eating-medication-server`（:1059）、`eating-medication-family`（:4430）—— 通过 systemd 免密 sudoers 规则
- macOS：launchd 服务自动 KeepAlive 重启
- Windows：NSSM 服务自动 Restart / 计划任务 RestartCount

> 非 systemd 环境（本地开发、容器等）不会尝试自动重启，仅打印提示。

## 手动安装

### Linux（systemd）

```bash
# 1. 复制 systemd 单元到系统目录
sudo cp eating-medication-server.service eating-medication-family.service /etc/systemd/system/
sudo cp cloudflared.service /etc/systemd/system/

# 2. 创建 cloudflared 隧道 token 环境文件
sudo mkdir -p /etc/cloudflared
echo "TUNNEL_TOKEN=你的隧道token" | sudo tee /etc/cloudflared/cloudflared.env
sudo chmod 0600 /etc/cloudflared/cloudflared.env
sudo chown cloudflared:cloudflared /etc/cloudflared/cloudflared.env

# 3. 重载 systemd 并启用开机自启
sudo systemctl daemon-reload
sudo systemctl enable --now eating-medication-server eating-medication-family cloudflared

# 4. 查看状态
sudo systemctl status eating-medication-server eating-medication-family cloudflared
```

### Windows（手动 NSSM）

```powershell
# 1. 下载 NSSM
nssm install EatingMedication-Server "C:\eating-medication\venv\Scripts\python.exe" "main.py"
nssm set EatingMedication-Server AppDirectory "C:\eating-medication\server"
nssm set EatingMedication-Server AppEnvironmentExtra PYTHONUNBUFFERED=1
nssm set EatingMedication-Server Start SERVICE_AUTO_START
nssm set EatingMedication-Server AppStdout "C:\eating-medication\server\logs\service.log"
nssm set EatingMedication-Server AppStderr "C:\eating-medication\server\logs\service.err.log"
nssm start EatingMedication-Server

# 2. 同样安装 family 服务
nssm install EatingMedication-Family "C:\eating-medication\venv\Scripts\python.exe" "main.py"
nssm set EatingMedication-Family AppDirectory "C:\eating-medication\family_monitor"
nssm set EatingMedication-Family Start SERVICE_AUTO_START
nssm start EatingMedication-Family
```

## Cloudflare 隧道配置

`cloudflared-config.yml` 仅作示例，推荐通过 Cloudflare Zero Trust 控制台配置隧道路由：

1. 控制台创建隧道，复制 token 写入 `/etc/cloudflared/cloudflared.env`（Linux）或通过 `cloudflared service install` 注册 Windows 服务
2. 添加两条 Public Hostname 路由：
   - 子路径 `/eating-medication/server` → `http://localhost:1059`
   - 子路径 `/eating-medication/family` → `http://localhost:4430`
3. 在 Cloudflare DNS 为域名添加 CNAME 指向隧道 ID（控制台可自动完成）

## 日志查看

### Linux

```bash
journalctl -u eating-medication-server -f       # 服务端日志
journalctl -u eating-medication-family -f       # 家属端日志
journalctl -u cloudflared -f                    # 隧道日志
```

### macOS

```bash
tail -f /usr/local/eating-medication/server/logs/launchd.log
tail -f /usr/local/eating-medication/family_monitor/logs/launchd.log
```

### Windows

```powershell
# NSSM 服务日志
Get-Content C:\eating-medication\server\logs\service.log -Tail 30 -Wait
Get-Content C:\eating-medication\family_monitor\logs\service.log -Tail 30 -Wait

# 服务状态
nssm status EatingMedication-Server
nssm status EatingMedication-Family
```
