"""Read validated CSV headers from an explicitly selected local storage root.

The caller must authorize the dataset and select a READY record and its UUID key;
this module does not consult or lock the database. The root and its ancestors,
filesystem, and same-UID processes must be trusted. Root mode checks do not
inspect ACLs. A validated file is not proof of freshness or provenance: changes
by another writer, including during the read, cannot be ruled out by stat checks.
"""

import os
import stat
from uuid import UUID

from .csv_intake import CsvLimits, validate_csv


class DatasetColumnsUnavailable(Exception):
    """The selected dataset's columns could not safely be read."""

    def __init__(self):
        super().__init__('Dataset columns unavailable.')


def read_dataset_columns(root, key, limits=CsvLimits()):
    """Return only column names; reject inaccessible or invalid CSV as unavailable."""
    directory = fd = None
    result = None
    try:
        if (not isinstance(key, UUID) or not hasattr(os, 'O_DIRECTORY')
                or not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_NONBLOCK')
                or os.open not in os.supports_dir_fd):
            raise ValueError('Unsupported request')
        directory = os.open(os.path.normpath(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(directory)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o7077:
            raise ValueError('Invalid root')
        fd = os.open(str(key), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limits.max_bytes:
            raise ValueError('Invalid file')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            result = validate_csv(stream, limits).columns
    except Exception:
        result = None
    finally:
        for descriptor in (fd, directory):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    result = None
    if result is None:
        raise DatasetColumnsUnavailable() from None
    return result
