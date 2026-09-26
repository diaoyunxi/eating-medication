"""用药记录未确认升级通知去重标志

Revision ID: 20260812_001
Revises: 20260809_001
Create Date: 2026-08-12
"""
from alembic import op
import sqlalchemy as sa

# 修订版本标识
revision = "20260812_001"
down_revision = "20260809_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # medication_records 表增加未确认升级通知去重标志列
    with op.batch_alter_table("medication_records") as batch_op:
        batch_op.add_column(
            sa.Column(
                "notified_unconfirmed_1m",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "notified_unconfirmed_3m",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("medication_records") as batch_op:
        batch_op.drop_column("notified_unconfirmed_3m")
        batch_op.drop_column("notified_unconfirmed_1m")
