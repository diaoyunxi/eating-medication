# -*- coding: utf-8 -*-
"""新增 Gitee OAuth 绑定字段与邮箱字段

Revision ID: 20260723_001
Revises: 20260722_001
Create Date: 2026-07-23

新增内容：
- users.gitee_id：Gitee 唯一 ID（唯一索引，与 github_id 对称）
- users.email ：第三方 OAuth 返回的邮箱（如 Gitee 已授权 emails 权限），本地注册为 NULL
"""
from alembic import op
import sqlalchemy as sa

# 修订版本标识
revision = "20260723_001"
down_revision = "20260722_001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("gitee_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_users_gitee_id", "gitee_id", unique=True)
        batch_op.add_column(sa.Column("email", sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("email")
        batch_op.drop_index("ix_users_gitee_id")
        batch_op.drop_column("gitee_id")
