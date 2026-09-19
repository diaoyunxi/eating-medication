"""手机号登录改造：phone 唯一必填、username 改昵称、删除 full_name

Revision ID: 20260724_001
Revises: 20260723_001
Create Date: 2026-07-24

变更说明（issue #3：登陆方式变更）：
- phone 设为登录唯一标识：加唯一索引 ix_users_phone，长度 20，保持可空
  （兼容邮箱验证码自动注册产生的 phone=None 账号）
- username 改为昵称（展示名）：去除唯一约束、允许为空、长度扩到 50
- 删除 full_name 列（昵称统一使用 username）
"""
from alembic import op
import sqlalchemy as sa


revision = "20260724_001"
down_revision = "20260723_001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        # 1. 删除 full_name 列
        batch_op.drop_column("full_name")
        # 2. username 改昵称：先删唯一索引，再放宽约束、扩长度
        batch_op.drop_index("ix_users_username")
        batch_op.alter_column(
            "username",
            existing_type=sa.String(length=20),
            type_=sa.String(length=50),
            nullable=True,
            existing_nullable=False,
        )
        # 3. phone 设为唯一登录标识
        batch_op.alter_column(
            "phone",
            existing_type=sa.String(),
            type_=sa.String(length=20),
            nullable=True,
            existing_nullable=True,
        )
        batch_op.create_index("ix_users_phone", "phone", unique=True)


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_phone")
        batch_op.alter_column(
            "phone",
            existing_type=sa.String(length=20),
            type_=sa.String(),
            nullable=True,
            existing_nullable=True,
        )
        batch_op.alter_column(
            "username",
            existing_type=sa.String(length=50),
            type_=sa.String(length=20),
            nullable=False,
            existing_nullable=True,
        )
        batch_op.create_index("ix_users_username", "username", unique=True)
        batch_op.add_column(sa.Column("full_name", sa.String(), nullable=False))
