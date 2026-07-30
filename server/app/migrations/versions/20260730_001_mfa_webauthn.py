"""MFA(TOTP) + WebAuthn/Passkey 支持

Revision ID: 20260730_001
Revises: 20260724_001
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

# 修订版本标识
revision = "20260730_001"
down_revision = "20260724_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) users 表增加 TOTP 相关列（SQLite 需 batch）
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("totp_secret", sa.String(255), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "mfa_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("backup_codes", sa.Text(), nullable=True))

    # 2) 新建 WebAuthn 凭证表
    op.create_table(
        "webauthn_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credential_id", sa.String(512), nullable=False, unique=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column(
            "sign_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("transports", sa.Text(), nullable=True),
        sa.Column("nickname", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_webauthn_credentials_user_id", "webauthn_credentials", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_webauthn_credentials_user_id", table_name="webauthn_credentials")
    op.drop_table("webauthn_credentials")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("backup_codes")
        batch_op.drop_column("mfa_enabled")
        batch_op.drop_column("totp_secret")
