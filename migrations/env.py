from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import DatabaseSettings
from app.core.database import Base
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.contact import models as contact_models  # noqa: F401
from app.modules.media import models as media_models  # noqa: F401
from app.modules.projects import models  # noqa: F401

settings = DatabaseSettings()
url = (settings.migration_database_url or settings.database_url).get_secret_value()
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(
        url, poolclass=pool.NullPool, hide_parameters=True, connect_args={"connect_timeout": 5}
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
