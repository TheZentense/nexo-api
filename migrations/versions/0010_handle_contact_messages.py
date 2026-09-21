"""Registra la atención de mensajes sin cambiar su contenido."""

import sqlalchemy as sa
from alembic import op

revision = "0010_handle_contact_messages"
down_revision = "0009_contact_messages"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("contact_messages", sa.Column("handled_at", sa.DateTime(timezone=True)))
    op.execute("""
        CREATE FUNCTION audit.capture_contact_handling() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
            INSERT INTO audit.events(actor_id,request_id,database_user,table_name,
                                     record_id,operation,action,before_data,after_data)
            VALUES(nullif(current_setting('app.actor_id',true),'')::uuid,
                   nullif(current_setting('app.request_id',true),'')::uuid,
                   session_user,TG_TABLE_NAME,NEW.id,TG_OP,'handled',
                   jsonb_build_object('id',OLD.id,'handled_at',OLD.handled_at),
                   jsonb_build_object('id',NEW.id,'handled_at',NEW.handled_at));
            RETURN NULL;
        END;
        $$;
        REVOKE ALL ON FUNCTION audit.capture_contact_handling() FROM PUBLIC;
        CREATE TRIGGER audit_contact_handling AFTER UPDATE ON contact_messages
            FOR EACH ROW WHEN (OLD.handled_at IS DISTINCT FROM NEW.handled_at)
            EXECUTE FUNCTION audit.capture_contact_handling();
    """)


def downgrade():
    raise RuntimeError("Destructive rollback is disabled; use a corrective migration.")
