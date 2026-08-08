"""用药计划增加药品编号/条形码字段（product_code）

Revision ID: 20260807_001
Revises: 20260730_001
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

# 修订版本标识
revision = "20260807_001"
down_revision = "20260730_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # medication_plans 表增加可选 product_code 列（药品编号/条形码）
    # 用于老人端扫码识别：家属端录入编号与名称/剂量，老人端扫码后按编号匹配
    with op.batch_alter_table("medication_plans") as batch_op:
        batch_op.add_column(
            sa.Column("product_code", sa.String(64), nullable=True)
        )
        batch_op.create_index(
            "ix_medication_plans_product_code", ["product_code"]
        )


def downgrade() -> None:
    with op.batch_alter_table("medication_plans") as batch_op:
        batch_op.drop_index("ix_medication_plans_product_code")
        batch_op.drop_column("product_code")
