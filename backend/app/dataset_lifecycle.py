"""Logical dataset deletion; retained files are never inspected or changed.

HTTP upload publishers cooperate using the shared root admission lock. Direct
internal publishers need not hold it, so only active, ready rows are eligible;
this is not a synchronization guarantee for out-of-band code.
"""
import os
from uuid import UUID

import sqlalchemy as sa

from .dataset_upload_api import _acquire


class DatasetDeletionNotFound(Exception):
    pass


class DatasetDeletionConflict(Exception):
    pass


def delete_dataset(runtime, dataset_id: UUID):
    """Tombstone on a dedicated connection; errors never imply rollback certainty."""
    fd = _acquire(runtime.root)
    try:
        with runtime.connection() as connection:
            connection.execute(sa.text('SELECT pg_advisory_xact_lock(1262571873, 3)'))
            row = connection.execute(sa.text(
                'SELECT lifecycle, publication_state FROM datasets WHERE id=:id FOR UPDATE'
            ), {'id': dataset_id}).one_or_none()
            if row is None:
                raise DatasetDeletionNotFound()
            if row.lifecycle == 'deleted':
                return
            if row.lifecycle != 'active' or row.publication_state != 'ready':
                raise DatasetDeletionConflict()
            busy = connection.execute(sa.text(
                "SELECT EXISTS (SELECT 1 FROM request_intents WHERE dataset_id=:id "
                "AND status NOT IN ('cancelled', 'fake_completed'))"
            ), {'id': dataset_id}).scalar_one()
            if busy:
                raise DatasetDeletionConflict()
            connection.execute(sa.text(
                "UPDATE datasets SET lifecycle='deleted', deleted_at=clock_timestamp() WHERE id=:id"
            ), {'id': dataset_id})
            connection.commit()
    finally:
        os.close(fd)
