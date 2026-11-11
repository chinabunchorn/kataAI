"""Explicit database configuration; never embed or print connection secrets."""
import os

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def database_url(value=None):
    # libpq can override even an explicit URL (notably via PGHOSTADDR or
    # PGSERVICE). Fail closed rather than silently dropping security settings.
    if any(name.startswith('PG') for name in os.environ):
        raise ValueError('Inherited PG environment variables are not supported.')
    value = os.environ.get('DATABASE_URL') if value is None else value
    try:
        url = make_url(value or '')
        socket = url.query.get('host')
        query_port = url.query.get('port')
        if (url.drivername not in ('postgresql', 'postgresql+psycopg')
                or not url.username or not url.database or '/' in url.database
                or set(url.query) - {'host', 'port'}
                or (socket is not None and (not isinstance(socket, str) or not socket.startswith('/')))
                or (socket is None and not url.host)
                or (socket is not None and url.host)
                or (query_port is not None and
                    (not isinstance(query_port, str) or not query_port.isdigit()
                     or not 0 < int(query_port) < 65536))
                or (url.port is not None and not 0 < url.port < 65536)):
            raise ValueError
        return url.set(drivername='postgresql+psycopg')
    except (ArgumentError, ValueError, TypeError):
        raise ValueError('DATABASE_URL must be an explicit valid PostgreSQL URL.') from None
