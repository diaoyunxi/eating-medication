# 智能用药管理系统 - 服务端

基于 FastAPI 的后端服务，提供设备注册、用药计划管理、服药记录、AI 问答、WebSocket 实时通信等功能。

## 快速开始

```bash
cd server
python install.py          # 自动安装依赖（推荐）
# 或手动：
# pip install -r requirements.txt
cp .env.example .env  # 编辑配置
python main.py
```

`install.py` 行为（已与其他模块统一为同一份脚本）：

1. 先检测 `pip` 是否存在；无则按平台自动安装（Linux 优先 `apt-get install python3-pip`，Windows 下载 `get-pip.py`，其他走 `ensurepip` 后备）。
2. 正常 `pip install`（使用 `-i PIP_INDEX_URL` 临时指定镜像源，默认清华源，可通过环境变量覆盖，不修改全局 pip 配置）。
3. 若 `pip install` 输出包含 `--break-system-packages`（PEP 668 `externally-managed-environment` 错误），自动加上该参数重新 `pip install`。
4. 已安装的包自动跳过（优先 `importlib.import_module` 检测，回退 `pip show`）。

## API 文档

启动后访问 http://localhost:8000/docs 查看 Swagger UI。

## 配置项

参见 `.env.example`，主要配置：
- `DATABASE_URL`: 数据库连接
- `JWT_SECRET`: JWT 签名密钥
- `ALLOWED_ORIGINS`: CORS 允许的源
