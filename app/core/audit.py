from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session


def set_audit_context(db: Session, actor_id: UUID):
    """El administrador se guarda solo durante esta transacción."""
    db.execute(
        text(
            "SELECT set_config('app.actor_id', :actor, true), "
            "set_config('app.request_id', :request_id, true)"
        ),
        {"actor": str(actor_id), "request_id": str(uuid4())},
    )
