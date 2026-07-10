"""add last_notified_at column to medication_plans table

S-05 修复：在 medication_plans 表新增 last_notified_at 字段，
用于低库存通知去重，每条计划每天最多通知一次，避免重复打扰。

Revision ID: 20260709_002
Revises: 20260709_001
Create Date: 2026-07-09 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260709_002'
down_revision = '20260709_001'
branch_labels = None
depends_on = None


def upgrade():
    """升级：新增 last_notified_at 字段（nullable）"""
    op.add_column(
        'medication_plans',
        sa.Column('last_notified_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    """回滚：删除 last_notified_at 字段"""
    op.drop_column('medication_plans', 'last_notified_at')
