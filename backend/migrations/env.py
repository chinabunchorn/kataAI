import sys

from alembic import context
from sqlalchemy import create_engine, pool

from app.database_config import database_url


try:
    url = database_url()
except ValueError as exc:
    sys.exit(str(exc))


def migrate(connection):
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=url, target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get('connection') is not None:
    migrate(context.config.attributes['connection'])
else:
    # Do not let DBAPI or SQLAlchemy errors expose connection details.
    try:
        engine = create_engine(url, poolclass=pool.NullPool, hide_parameters=True)
        with engine.connect() as connection:
            migrate(connection)
        engine.dispose()
    except Exception:
        sys.exit('Migration failed; check database availability and migration state.')
