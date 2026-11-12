"""Internal, non-atomic metadata-first CSV publication."""
from dataclasses import dataclass
from typing import Callable

from .csv_intake import CsvMetadata
from .dataset_store import DatasetMetadata, DatasetPublicationConflict, PostgresDatasetStore, PublicationStore
from .local_csv_storage import CsvStorageError, publish_csv


@dataclass(frozen=True)
class PublishedDataset:
    dataset: DatasetMetadata
    csv: CsvMetadata


class DatasetPublicationError(Exception):
    def __init__(self, phase, dataset, *, code=None, publication=None, cleanup=None):
        self.phase = phase
        self.dataset = dataset
        self.code = code
        self.publication = publication
        self.cleanup = cleanup
        super().__init__('DATASET_PUBLICATION_ERROR')


def publish_dataset_on_connection(connection, root, display_name, source):
    """Commit only a dedicated connection's own transaction, then publish."""
    return publish_dataset(PostgresDatasetStore(connection), connection.commit, root, display_name, source)


def publish_dataset(store: PublicationStore, commit: Callable[[], None], root, display_name, source):
    if not all(callable(getattr(store, name, None)) for name in ('create', 'get', 'mark_ready')):
        raise TypeError('INVALID_PUBLICATION_STORE')
    dataset = store.create(display_name)
    interrupted = False
    try:
        commit()
    except KeyboardInterrupt:
        interrupted = True
    except Exception:
        raise DatasetPublicationError('commit_unknown', dataset) from None
    if interrupted:
        raise KeyboardInterrupt()
    try:
        csv = publish_csv(root, source, dataset.storage_key)
    except CsvStorageError as exc:
        raise DatasetPublicationError('publication_failed', dataset, code=exc.code,
                                      publication=exc.publication, cleanup=exc.cleanup) from None
    interrupted = False
    try:
        ready = store.mark_ready(dataset)
    except KeyboardInterrupt:
        interrupted = True
    except DatasetPublicationConflict:
        raise DatasetPublicationError('ready_conflict', dataset) from None
    except Exception:
        raise DatasetPublicationError('ready_update_unknown', dataset) from None
    if interrupted:
        raise KeyboardInterrupt()
    try:
        commit()
    except KeyboardInterrupt:
        interrupted = True
    except Exception:
        raise DatasetPublicationError('ready_commit_unknown', dataset) from None
    if interrupted:
        raise KeyboardInterrupt()
    return PublishedDataset(ready, csv)
