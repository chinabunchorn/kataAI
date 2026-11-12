"""Internal, non-atomic metadata-first CSV publication."""
from dataclasses import dataclass

from .csv_intake import CsvMetadata
from .dataset_store import DatasetMetadata, PostgresDatasetStore
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


def publish_dataset(store, commit, root, display_name, source):
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
    return PublishedDataset(dataset, csv)
