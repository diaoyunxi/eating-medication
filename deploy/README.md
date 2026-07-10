# 部署辅助文件

本目录提供生产环境部署所需的守护进程配置与隧道示例文件。

## 文件清单

| 文件 | 用途 |
|------|------|
| `eating-medication-server.service` | 服务端（FastAPI :1059）systemd 单元 |
| `eating-medication-family.service` | 家属看护端（FastAPI Web :4430）systemd 单元 |
| `cloudflared.service` | Cloudflare 隧道守护进程 systemd 单元 |
| `cloudflared-config.yml` | Cloudflare 隧道路由配置示例（子路径转发） |

## 快速安装

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
- `ExecStart`：Python 解释器绝对路径（`which python3` 确认）

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
