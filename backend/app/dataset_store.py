"""Dataset metadata storage; connections and transaction boundaries belong to callers."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Protocol, runtime_checkable
from unicodedata import category
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError


@dataclass(frozen=True)
class DatasetMetadata:
    id: UUID
    display_name: str
    storage_key: UUID
    created_at: datetime
    lifecycle: Literal['active', 'deleted']
    deleted_at: datetime | None
    publication_state: Literal['unknown', 'pending', 'ready'] = 'unknown'


class DatasetStore(Protocol):
    def create(self, display_name: str) -> DatasetMetadata: ...
    def get(self, dataset_id: UUID) -> DatasetMetadata: ...


@runtime_checkable
class PublicationStore(DatasetStore, Protocol):
    def mark_ready(self, dataset: DatasetMetadata) -> DatasetMetadata: ...


class InvalidDatasetMetadata(ValueError):
    def __init__(self) -> None:
        super().__init__('INVALID_DATASET_METADATA')


class DatasetNotFound(LookupError):
    def __init__(self) -> None:
        super().__init__('DATASET_NOT_FOUND')


class DuplicateDatasetMetadata(Exception):
    def __init__(self) -> None:
        super().__init__('DUPLICATE_DATASET_METADATA')


class DatasetStorageError(Exception):
    def __init__(self) -> None:
        super().__init__('DATASET_STORAGE_ERROR')


class DatasetPublicationConflict(Exception):
    def __init__(self) -> None:
        super().__init__('DATASET_PUBLICATION_CONFLICT')


def _validate_name(name: str) -> None:
    # Deliberately stricter than the migration for portability across DB locales.
    if (not isinstance(name, str) or not 1 <= len(name) <= 255 or name != name.strip()
            or name in ('.', '..') or '/' in name or '\\' in name
            or any(category(char).startswith('C') for char in name)):
        raise InvalidDatasetMetadata()


def _validate_id(value: UUID) -> None:
    if not isinstance(value, UUID):
        raise InvalidDatasetMetadata()


def _new_ids(factory: Callable[[], UUID]) -> tuple[UUID, UUID]:
    dataset_id, key = factory(), factory()
    _validate_id(dataset_id)
    _validate_id(key)
    return dataset_id, key


class MemoryDatasetStore:
    def __init__(self, *, id_factory: Callable[[], UUID] = uuid4,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._id_factory, self._clock = id_factory, clock
        self._records: dict[UUID, DatasetMetadata] = {}
        self._keys: set[UUID] = set()

    def create(self, display_name: str) -> DatasetMetadata:
        _validate_name(display_name)
        dataset_id, key = _new_ids(self._id_factory)
        if dataset_id in self._records or key in self._keys:
            raise DuplicateDatasetMetadata()
        created_at = self._clock()
        if not isinstance(created_at, datetime) or created_at.utcoffset() is None:
            raise InvalidDatasetMetadata()
        record = DatasetMetadata(dataset_id, display_name, key, created_at, 'active', None, 'pending')
        self._records[record.id] = record
        self._keys.add(key)
        return record

    def get(self, dataset_id: UUID) -> DatasetMetadata:
        _validate_id(dataset_id)
        try:
            return self._records[dataset_id]
        except KeyError:
            raise DatasetNotFound() from None


class PostgresDatasetStore:
    def __init__(self, connection: Connection, *, id_factory: Callable[[], UUID] = uuid4) -> None:
        self._connection, self._id_factory = connection, id_factory

    def create(self, display_name: str) -> DatasetMetadata:
        _validate_name(display_name)
        dataset_id, key = _new_ids(self._id_factory)
        try:
            row = self._connection.execute(sa.text(
                "INSERT INTO datasets (id, display_name, storage_key, publication_state) "
                "VALUES (:id, :name, :key, 'pending') "
                'ON CONFLICT DO NOTHING '
                'RETURNING id, display_name, storage_key, created_at, lifecycle, deleted_at, publication_state'),
                {'id': dataset_id, 'name': display_name, 'key': key}).one_or_none()
        except SQLAlchemyError:
            raise DatasetStorageError() from None
        if row is None:
            raise DuplicateDatasetMetadata()
        return DatasetMetadata(*row)

    def get(self, dataset_id: UUID) -> DatasetMetadata:
        _validate_id(dataset_id)
        try:
            row = self._connection.execute(sa.text(
                'SELECT id, display_name, storage_key, created_at, lifecycle, deleted_at, publication_state '
                'FROM datasets WHERE id = :id'), {'id': dataset_id}).one_or_none()
        except SQLAlchemyError:
            raise DatasetStorageError() from None
        if row is None:
            raise DatasetNotFound()
        return DatasetMetadata(*row)

    def mark_ready(self, dataset: DatasetMetadata) -> DatasetMetadata:
        """Compare identity, pending state and lifecycle; caller owns commit."""
        try:
            row = self._connection.execute(sa.text(
                "UPDATE datasets SET publication_state = 'ready' "
                "WHERE id = :id AND storage_key = :key AND lifecycle = 'active' "
                "AND publication_state = 'pending' "
                'RETURNING id, display_name, storage_key, created_at, lifecycle, deleted_at, publication_state'),
                {'id': dataset.id, 'key': dataset.storage_key}).one_or_none()
        except SQLAlchemyError:
            raise DatasetStorageError() from None
        if row is None:
            raise DatasetPublicationConflict()
        return DatasetMetadata(*row)

    def list_incomplete(self, *, limit: int = 100,
                        after: tuple[datetime, UUID] | None = None) -> list[DatasetMetadata]:
        """Snapshot only; rows may still have a live publisher."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('INVALID_PAGE_LIMIT')
        if after is not None and (not isinstance(after, tuple) or len(after) != 2
                                  or not isinstance(after[0], datetime) or after[0].utcoffset() is None
                                  or not isinstance(after[1], UUID)):
            raise ValueError('INVALID_PAGE_CURSOR')
        try:
            query = (
                'SELECT id, display_name, storage_key, created_at, lifecycle, deleted_at, publication_state '
                "FROM datasets WHERE publication_state IN ('pending', 'unknown') ")
            params: dict[str, object] = {'limit': limit}
            if after is not None:
                query += 'AND (created_at, id) > (:created_at, :id) '
                params.update(created_at=after[0], id=after[1])
            rows = self._connection.execute(sa.text(query + 'ORDER BY created_at, id LIMIT :limit'), params)
            return [DatasetMetadata(*row) for row in rows]
        except SQLAlchemyError:
            raise DatasetStorageError() from None
