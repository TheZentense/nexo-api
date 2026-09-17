"""Evita que una edición antigua sobrescriba cambios recientes."""

import sqlalchemy as sa
from alembic import op

revision = "0003_project_version"
down_revision = "0002_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "projects", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION touch_project_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            NEW.version = OLD.version + 1;
            RETURN NEW;
        END;
        $$;
    """)


def downgrade():
    raise RuntimeError("Destructive rollback is disabled; use a corrective migration.")
