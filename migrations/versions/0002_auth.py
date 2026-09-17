"""Agrega las cuentas de administrador y sus sesiones."""

import sqlalchemy as sa
from alembic import op

revision = "0002_auth"
down_revision = "0001_projects"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_admin_users_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_users")),
        sa.UniqueConstraint("email", name=op.f("uq_admin_users_email")),
    )
    op.create_table(
        "auth_rate_limits",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_auth_rate_limits")),
    )
    op.create_index(
        op.f("ix_auth_rate_limits_expires_at"), "auth_rate_limits", ["expires_at"], unique=False
    )
    op.create_table(
        "admin_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("admin_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_users.id"],
            name=op.f("fk_admin_sessions_admin_id_admin_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_admin_sessions")),
    )
    op.create_index(
        op.f("ix_admin_sessions_admin_id"), "admin_sessions", ["admin_id"], unique=False
    )
    op.create_index(
        op.f("ix_admin_sessions_expires_at"), "admin_sessions", ["expires_at"], unique=False
    )


def downgrade():
    raise RuntimeError("Destructive rollback is disabled; use a corrective migration.")
