# 子女看护Web端

为子女提供的Web界面，用于查看老人的用药提醒和记录。

## 功能特性

- 🔐 用户认证系统（bcrypt不可逆加密）
- 📊 老人端连接状态监控
- ⏰ 用药提醒查看
- 📋 用药记录查看
- 💬 与老人端实时消息
- 🎨 精美的UI设计
- 📱 响应式设计
- 🛡️ 完善的安全防护（CSRF、安全响应头、登录限流、会话撤销）

## 快速开始

### 1. 安装依赖

```bash
python install.py
```

安装脚本行为（已与其他模块统一为同一份脚本）：

1. 先检测 `pip` 是否存在；无则按平台自动安装（Linux 优先 `apt-get install python3-pip`，Windows 下载 `get-pip.py`，其他走 `ensurepip` 后备）。
2. 正常 `pip install`（使用 `-i PIP_INDEX_URL` 临时指定镜像源，默认清华源，可通过环境变量覆盖，不修改全局 pip 配置）。
3. 若 `pip install` 输出包含 `--break-system-packages`（PEP 668 `externally-managed-environment` 错误），自动加上该参数重新 `pip install`。
4. 已安装的包自动跳过（优先 `importlib.import_module` 检测，回退 `pip show`）。

> 推荐使用虚拟环境安装：
> ```bash
> python -m venv venv
> source venv/bin/activate  # Windows: venv\Scripts\activate
> python install.py
> ```

### 2. 配置

#### 配置文件 config.json

复制 `config.json.example` 为 `config.json` 并修改：

```bash
cp config.json.example config.json
```

主要配置项：
- `SERVER_HOST`: 服务监听地址（默认: 0.0.0.0）
- `SERVER_PORT`: 服务端口（默认: 4430）
- `ELDERLY_SERVER_URL`: 老人端服务器地址
- `DEBUG`: 调试模式
- `APP_NAME`: 应用名称
- `PATH_PREFIX`: 路径前缀（Cloudflare 隧道子路径，本地直连设为空）
- `DISPLAY_THEME` / `DISPLAY_COLOR` 等：界面显示设置

#### 敏感配置 .env（推荐）

`SECRET_KEY` 等敏感配置应通过 `.env` 文件注入，不应写入 `config.json`：

```bash
cat > .env <<'EOF'
# 会话加密密钥（生产环境必须配置为一个固定的随机字符串）
SECRET_KEY=请替换为您生成的随机密钥
# 是否为生产环境（true 时禁止通过 Web 修改 DEBUG）
PRODUCTION=false
# Cookie 是否启用 secure 标志（本地 HTTP 调试可设为 false）
COOKIE_SECURE=true
# CORS 允许的来源（逗号分隔）
ALLOWED_ORIGINS=http://localhost:4430,http://127.0.0.1:4430
EOF
```

> 生成随机 SECRET_KEY：
> ```bash
> python -c "import secrets; print(secrets.token_urlsafe(32))"
> ```

如果 `SECRET_KEY` 未配置，启动时会自动生成临时密钥并打印警告，但**重启后会话将失效**。

### 3. 启动服务

```bash
python main.py
```

然后在浏览器访问：`http://localhost:4430`

### 4. 注册/登录

首次使用需要注册账户：
- 访问 `http://localhost:4430/register` 注册新账户
- 访问 `http://localhost:4430/login` 登录
- 管理员设置入口：`http://localhost:4430/admin/administrator/setting`

## 项目结构

```
family_monitor/
├── main.py                 # 主程序入口（含中间件、生命周期、路由注册）
├── install.py              # 自动安装脚本（不修改全局 pip 配置）
├── updater.py              # 自动更新检查模块
├── requirements.txt        # Python 依赖（使用 ~= 兼容版本）
├── config.json             # 运行时配置（已被 .gitignore 忽略）
├── config.json.example     # 配置文件模板（不含敏感值）
├── .env                    # 敏感配置（SECRET_KEY 等，已被 .gitignore 忽略）
├── .gitignore              # Git 忽略文件
├── core/                   # 核心模块
│   ├── __init__.py
│   ├── config.py           # 配置管理（不写回 os.environ）
│   ├── auth.py             # 用户认证（fcntl 文件锁 + 0600 权限）
│   ├── session.py          # 会话管理（含 CSRF token、会话撤销持久化）
│   └── api_client.py       # 老人端 API 客户端（device_id URL 编码）
├── routes/                 # 路由模块
│   ├── __init__.py         # 路由模块注册
│   ├── home.py             # 首页、仪表板、提醒、记录、设置路由
│   ├── auth.py             # 登录、注册、登出路由（含登录限流）
│   ├── chat.py             # 实时消息路由
│   └── admin.py            # 管理员设置路由
├── templates/              # HTML 模板
│   ├── index.html          # 首页
│   ├── dashboard.html      # 仪表板
│   ├── reminders.html      # 用药提醒页面
│   ├── records.html        # 用药记录页面
│   ├── medication_settings.html  # 用药设置页面
│   ├── chat.html           # 消息页面
│   ├── settings.html       # 设置页面
│   ├── admin_settings.html # 管理员设置页面
│   ├── login.html          # 登录页面
│   └── register.html       # 注册页面
└── static/                 # 静态文件
    └── css/
        ├── style.css       # 全局样式
        └── main.css        # 主样式
```

## 安全特性

- **密码加密**：使用 bcrypt 算法进行不可逆加密
- **会话管理**：使用 itsdangerous 创建带签名的会话令牌，登出时撤销并持久化到 `data/revoked_tokens.json`
- **Cookie 安全**：`httponly=True`、`samesite=strict`、`secure`（可配置）防止 XSS 和 CSRF
- **CSRF 防护**：双重提交 Cookie 模式（cookie + 表单隐藏字段 / `X-CSRF-Token` 请求头），所有 POST 请求均校验
- **CORS 收紧**：仅允许 `ALLOWED_ORIGINS` 配置的来源，关闭通配符
- **安全响应头**：`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy`、`Content-Security-Policy`
- **登录限流**：每分钟每 IP 最多 5 次登录尝试，防止暴力破解
- **会话撤销**：登出后令牌立即失效并持久化，重启后仍然有效
- **文件权限**：用户数据文件 `users.json` 保存后自动 `chmod 0600`，并使用 `fcntl` 文件锁防并发写
- **XSS 防护**：模板移除 `| safe`，使用 `data-*` 属性 + `textContent` 渲染动态内容
- **路径精确匹配**：公开路径使用精确匹配，防止路径前缀绕过
- **敏感信息隔离**：`SECRET_KEY` 仅通过 `.env` 注入，禁止通过 Web 修改
- **生产环境保护**：`PRODUCTION=true` 时禁止通过 Web 修改 `DEBUG`
- **URL 编码**：`device_id` 等参数在拼接 URL 时进行编码，防止注入
- **版本控制排除**：`.env`、`config.json`、`data/` 已加入 `.gitignore`

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `SECRET_KEY` | 会话加密密钥（生产环境必须配置） | 空（自动生成临时密钥） |
| `PRODUCTION` | 是否为生产环境 | `false` |
| `COOKIE_SECURE` | Cookie 是否启用 secure 标志 | `true` |
| `ALLOWED_ORIGINS` | CORS 允许的来源（逗号分隔） | `http://localhost:4430,http://127.0.0.1:4430` |
| `SERVER_HOST` | 服务监听地址 | `0.0.0.0` |
| `SERVER_PORT` | 服务端口 | `4430` |
| `ELDERLY_SERVER_URL` | 老人端服务器地址 | - |
| `PATH_PREFIX` | 路径前缀 | `/eating-medication/family` |
| `DEBUG` | 调试模式 | `False` |
| `PIP_INDEX_URL` | install.py 使用的 pip 镜像源 | 清华源 |

## 注意事项

- 需要先启动老人端服务器
- 确保老人端 API 可访问
- 端口 4430 不需要特殊权限
- 生产环境必须通过 `.env` 配置固定的 `SECRET_KEY`，并设置 `PRODUCTION=true`
- HTTPS 由 Cloudflare 隧道边缘自动配置，本地监听纯 HTTP

## 许可证

MIT License
