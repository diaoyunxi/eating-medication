"""为 users 表增加二哈人脸识别 ID 字段

支持多老人场景：家属在网页录入老人人脸后，将二哈摄像头返回的人脸 ID
回填到 users.husky_face_id，老人端服药拍照前据此核验当前人脸是否为该老人。

Revision ID: 20260812_003
Revises: 20260812_002
Create Date: 2026-08-12
"""
from alembic import op
import sqlalchemy as sa

# 修订版本标识
revision = "20260812_003"
down_revision = "20260812_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users 表增加二哈人脸识别 ID 列（可为空，未录入人脸的老人为 NULL）
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "husky_face_id",
                sa.Integer(),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("husky_face_id")
