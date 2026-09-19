"""Guarda quién cambió los datos y qué cambió."""

from alembic import op

revision = "0004_database_audit"
down_revision = "0003_project_version"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE SCHEMA audit;
        REVOKE ALL ON SCHEMA audit FROM PUBLIC;
        CREATE TABLE audit.events (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            actor_id uuid,
            request_id uuid,
            database_user text NOT NULL,
            table_name text NOT NULL,
            record_id uuid NOT NULL,
            operation text NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
            action text NOT NULL,
            before_data jsonb,
            after_data jsonb
        );
        CREATE INDEX ix_audit_events_record ON audit.events(table_name, record_id, id);
        CREATE INDEX ix_audit_events_occurred_at ON audit.events(occurred_at);
        REVOKE ALL ON audit.events FROM PUBLIC;

        CREATE FUNCTION audit.capture_change() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        DECLARE
            previous jsonb;
            following jsonb;
            allowed_fields text[];
            actor uuid := nullif(current_setting('app.actor_id', true), '')::uuid;
            request_uuid uuid := nullif(current_setting('app.request_id', true), '')::uuid;
            event_action text := lower(TG_OP);
        BEGIN
            IF TG_OP <> 'INSERT' THEN previous := to_jsonb(OLD); END IF;
            IF TG_OP <> 'DELETE' THEN following := to_jsonb(NEW); END IF;

            IF TG_TABLE_NAME = 'projects' AND TG_OP = 'UPDATE'
               AND previous->>'status' IS DISTINCT FROM following->>'status' THEN
                event_action := following->>'status';
            END IF;

            IF TG_TABLE_NAME = 'admin_users' AND TG_OP = 'UPDATE'
               AND previous->>'password_hash' IS DISTINCT FROM following->>'password_hash' THEN
                event_action := 'credentials_changed';
            END IF;

            -- Los campos nuevos quedan fuera hasta que decidamos incluirlos.
            allowed_fields := CASE TG_TABLE_NAME
                WHEN 'projects' THEN ARRAY[
                    'id', 'title', 'slug', 'category_id', 'project_date',
                    'short_description', 'description', 'location',
                    'beneficiaries_count', 'progress_percent', 'status',
                    'version', 'created_at', 'updated_at'
                ]
                WHEN 'categories' THEN ARRAY['id', 'name', 'slug', 'created_at']
                WHEN 'admin_users' THEN ARRAY['id', 'is_active']
            END;
            SELECT jsonb_object_agg(key, value) INTO previous
                FROM jsonb_each(previous) WHERE key = ANY(allowed_fields);
            SELECT jsonb_object_agg(key, value) INTO following
                FROM jsonb_each(following) WHERE key = ANY(allowed_fields);

            INSERT INTO audit.events(actor_id, request_id, database_user, table_name,
                                     record_id, operation, action, before_data, after_data)
            VALUES(actor, request_uuid, session_user, TG_TABLE_NAME,
                   coalesce(following->>'id', previous->>'id')::uuid,
                   TG_OP, event_action, previous, following);
            RETURN NULL;
        END;
        $$;
        REVOKE ALL ON FUNCTION audit.capture_change() FROM PUBLIC;

        CREATE TRIGGER projects_audit AFTER INSERT OR UPDATE OR DELETE ON public.projects
            FOR EACH ROW EXECUTE FUNCTION audit.capture_change();
        CREATE TRIGGER categories_audit AFTER INSERT OR UPDATE OR DELETE ON public.categories
            FOR EACH ROW EXECUTE FUNCTION audit.capture_change();
        CREATE TRIGGER admin_users_audit AFTER INSERT OR UPDATE OR DELETE ON public.admin_users
            FOR EACH ROW EXECUTE FUNCTION audit.capture_change();

    """)


def downgrade():
    raise RuntimeError(
        "Destructive rollback is disabled; preserve audit history with a corrective migration."
    )
