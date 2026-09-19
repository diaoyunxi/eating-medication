"""add device_id column to users table

新增 device_id 字段，关联真实老人用户与设备 ID（原"设备即用户"设计未区分账户与设备）。

Revision ID: 20260708_001
Revises:
Create Date: 2026-07-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260708_001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """升级：新增 device_id 字段（nullable, unique, index）"""
    op.add_column(
        'users',
        sa.Column('device_id', sa.String(), nullable=True),
    )
    op.create_index('ix_users_device_id', 'users', ['device_id'], unique=True)


def downgrade():
    """回滚：删除 device_id 字段"""
    op.drop_index('ix_users_device_id', table_name='users')
    op.drop_column('users', 'device_id')
