# 部署辅助文件

本目录提供生产环境部署所需的守护进程配置与隧道示例文件。

## 文件清单

| 文件 | 用途 |
|------|------|
| `eating-medication-server.service` | 服务端（FastAPI :1059）systemd 单元 |
| `eating-medication-family.service` | 家属看护端（FastAPI Web :4430）systemd 单元 |
| `cloudflared.service` | Cloudflare 隧道守护进程 systemd 单元 |
| `cloudflared-config.yml` | Cloudflare 隧道路由配置示例（子路径转发） |

## 一键部署（推荐）

仓库提供 `deploy/setup.sh`，可一条命令完成「克隆代码 → 装依赖 → 生成生产 `.env` → 建 systemd 服务并启动」，幂等可重跑。

```bash
# 登录服务器后执行（默认域名 my-website.ccwu.cc）
sudo bash /opt/eating-medication/deploy/setup.sh
# 或自定义域名
sudo DOMAIN=你的域名 bash /opt/eating-medication/deploy/setup.sh
```

脚本会自动：
1. 安装系统依赖（git/python3/pip/curl）
2. 克隆或更新仓库到 `/opt/eating-medication`
3. 创建 `deploy` 运行用户
4. 创建独立虚拟环境 `/opt/eating-medication/venv` 并安装 `server` 与 `family_monitor` 的 Python 依赖（避免污染系统 Python，兼容 Debian 12+ 的 PEP 668）
5. 生成生产环境 `.env`（仅首次，已存在则保留）；`DEBUG=false`、`PRODUCTION=true`
6. 创建运行时目录（`data/`、`logs/`）并修正权限
7. 安装并启动 `eating-medication-server`（:1059）、`eating-medication-family`（:4430）

> 公网访问依赖你在 Cloudflare Zero Trust 已配置的隧道（脚本不处理隧道），请确保两条路由：
> `/eating-medication/server → :1059`、`/eating-medication/family → :4430`。

## 自动更新与自动重启

仓库根目录 `updater.py` 在应用启动时会检查 GitHub Release：当发现新版本且根目录 `.env` 的 `AUTO_PULL=true`（默认）时，自动下载完整发布包（eating-medication-vX.Y.Z.zip）并**安全更新**——仅覆盖代码文件，保留 `.env`、`data/`、`logs/`、`*.db` 等运行时数据，并做 SHA256 校验。

更新完成后，`updater.py` 会**自动重启**以下 systemd 服务以加载新版本，无需人工干预：

- `eating-medication-server`（:1059）
- `eating-medication-family`（:4430）

自动重启依赖部署时写入的免密 sudoers 规则（由 `deploy/setup.sh` 步骤 7 生成 `/etc/sudoers.d/eating-medication`，允许 `deploy` 用户 `sudo -n systemctl restart` 这两个服务）。

> 说明：若采用「手动安装」或未执行 `setup.sh`，请自行为运行用户配置等效的免密 sudoers，或以 root 身份运行更新；否则自动重启会因权限不足失败，此时日志会提示「请手动重启服务」。
> 非 systemd 环境（本地开发、Windows、容器等）不会尝试自动重启，仅打印提示。

## 手动安装

```bash
# 1. 复制 systemd 单元到系统目录
sudo cp eating-medication-server.service eating-medication-family.service /etc/systemd/system/
sudo cp cloudflared.service /etc/systemd/system/

# 2. 创建 cloudflared 隧道 token 环境文件（避免命令行暴露 token）
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

## 路径约定

示例中部署目录为 `/opt/eating-medication/`，运行用户为 `deploy`，请按实际环境修改：
- `WorkingDirectory`：各模块的根目录（含 `main.py` 的目录）
- `User` / `Group`：运行服务的系统用户
- `ExecStart`：Python 解释器绝对路径（`/opt/eating-medication/venv/bin/python`，由 `setup.sh` 创建）

## Cloudflare 隧道配置

`cloudflared-config.yml` 仅作示例，推荐通过 Cloudflare Zero Trust 控制台配置隧道路由：
1. 控制台创建隧道，复制 token 写入 `/etc/cloudflared/cloudflared.env`（内容 `TUNNEL_TOKEN=xxx`，权限 0600），`cloudflared.service` 通过 `EnvironmentFile` 读取，避免命令行暴露。
2. 添加两条 Public Hostname 路由：
   - 子路径 `/eating-medication/server` → `http://localhost:1059`
   - 子路径 `/eating-medication/family` → `http://localhost:4430`
3. 在 Cloudflare DNS 为域名添加 CNAME 指向隧道 ID（控制台可自动完成）。

## 日志查看

```bash
journalctl -u eating-medication-server -f       # 服务端日志
journalctl -u eating-medication-family -f       # 家属端日志
journalctl -u cloudflared -f                    # 隧道日志
```
