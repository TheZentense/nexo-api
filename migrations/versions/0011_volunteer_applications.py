"""Guarda solicitudes de voluntariado y audita sus cambios de estado."""

import sqlalchemy as sa
from alembic import op

revision = "0011_volunteer_applications"
down_revision = "0010_handle_contact_messages"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "volunteer_applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("area", sa.String(20), nullable=False),
        sa.Column("message", sa.String(2000), server_default="", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_volunteer_applications"),
        sa.CheckConstraint(
            "area IN ('education','health','environment')",
            name=op.f("ck_volunteer_applications_area_values"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','accepted','rejected')",
            name=op.f("ck_volunteer_applications_status_values"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_volunteer_applications_version_positive")),
    )
    op.create_index(
        "ix_volunteer_applications_created_at_id", "volunteer_applications", ["created_at", "id"]
    )
    op.execute("""
        CREATE FUNCTION audit.capture_volunteer_status() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            INSERT INTO audit.events(actor_id,request_id,database_user,table_name,
                                     record_id,operation,action,before_data,after_data)
            VALUES(nullif(current_setting('app.actor_id',true),'')::uuid,
                   nullif(current_setting('app.request_id',true),'')::uuid,
                   session_user,TG_TABLE_NAME,NEW.id,TG_OP,'status_changed',
                   jsonb_build_object('id',OLD.id,'status',OLD.status,'version',OLD.version,'updated_at',OLD.updated_at),
                   jsonb_build_object('id',NEW.id,'status',NEW.status,'version',NEW.version,'updated_at',NEW.updated_at));
            RETURN NULL;
        END;
        $$;
        REVOKE ALL ON FUNCTION audit.capture_volunteer_status() FROM PUBLIC;
        CREATE TRIGGER audit_volunteer_status AFTER UPDATE ON volunteer_applications
            FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
            EXECUTE FUNCTION audit.capture_volunteer_status();
    """)


def downgrade():
    raise RuntimeError("Destructive rollback is disabled; use a corrective migration.")
