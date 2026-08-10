# 智能用药管理系统 - 服务端

基于 FastAPI 的后端服务，提供设备注册、用药计划管理、服药记录、AI 问答、WebSocket 实时通信等功能。

## 快速开始

```bash
cd server
python common/install.py          # 自动安装依赖（推荐）
# 或手动：
# pip install -r requirements.txt
cp .env.example .env  # 编辑配置
python main.py
```

`common/install.py` 行为（已与其他模块统一为同一份脚本）：

1. venv 引导：已在虚拟环境则直接安装；否则检测 venv 工具（`venv`+`ensurepip` 模块），可用时复用/创建仓库根 `.venv`（`--system-site-packages`）并用其解释器重新执行安装；不可用时 Linux 尝试 `sudo apt-get install python3-venv` 后重试，Windows 仅提示并降级在当前环境继续。
2. 检测 `pip` 是否存在；无则按平台自动安装（Linux 优先 `apt-get install python3-pip`，Windows 下载 `get-pip.py`，其他走 `ensurepip` 后备）。
3. 正常 `pip install`：**默认不使用任何镜像源（走系统/官方默认源）**，首选源安装失败自动回退官方 PyPI 源 `https://pypi.org/simple`；可用环境变量 `PIP_INDEX_URL` 指定首选源（仍会回退官方源），不修改全局 pip 配置。
4. 若 `pip install` 输出包含 `--break-system-packages`（PEP 668 `externally-managed-environment` 错误），自动加上该参数重新 `pip install`。
5. 已安装的包自动跳过（优先 `importlib.import_module` 检测，回退 `pip show`）。

## API 文档

启动后访问 http://localhost:8000/docs 查看 Swagger UI。

## 配置项

参见 `.env.example`，主要配置：
- `DATABASE_URL`: 数据库连接
- `JWT_SECRET`: JWT 签名密钥
- `ALLOWED_ORIGINS`: CORS 允许的源
- `TURNSTILE_SECRET_KEY`: Cloudflare Turnstile 密钥（用于后端 siteverify 人机验证校验，未配置时跳过校验仅兼容开发环境，生产环境必须配置）
