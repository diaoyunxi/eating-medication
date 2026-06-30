# 子女看护Web端

为子女提供的Web界面，用于查看老人的用药提醒和记录。

## 功能特性

- 🔐 用户认证系统（bcrypt不可逆加密）
- 📊 老人端连接状态监控
- ⏰ 用药提醒查看
- 📋 用药记录查看
- 💎 精美的UI设计
- 📱 响应式设计

## 快速开始

### 1. 安装依赖

```bash
python install.py
```

安装脚本会自动：
- 备份原有pip配置
- 配置清华镜像源
- 安装所有依赖

### 2. 配置

复制 `.env.example` 为 `.env` 并修改配置：

```bash
cp .env.example .env
```

主要配置项：
- `SERVER_HOST`: 服务监听地址 (默认: 0.0.0.0)
- `SERVER_PORT`: 服务端口 (默认: 4430)
- `ELDERLY_SERVER_URL`: 老人端服务器地址
- `DEBUG`: 调试模式
- `APP_NAME`: 应用名称
- `SECRET_KEY`: 会话加密密钥（生产环境请修改）

### 3. 启动服务

```bash
python main.py
```

然后在浏览器访问：`http://localhost:4430`

### 4. 注册/登录

首次使用需要注册账户：
- 访问 `http://localhost:4430/register` 注册新账户
- 访问 `http://localhost:4430/login` 登录

## 项目结构

```
family_monitor/
├── main.py                 # 主程序入口
├── install.py              # 自动安装脚本
├── requirements.txt        # Python依赖
├── .env                   # 配置文件
├── .env.example           # 配置文件示例
├── .gitignore             # Git忽略文件
├── core/                  # 核心模块
│   ├── __init__.py
│   ├── config.py          # 配置管理
│   ├── auth.py            # 用户认证
│   └── session.py         # 会话管理
├── routes/                # 路由模块
│   ├── __init__.py
│   ├── home.py            # 首页路由
│   └── auth.py            # 认证路由
├── templates/             # HTML模板
│   ├── index.html         # 首页
│   ├── dashboard.html     # 仪表板
│   ├── reminders.html     # 提醒页面
│   ├── records.html       # 记录页面
│   ├── settings.html      # 设置页面
│   ├── login.html         # 登录页面
│   └── register.html      # 注册页面
└── static/                # 静态文件 (CSS, JS等)
    └── css/
        └── style.css      # 全局样式
```

## 安全特性

- **密码加密**：使用bcrypt算法进行不可逆加密
- **会话管理**：使用itsdangerous创建加密会话令牌
- **Cookie安全**：httponly=True防止XSS攻击
- **敏感信息**：.env和data/目录已排除版本控制

## 注意事项

- 需要先启动老人端服务器
- 确保老人端API可访问
- 端口4430不需要特殊权限
- SECRET_KEY在生产环境中应修改

## 许可证

MIT License
