"""add github oauth fields to users table

GitHub OAuth 登录支持：新增 github_id（唯一索引）与 oauth_provider 字段；
并将 hashed_password 改为可空，以兼容通过 OAuth 注册、未设置密码的用户。

Revision ID: 20260722_001
Revises: 20260709_002
Create Date: 2026-07-22 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260722_001'
down_revision = '20260709_002'
branch_labels = None
depends_on = None


def upgrade():
    """升级：新增 GitHub OAuth 关联字段，hashed_password 允许为空"""
    op.add_column('users', sa.Column('github_id', sa.Integer(), nullable=True))
    op.create_index('ix_users_github_id', 'users', ['github_id'], unique=True)
    op.add_column('users', sa.Column('oauth_provider', sa.String(length=20), nullable=True))
    # OAuth 用户可不设密码
    op.alter_column('users', 'hashed_password',
                    existing_type=sa.String(),
                    nullable=True)


def downgrade():
    """回滚：删除 GitHub OAuth 字段，恢复 hashed_password 非空"""
    op.alter_column('users', 'hashed_password',
                    existing_type=sa.String(),
                    nullable=False)
    op.drop_column('users', 'oauth_provider')
    op.drop_index('ix_users_github_id', table_name='users')
    op.drop_column('users', 'github_id')
