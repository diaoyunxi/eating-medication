# -*- coding: utf-8 -*-
"""数据库连接与引擎管理

支持多种数据库后端（通过 settings.DATABASE_URL 切换）：
- SQLite（默认，单文件本地部署）：sqlite:///./data/elderly_care.db
- MySQL / MariaDB（生产远程数据库，pymysql 驱动）：
      mysql+pymysql://user:password@host:3306/dbname
- PostgreSQL（生产远程数据库，psycopg2 驱动）：
      postgresql+psycopg2://user:password@host:5432/dbname

特性：
1. 按方言自动选择连接参数（如 MySQL 使用 utf8mb4 字符集、连接池预检与回收）。
2. 检测不到目标数据库时自动建库（详见 ensure_database_exists）。
3. UTCDateTime：跨库兼容的 UTC 时间类型，写入时去除时区信息，规避
   MySQL/pymysql 对带时区 datetime 的报错，读取行为与 SQLite 一致。
"""
import logging
from datetime import timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text, pool
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.types import TypeDecorator, DateTime
from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 跨库兼容工具
# ---------------------------------------------------------------------------
def _db_scheme(database_url: str) -> str:
    """返回 URL 的基础方言（去掉 +driver 后缀），如 mysql / postgresql / sqlite。"""
    return urlparse(database_url).scheme.split("+")[0].lower()


def _is_server_database(scheme: str) -> bool:
    """判断是否为需要服务端预建库的数据库（非文件型）。"""
    return scheme in ("mysql", "mariadb", "postgresql", "mssql", "oracle")


class UTCDateTime(TypeDecorator):
    """跨库兼容的 UTC 时间类型。

    - 写入：将带时区的时间统一转换为 naive UTC。MySQL/pymysql 不支持
      带时区 datetime，必须去除时区信息才能写入；SQLite / PostgreSQL 写入
      naive 值也完全合规。
    - 读取：原样返回 naive datetime。调用方（如 device_service）已有
      「读取后补 UTC 时区」的兼容逻辑，行为与现有 SQLite 部署完全一致。
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        return value


# ---------------------------------------------------------------------------
# 自动建库：检测不到数据库时创建
# ---------------------------------------------------------------------------
def ensure_database_exists(database_url: str = None):
    """确保目标数据库存在；不存在时自动建库。

    - SQLite：文件型，引擎会自动创建，这里仅确保父目录存在。
    - MySQL / MariaDB / PostgreSQL：连接「服务管理库」（mysql 不带库名、
      postgres 连 postgres 库）查询数据库是否存在，不存在则 CREATE DATABASE。
    建库失败仅记录警告，不直接中断，交由后续建表逻辑暴露更明确的错误。
    """
    if database_url is None:
        database_url = settings.DATABASE_URL
    scheme = _db_scheme(database_url)
    parsed = urlparse(database_url)

    if scheme == "sqlite":
        # SQLite 文件由引擎自动创建，提前建好父目录避免首次写入失败
        db_path = parsed.path
        if db_path:
            parent = Path(db_path).resolve().parent
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"创建 SQLite 数据库父目录失败（可忽略）: {e}")
        return

    if not _is_server_database(scheme):
        # 其他未知类型交给引擎处理
        return

    db_name = parsed.path.lstrip("/")
    if not db_name:
        logger.warning("DATABASE_URL 未指定数据库名，跳过自动建库")
        return

    # 构造「管理连接」URL（不含目标库名）
    admin_path = "/postgres" if scheme == "postgresql" else "/"
    admin_url = urlunparse((parsed.scheme, parsed.netloc, admin_path, "", "", ""))

    try:
        admin_engine = create_engine(admin_url, poolclass=pool.NullPool, future=True)
        with admin_engine.connect() as conn:
            if scheme in ("mysql", "mariadb"):
                exists = (
                    conn.execute(text("SHOW DATABASES LIKE :name"), {"name": db_name}).first()
                    is not None
                )
            else:  # postgresql
                exists = (
                    conn.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :name"),
                        {"name": db_name},
                    ).first()
                    is not None
                )

        if exists:
            logger.info(f"数据库 '{db_name}' 已存在")
        else:
            logger.info(f"未检测到数据库 '{db_name}'，正在自动创建...")
            # CREATE DATABASE 不支持参数化，数据库名来自配置、仅做标识符引用
            with admin_engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            ) as conn:
                if scheme in ("mysql", "mariadb"):
                    conn.execute(
                        text(
                            f"CREATE DATABASE `{db_name}` "
                            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                        )
                    )
                else:  # postgresql
                    conn.execute(text(f'CREATE DATABASE "{db_name}"'))
            logger.info(f"已自动创建数据库 '{db_name}'")
        admin_engine.dispose()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"自动建库检查失败（将尝试直接连接，错误可能在此后暴露）: {e}"
        )


# ---------------------------------------------------------------------------
# 引擎构建（按方言调优）
# ---------------------------------------------------------------------------
def _build_engine():
    scheme = _db_scheme(settings.DATABASE_URL)
    connect_args = {}
    engine_kwargs = {}

    if scheme == "sqlite":
        connect_args = {"check_same_thread": False}
    elif scheme in ("mysql", "mariadb"):
        # pymysql 使用 utf8mb4 字符集，避免中文乱码
        connect_args = {"charset": "utf8mb4"}
        # 远程数据库连接池调优：预检 + 回收，规避 8 小时空闲断连
        engine_kwargs.update(
            pool_size=10,
            max_overflow=20,
            pool_recycle=3600,
            pool_pre_ping=True,
        )
    elif scheme == "postgresql":
        engine_kwargs.update(
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
            pool_pre_ping=True,
        )

    return create_engine(settings.DATABASE_URL, connect_args=connect_args, **engine_kwargs)


engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# 模式自愈：补齐模型声明但数据库缺失的列
# ---------------------------------------------------------------------------
def _safe_add_column(conn, table_name, column, dialect):
    """向已存在表追加单列，跨方言构造 DDL 并容忍已存在/不支持。

    不依赖 inspector 的 batch_alter_table，直接用文本 DDL，兼容 SQLite/MySQL/PG。
    仅做「列不存在时添加」，存在则跳过；遇到任何异常记录后继续，不中断启动。
    """
    from sqlalchemy import text
    try:
        sqltype = str(column.type.compile(dialect=dialect))
        # SQLite 不支持 AFTER，其他方言忽略列位置即可；统一不加 AFTER
        col_default = ""
        if column.default is not None and column.default.arg is not None:
            arg = column.default.arg
            if isinstance(arg, bool):
                col_default = f" DEFAULT {'1' if arg else '0'}"
            elif isinstance(arg, (int, float)):
                col_default = f" DEFAULT {arg}"
            elif isinstance(arg, str):
                col_default = f" DEFAULT '{arg}'"
        nullable = "" if column.nullable else " NOT NULL"
        stmt = text(
            f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {sqltype}{col_default}{nullable}'
        )
        conn.execute(stmt)
        conn.commit()
        logger.info(f"  自愈补列: {table_name}.{column.name} {sqltype}")
        return True
    except Exception as e:  # noqa: BLE001
        # 列已存在（重复添加）或其他错误：仅记录，不中断
        logger.debug(f"  补列跳过 {table_name}.{column.name}: {e}")
        # 回滚可能因 ALTER 失败而开启的事务
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def sync_schema_with_models():
    """启动期模式自愈：检测并补齐 ORM 模型声明、但数据库缺失的列。

    背景：生产曾出现 alembic_version 已 stamp 到 head、但 users 表实际缺少
    notification_settings 列，导致任意 User 查询抛 OperationalError。原因是
    历史上某次 create_all 回退建表后 stamp("head")，跳过了真正的迁移。
    此函数在 alembic upgrade 之后兜底，按列级别对齐，保证「代码声明 → DB 必有列」。

    仅追加缺失列，不删除多余列、不修改已有列类型，安全可重复。
    """
    from sqlalchemy import inspect
    try:
        inspector = inspect(engine)
        conn = engine.connect()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"模式自愈：连接数据库失败，跳过: {e}")
        return
    try:
        dialect = engine.dialect
        existing_tables = set(inspector.get_table_names())
        added = 0
        for mapper in Base.registry.mappers:
            table = mapper.local_table
            table_name = table.name
            if table_name not in existing_tables:
                continue  # 表不存在交由 create_all 处理
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                if _safe_add_column(conn, table_name, column, dialect):
                    added += 1
        if added:
            logger.info(f"模式自愈完成：共补齐 {added} 个缺失列")
    finally:
        conn.close()
