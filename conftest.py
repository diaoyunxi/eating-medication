# -*- coding: utf-8 -*-
"""
仓库根目录 pytest 配置（conftest）。

CI 工作流 `.github/workflows/python-app.yml` 在仓库根执行 `pytest`，
本文件确保：
1. `server` 模块（顶层包 `app`）加入 sys.path，使 `import app...` 可用。
2. 注入测试环境变量，避免测试依赖真实 `.env` / 外部服务。

说明：elderly_assistant / family_monitor 由于各自存在同名顶层包 `core`，
不在此统一加入 sys.path（避免导入冲突）。相关测试通过
`tests/_helpers.load_module()` 按文件路径加载为唯一模块名。
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# server 后端以 `app` 为顶层包
SERVER = REPO_ROOT / "server"
if SERVER.exists() and str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

# 测试环境变量（覆盖真实配置，避免外部依赖）
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci-not-for-prod")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("GITHUB_TOKEN", "")
# 避免测试触发真实 .env 文件加载副作用
os.environ.setdefault("APP_SKIP_ENV_FILE", "1")
