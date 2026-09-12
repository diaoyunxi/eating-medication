"""add device_bind_code column to users table

新增 device_bind_code 字段：老人端屏幕展示的 6 位绑定码，
家属绑定设备时须提供以证明实际占有，防止仅凭 MAC 派生的
device_id 即可越权绑定。

Revision ID: 20260912_001
Revises: 20260812_001_add_unconfirmed_notify_flags
Create Date: 2026-09-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260912_001'
down_revision = '20260812_001_add_unconfirmed_notify_flags'
branch_labels = None
depends_on = None


def upgrade():
    """升级：新增 device_bind_code 字段（nullable）"""
    op.add_column(
        'users',
        sa.Column('device_bind_code', sa.String(length=16), nullable=True),
    )


def downgrade():
    """回滚：删除 device_bind_code 字段"""
    op.drop_column('users', 'device_bind_code')
