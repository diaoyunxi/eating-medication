# -*- coding: utf-8 -*-
"""应用启动引导。

将 config 模块的导入期副作用（首次运行生成/补齐 .env、必填项校验可能 sys.exit）
收敛到显式调用，避免在 ``import app.core.config`` 时写磁盘，或在测试 / 导入场景
下因配置非法而意外退出进程。

调用点：``server/main.py`` 的 ``create_app_dirs()``（生产 systemd 启动入口），
确保 .env 就绪后再构建并校验配置。
"""
import logging

from app.core.config import (
    BASE_DIR,
    Settings,
    _ensure_default_env,
    validate_mandatory_config,
)

logger = logging.getLogger(__name__)


def bootstrap_config():
    """确保 .env 存在且字段完整，随后构建全局 settings 并做必填校验。

    返回重建后的 settings 实例，并同步写回模块全局 ``app.core.config.settings``，
    使首跑生成的 .env 立即对后续导入（如 ``app.main``）生效。

    注意：必须在任何依赖 settings 的业务逻辑执行前调用。当前在
    ``server/main.py`` 的 ``create_app_dirs()`` 中、``uvicorn`` 导入 ``app.main``
    之前调用。
    """
    # 1) 确保 .env 存在且含全部必填字段（首次运行写入完整模板；已存在则补齐缺失项）
    _ensure_default_env()

    # 2) 重建全局 settings，使首跑生成的 .env 立即生效。
    #    config.settings 被大量模块以 ``from app.core.config import settings`` 直接引用，
    #    此处重建并写回模块全局，保证同一进程内后续导入取到最新实例。
    import app.core.config as cfg_mod
    cfg_mod.settings = Settings()

    # 3) 启动期集中校验必填配置；缺失/非法打印清晰提示并结束进程
    validate_mandatory_config()

    logger.info("配置引导完成：.env 已就绪，必填项校验通过")
    return cfg_mod.settings
