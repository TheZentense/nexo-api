"""Agrega imágenes y galería sin cambiar los videos existentes."""

import sqlalchemy as sa
from alembic import op

revision = "0006_project_images"
down_revision = "0005_project_videos"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_images",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("original_key", sa.String(300), nullable=False, unique=True),
        sa.Column("variants", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_cover", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("alt_text", sa.String(250), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(40)),
        sa.Column("attempt_id", sa.Uuid()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending','processing','ready','failed')", name="status_values"
        ),
        sa.CheckConstraint("size_bytes > 0", name="size_positive"),
        sa.CheckConstraint("position >= 0", name="position_nonnegative"),
    )
    op.create_index("ix_project_images_project_id", "project_images", ["project_id"])
    op.create_index("ix_project_images_status", "project_images", ["status"])
    op.create_index(
        "uq_project_images_cover",
        "project_images",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("is_cover"),
    )
    op.execute("""
        CREATE FUNCTION audit.capture_image_change() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            previous jsonb;
            following jsonb;
            fields text[] := ARRAY['id','project_id','status','size_bytes','error_code','created_at','position','is_cover','alt_text'];
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                SELECT jsonb_object_agg(key,value) INTO previous
                    FROM jsonb_each(to_jsonb(OLD)) WHERE key = ANY(fields);
            END IF;
            IF TG_OP <> 'DELETE' THEN
                SELECT jsonb_object_agg(key,value) INTO following
                    FROM jsonb_each(to_jsonb(NEW)) WHERE key = ANY(fields);
            END IF;
            INSERT INTO audit.events(actor_id,request_id,database_user,table_name,
                                     record_id,operation,action,before_data,after_data)
            VALUES(nullif(current_setting('app.actor_id',true),'')::uuid,
                   nullif(current_setting('app.request_id',true),'')::uuid,
                   session_user,TG_TABLE_NAME,coalesce(following->>'id',previous->>'id')::uuid,
                   TG_OP,lower(TG_OP),previous,following);
            RETURN NULL;
        END;
        $$;
        REVOKE ALL ON FUNCTION audit.capture_image_change() FROM PUBLIC;
        CREATE TRIGGER project_images_audit AFTER INSERT OR UPDATE OR DELETE ON public.project_images
            FOR EACH ROW EXECUTE FUNCTION audit.capture_image_change();
    """)


def downgrade():
    raise RuntimeError("Destructive rollback is disabled; use a corrective migration.")
