"""add device_token column to users table

在 users 表新增 device_token 字段，
用于设备端点访问鉴权（X-Device-Token 头校验），防止仅凭 device_id 即可访问设备数据。

Revision ID: 20260709_001
Revises: 20260708_001
Create Date: 2026-07-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260709_001'
down_revision = '20260708_001'
branch_labels = None
depends_on = None


def upgrade():
    """升级：新增 device_token 字段（nullable, index）"""
    op.add_column(
        'users',
        sa.Column('device_token', sa.String(length=64), nullable=True),
    )
    op.create_index('ix_users_device_token', 'users', ['device_token'])


def downgrade():
    """回滚：删除 device_token 字段"""
    op.drop_index('ix_users_device_token', table_name='users')
    op.drop_column('users', 'device_token')
