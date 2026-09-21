"""Guarda los mensajes recibidos desde contacto."""

import sqlalchemy as sa
from alembic import op

revision = "0009_contact_messages"
down_revision = "0008_archive_project_videos"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contact_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("message", sa.String(5000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_contact_messages"),
    )


def downgrade():
    raise RuntimeError("Destructive rollback is disabled; use a corrective migration.")
