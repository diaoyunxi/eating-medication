"""用户通知偏好设置（notification_settings）

Revision ID: 20260809_001
Revises: 20260807_001
Create Date: 2026-08-09
"""
from alembic import op
import sqlalchemy as sa

# 修订版本标识
revision = "20260809_001"
down_revision = "20260807_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users 表增加 notification_settings 列（SQLite 需 batch）
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("notification_settings", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("notification_settings")
