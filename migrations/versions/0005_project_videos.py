"""Agrega videos sin tocar proyectos ni historial existentes."""

import sqlalchemy as sa
from alembic import op

revision = "0005_project_videos"
down_revision = "0004_database_audit"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_videos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("original_key", sa.String(300), nullable=False, unique=True),
        sa.Column("video_key", sa.String(300)),
        sa.Column("poster_key", sa.String(300)),
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
    )
    op.create_index("ix_project_videos_project_id", "project_videos", ["project_id"])
    op.create_index("ix_project_videos_status", "project_videos", ["status"])
    op.execute("""
        CREATE FUNCTION audit.capture_video_change() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            previous jsonb;
            following jsonb;
            fields text[] := ARRAY['id','project_id','status','size_bytes','error_code','created_at'];
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
        REVOKE ALL ON FUNCTION audit.capture_video_change() FROM PUBLIC;
        CREATE TRIGGER project_videos_audit AFTER INSERT OR UPDATE OR DELETE ON public.project_videos
            FOR EACH ROW EXECUTE FUNCTION audit.capture_video_change();
    """)


def downgrade():
    raise RuntimeError("Destructive rollback is disabled; use a corrective migration.")
