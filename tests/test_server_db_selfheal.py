# -*- coding: utf-8 -*-
"""模式自愈 sync_schema_with_models 单元测试。

复现生产故障：alembic_version 已 stamp 到 head，但 users 表实际缺列
（如 notification_settings），User 查询抛 OperationalError。验证自愈函数
能补齐模型声明但 DB 缺失的列，使启动即可恢复。

为避免与 app.core.config 的 .env/绝对路径耦合，本测试直接在独立 SQLAlchemy
Base 上复现自愈逻辑，校验 _safe_add_column + 按列对齐的行为正确性。
"""
import unittest

try:
    import sqlalchemy
    from sqlalchemy import create_engine, inspect, Column, Integer, Text, String
    from sqlalchemy.orm import declarative_base
    _HAS_SA = True
except ImportError:
    _HAS_SA = False


def _safe_add_column(conn, table_name, column, dialect):
    """与 server/app/core/database.py 中 _safe_add_column 完全一致，便于单测。

    之所以复制实现而非导入：源模块在 import 期即构建 engine 并读取 settings/.env，
    在测试环境难以干净地注入目标 DATABASE_URL；而自愈逻辑是纯 DDL，复制实现可
    保证测试与生产代码行为一致（如需变更，两处同步）。
    """
    from sqlalchemy import text
    try:
        sqltype = str(column.type.compile(dialect=dialect))
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
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def sync_schema_with_models(engine, Base):
    """与生产 sync_schema_with_models 同构的自愈实现，参数化 engine/Base。"""
    inspector = inspect(engine)
    conn = engine.connect()
    try:
        dialect = engine.dialect
        existing_tables = set(inspector.get_table_names())
        added = 0
        for mapper in Base.registry.mappers:
            table = mapper.local_table
            table_name = table.name
            if table_name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                if _safe_add_column(conn, table_name, column, dialect):
                    added += 1
        return added
    finally:
        conn.close()


@unittest.skipUnless(_HAS_SA, "sqlalchemy 未安装，跳过")
class TestSyncSchemaSelfHeal(unittest.TestCase):

    def _build_env(self):
        """构造一个最小模型：users 表（生产模型的子集）+ 一个无关表 items。"""
        Base = declarative_base()

        class User(Base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)
            username = Column(String(50))
            # notification_settings 是本测试关注的「模型声明但 DB 缺失」列
            notification_settings = Column(Text, nullable=True)

        class Item(Base):
            __tablename__ = "items"
            id = Column(Integer, primary_key=True)
            name = Column(String(50))

        return Base, User, Item

    def test_adds_missing_column(self):
        Base, User, Item = self._build_env()
        engine = create_engine("sqlite:///:memory:")
        # 仅创建「缺 notification_settings 列」的 users（手动建表）+ 完整 items
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50))'))
            conn.execute(text('CREATE TABLE items (id INTEGER PRIMARY KEY, name VARCHAR(50))'))
            conn.commit()

        added = sync_schema_with_models(engine, Base)
        self.assertGreaterEqual(added, 1)
        cols = {c["name"] for c in inspect(engine).get_columns("users")}
        self.assertIn("notification_settings", cols)

    def test_idempotent_when_column_exists(self):
        Base, User, Item = self._build_env()
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)  # 列已存在
        added = sync_schema_with_models(engine, Base)
        self.assertEqual(added, 0)  # 无需补列

    def test_skips_missing_table(self):
        Base, User, Item = self._build_env()
        engine = create_engine("sqlite:///:memory:")
        # 只建 items，不建 users -> users 表缺失应跳过（交由 create_all）
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text('CREATE TABLE items (id INTEGER PRIMARY KEY, name VARCHAR(50))'))
            conn.commit()
        added = sync_schema_with_models(engine, Base)
        self.assertEqual(added, 0)


if __name__ == "__main__":
    unittest.main()
