"""Transactional PostgreSQL request queue.

Callers own commit/rollback. Per-client advisory locks last until transaction end;
keep transactions short. Recovery additionally requires the worker session lock.
"""
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from .dataset_store import DatasetNotFound
from .ready_dataset import DatasetUnavailable


class InvalidRequest(ValueError):
    def __init__(self):
        super().__init__('INVALID_REQUEST')


class IdempotencyConflict(Exception):
    def __init__(self):
        super().__init__('IDEMPOTENCY_CONFLICT')


class RequestStorageError(Exception):
    def __init__(self):
        super().__init__('REQUEST_STORAGE_ERROR')


@dataclass(frozen=True)
class RequestRecord:
    id: UUID
    client_request_id: UUID
    dataset_id: UUID
    question: str = field(repr=False)
    status: str
    claim_token: UUID | None
    created_at: datetime
    updated_at: datetime


_COLUMNS = 'id, client_request_id, dataset_id, question, status, claim_token, created_at, updated_at'


class RequestQueue:
    def __init__(self, connection):
        self._connection = connection

    def get(self, request_id):
        if not isinstance(request_id, UUID):
            raise InvalidRequest()
        try:
            row = self._connection.execute(sa.text(
                f'SELECT {_COLUMNS} FROM request_intents WHERE id = :id AND hidden_at IS NULL'),
                {'id': request_id}).one_or_none()
            return RequestRecord(*row) if row is not None else None
        except SQLAlchemyError:
            raise RequestStorageError() from None

    def history(self, limit, before=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise InvalidRequest()
        if before is not None and (not isinstance(before, tuple) or len(before) != 2
                                   or not isinstance(before[0], datetime) or before[0].utcoffset() is None
                                   or not isinstance(before[1], UUID)):
            raise InvalidRequest()
        try:
            cursor = ' AND (created_at, id) < (:created_at, :cursor_id)' if before else ''
            params: dict[str, object] = {'limit': limit}
            if before:
                params.update(created_at=before[0], cursor_id=before[1])
            rows = self._connection.execute(sa.text(
                f'SELECT {_COLUMNS} FROM request_intents WHERE hidden_at IS NULL{cursor} '
                'ORDER BY created_at DESC, id DESC LIMIT :limit'), params)
            return [RequestRecord(*row) for row in rows]
        except SQLAlchemyError:
            raise RequestStorageError() from None

    def cancel(self, request_id):
        """Cancel queued work or request cooperative cancellation; return current row.

        Terminal and unknown records are unchanged. The caller commits. Row-level
        update locking linearizes this operation against claim and finish.
        """
        if not isinstance(request_id, UUID):
            raise InvalidRequest()
        try:
            row = self._connection.execute(sa.text(
                "UPDATE request_intents SET status=CASE status WHEN 'queued' THEN 'cancelled' "
                "WHEN 'running' THEN 'cancel_requested' ELSE status END, "
                "updated_at=CASE WHEN status IN ('queued','running') THEN clock_timestamp() ELSE updated_at END "
                f'WHERE id=:id AND hidden_at IS NULL RETURNING {_COLUMNS}'), {'id': request_id}).one_or_none()
            return RequestRecord(*row) if row is not None else None
        except SQLAlchemyError:
            raise RequestStorageError() from None

    def hide_history(self, request_id):
        if not isinstance(request_id, UUID):
            raise InvalidRequest()
        try:
            row = self._connection.execute(sa.text(
                "UPDATE request_intents SET hidden_at=CASE WHEN status IN ('cancelled','fake_completed') "
                "THEN clock_timestamp() ELSE hidden_at END "
                f'WHERE id=:id AND hidden_at IS NULL RETURNING {_COLUMNS}'),
                {'id': request_id}).one_or_none()
            return RequestRecord(*row) if row is not None else None
        except SQLAlchemyError:
            raise RequestStorageError() from None

    def claim_next(self, token):
        if not isinstance(token, UUID):
            raise InvalidRequest()
        try:
            # Serialize claimers even if they do not share the worker session lock.
            self._connection.execute(sa.text('SELECT pg_advisory_xact_lock(1262571873, 3)'))
            row = self._connection.execute(sa.text(
                "UPDATE request_intents SET status='running', claim_token=:token, updated_at=clock_timestamp() "
                "WHERE id = (SELECT id FROM request_intents WHERE status='queued' "
                "AND NOT EXISTS (SELECT 1 FROM request_intents WHERE status IN ('running','cancel_requested')) "
                'ORDER BY created_at, id LIMIT 1 FOR UPDATE) '
                f'RETURNING {_COLUMNS}'), {'token': token}).one_or_none()
            return RequestRecord(*row) if row is not None else None
        except SQLAlchemyError:
            raise RequestStorageError() from None

    def complete_fake(self, request_id, token):
        if not isinstance(request_id, UUID) or not isinstance(token, UUID):
            raise InvalidRequest()
        try:
            row = self._connection.execute(sa.text(
                "UPDATE request_intents SET status=CASE WHEN status='cancel_requested' THEN 'cancelled' "
                "ELSE 'fake_completed' END, claim_token=NULL, updated_at=clock_timestamp() "
                "WHERE id=:id AND status IN ('running','cancel_requested') AND claim_token=:token RETURNING status"),
                {'id': request_id, 'token': token}).one_or_none()
            return row[0] if row is not None else False
        except SQLAlchemyError:
            raise RequestStorageError() from None

    def mark_unknown_running(self):
        """Caller must hold the exclusive worker session lock throughout recovery."""
        try:
            result = self._connection.execute(sa.text(
                "UPDATE request_intents SET status='unknown', claim_token=NULL, updated_at=clock_timestamp() "
                "WHERE status IN ('running','cancel_requested')"))
            return result.rowcount
        except SQLAlchemyError:
            raise RequestStorageError() from None

    def create(self, client_request_id, dataset_id, question):
        if (not isinstance(client_request_id, UUID) or not isinstance(dataset_id, UUID)
                or not isinstance(question, str) or not 1 <= len(question) <= 4096
                or not question.strip() or '\x00' in question):
            raise InvalidRequest()
        try:
            question.encode('utf-8', errors='strict')
        except UnicodeEncodeError:
            raise InvalidRequest() from None
        try:
            # Serialize the same idempotency key before checking either record or readiness.
            self._connection.execute(sa.text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                                     {'key': str(client_request_id)})
            existing = self._connection.execute(sa.text(
                f'SELECT {_COLUMNS} FROM request_intents WHERE client_request_id = :key'),
                {'key': client_request_id}).one_or_none()
            if existing is not None:
                record = RequestRecord(*existing)
                if record.dataset_id != dataset_id or record.question != question:
                    raise IdempotencyConflict()
                return record, False
            dataset = self._connection.execute(sa.text(
                'SELECT lifecycle, publication_state FROM datasets WHERE id = :id FOR SHARE'),
                {'id': dataset_id}).one_or_none()
            if dataset is None or dataset.lifecycle != 'active':
                raise DatasetNotFound()
            if dataset.publication_state != 'ready':
                raise DatasetUnavailable()
            row = self._connection.execute(sa.text(
                'INSERT INTO request_intents (id, client_request_id, dataset_id, question) '
                'VALUES (:id, :key, :dataset, :question) '
                f'ON CONFLICT (client_request_id) DO NOTHING RETURNING {_COLUMNS}'),
                {'id': uuid4(), 'key': client_request_id, 'dataset': dataset_id, 'question': question}).one_or_none()
            if row is None:
                row = self._connection.execute(sa.text(
                    f'SELECT {_COLUMNS} FROM request_intents WHERE client_request_id = :key'),
                    {'key': client_request_id}).one()
                record = RequestRecord(*row)
                if record.dataset_id != dataset_id or record.question != question:
                    raise IdempotencyConflict()
                return record, False
            return RequestRecord(*row), True
        except SQLAlchemyError:
            raise RequestStorageError() from None
