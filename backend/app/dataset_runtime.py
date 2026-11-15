"""Explicit, local-only dataset configuration; no work is performed at import."""
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from .database_config import database_url


@dataclass(frozen=True)
class DatasetRuntime:
    url: URL = field(repr=False)
    root: Path = field(repr=False)

    @property
    def engine(self):
        """Return a new unconnected engine; caller owns disposal."""
        return sa.create_engine(self.url, poolclass=NullPool, hide_parameters=True,
                                connect_args={'connect_timeout': 5})

    @contextmanager
    def connection(self):
        """Create and dispose a non-pooled engine for this trusted runtime."""
        engine = self.engine
        try:
            with engine.connect() as connection:
                yield connection
        finally:
            engine.dispose()


def load_dataset_runtime() -> DatasetRuntime:
    """Validate explicit local database and an existing private directory."""
    try:
        url = database_url()
        if url.host is not None and url.host not in ('127.0.0.1', '::1'):
            raise ValueError
        root_value = os.environ.get('KATAAI_DATASET_ROOT', '')
        if not root_value or not os.path.isabs(root_value):
            raise ValueError
        if not hasattr(os, 'O_DIRECTORY') or not hasattr(os, 'O_NOFOLLOW'):
            raise ValueError
        root_value = os.path.normpath(root_value)
        fd = os.open(root_value, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o7077:
                raise ValueError
        finally:
            os.close(fd)
        return DatasetRuntime(url, Path(root_value))
    except Exception:
        raise ValueError('DATASET_CONFIGURATION_ERROR') from None
