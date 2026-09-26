"""drop pending_learn from users

移除 users 表的 pending_learn 字段。人脸录入改为「用户自行在二哈录入后于网页填写人脸ID」，
不再需要待录入标记及设备端轮询学习流程，故删除该字段。

Revision ID: 20260812_005
Revises: 20260812_004
Create Date: 2026-08-13 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "20260812_005"
down_revision = "20260812_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 仅当字段存在时删除，兼容测试用 SQLite（通过 create_all 建表、未执行本迁移）
    bind = op.get_bind()
    cols = [row[1] for row in bind.execute(sa.text("PRAGMA table_info(users)")).fetchall()]
    if "pending_learn" in cols:
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("pending_learn")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("pending_learn", sa.Boolean(), nullable=False, server_default=sa.false())
        )
