"""为 users 表增加 pending_learn 待录入人脸标记

多老人场景下，家属在网页触发「录入人脸」后，由设备端轮询学习完成。
该标记用于在服务端记录「某老人正等待二哈摄像头学习人脸」的中间状态。

Revision ID: 20260812_004
Revises: 20260812_003
Create Date: 2026-08-12
"""
from alembic import op
import sqlalchemy as sa

# 修订版本标识
revision = "20260812_004"
down_revision = "20260812_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "pending_learn",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("pending_learn")
