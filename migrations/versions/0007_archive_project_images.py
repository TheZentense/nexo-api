"""Permite retirar imágenes sin borrar sus originales ni historial."""

import sqlalchemy as sa
from alembic import op

revision = "0007_archive_project_images"
down_revision = "0006_project_images"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("project_images", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.execute("""
        CREATE OR REPLACE FUNCTION audit.capture_image_change() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            previous jsonb;
            following jsonb;
            fields text[] := ARRAY['id','project_id','status','size_bytes','error_code','created_at','position','is_cover','alt_text','archived_at'];
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
                   TG_OP,CASE WHEN TG_OP = 'UPDATE' AND previous->>'archived_at' IS NULL
                       AND following->>'archived_at' IS NOT NULL THEN 'archived'
                       ELSE lower(TG_OP) END,previous,following);
            RETURN NULL;
        END;
        $$;
    """)


def downgrade():
    raise RuntimeError("Destructive rollback is disabled; use a corrective migration.")
