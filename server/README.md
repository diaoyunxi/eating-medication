# 智能用药管理系统 - 服务端

基于 FastAPI 的后端服务，提供设备注册、用药计划管理、服药记录、AI 问答、WebSocket 实时通信等功能。

## 快速开始

```bash
cd server
pip install -r requirements.txt
cp .env.example .env  # 编辑配置
python main.py
```

## API 文档

启动后访问 http://localhost:8000/docs 查看 Swagger UI。

## 配置项

参见 `.env.example`，主要配置：
- `DATABASE_URL`: 数据库连接
- `JWT_SECRET`: JWT 签名密钥
- `ALLOWED_ORIGINS`: CORS 允许的源
