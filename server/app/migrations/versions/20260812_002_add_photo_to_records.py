"""用药记录关联照片字段

Revision ID: 20260812_002
Revises: 20260812_001
Create Date: 2026-08-12
"""
from alembic import op
import sqlalchemy as sa

# 修订版本标识
revision = "20260812_002"
down_revision = "20260812_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # medication_records 表增加服药照片相对路径列（可为空）
    with op.batch_alter_table("medication_records") as batch_op:
        batch_op.add_column(
            sa.Column(
                "photo",
                sa.String(512),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("medication_records") as batch_op:
        batch_op.drop_column("photo")
