"""Create categories and projects without changing existing tables."""

import sqlalchemy as sa
from alembic import op

revision = "0001_projects"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.UniqueConstraint("name", name="uq_categories_name"),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(220), nullable=False),
        sa.Column("category_id", sa.Uuid()),
        sa.Column("project_date", sa.Date()),
        sa.Column("short_description", sa.String(500)),
        sa.Column("description", sa.Text()),
        sa.Column("location", sa.String(250)),
        sa.Column("beneficiaries_count", sa.Integer()),
        sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            ondelete="RESTRICT",
            name="fk_projects_category_id_categories",
        ),
        sa.CheckConstraint(
            "progress_percent BETWEEN 0 AND 100", name=op.f("ck_projects_progress_range")
        ),
        sa.CheckConstraint(
            "beneficiaries_count >= 0", name=op.f("ck_projects_beneficiaries_nonnegative")
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')", name=op.f("ck_projects_status_values")
        ),
    )
    op.create_index("ix_projects_category_id", "projects", ["category_id"])
    op.create_index("ix_projects_status_project_date", "projects", ["status", "project_date"])
    op.execute("""
        CREATE FUNCTION touch_project_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER projects_updated_at BEFORE UPDATE ON projects
        FOR EACH ROW EXECUTE FUNCTION touch_project_updated_at();
    """)


def downgrade():
    raise RuntimeError(
        "Reversión destructiva deshabilitada: crea una migración correctiva revisada."
    )
