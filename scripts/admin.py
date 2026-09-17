"""Gestiona cuentas desde la terminal sin mostrar las contraseñas."""

import argparse
from getpass import getpass

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.core.config import DatabaseSettings
from app.modules.auth.models import AdminSession, AdminUser
from app.modules.auth.security import password_hasher


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "reset-password", "disable"])
    parser.add_argument("email")
    args = parser.parse_args()
    email = str(TypeAdapter(EmailStr).validate_python(args.email)).lower()
    settings = DatabaseSettings()
    if not settings.migration_database_url:
        raise SystemExit("Set MIGRATION_DATABASE_URL to manage accounts.")
    engine = create_engine(settings.migration_database_url.get_secret_value(), hide_parameters=True)
    try:
        with Session(engine) as db, db.begin():
            user = db.scalar(select(AdminUser).where(AdminUser.email == email).with_for_update())
            if args.action == "create" and user:
                raise SystemExit("The account already exists; no changes made.")
            if args.action != "create" and not user:
                raise SystemExit("Account not found.")
            if args.action == "disable":
                user.is_active = False
            else:
                password = getpass("Password (15 to 128 characters): ")
                if not 15 <= len(password) <= 128:
                    raise SystemExit("Password must contain 15 to 128 characters.")
                if password != getpass("Repeat password: "):
                    raise SystemExit("Passwords do not match.")
                encoded = password_hasher.hash(password)
                if user:
                    user.password_hash = encoded
                else:
                    user = AdminUser(email=email, password_hash=encoded)
                    db.add(user)
                    db.flush()
            db.execute(delete(AdminSession).where(AdminSession.admin_id == user.id))
        print("Done. Previous sessions have been revoked.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
