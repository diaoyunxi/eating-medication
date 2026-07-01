# -*- coding: utf-8 -*-
import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# 将项目根目录添加到 Python 路径，以便导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.database import Base
from app.core.config import settings
# H12：删除不存在的 purchase_suggestion 引用
from app.models import user, medication_plan, medication_record, ai_query_log

# 这是 Alembic 使用的 MetaData 对象，用于自动生成迁移脚本
target_metadata = Base.metadata

# 读取 Alembic 配置中的日志设置
config = context.config

# 覆盖配置文件中的数据库 URL 为应用实际使用的 URL
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def run_migrations_offline():
    """离线模式迁移（仅生成 SQL，不连接数据库）"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """在线模式迁移（连接数据库执行）"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()