"""Internal readiness gate; does not expose a dataset HTTP endpoint."""
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from .dataset_store import DatasetNotFound


@dataclass(frozen=True)
class ReadyDataset:
    dataset_id: UUID
    display_name: str
    state: Literal['ready'] = 'ready'


class DatasetUnavailable(Exception):
    def __init__(self):
        super().__init__('DATASET_UNAVAILABLE')


def get_ready_dataset(store, dataset_id):
    record = store.get(dataset_id)
    if record.lifecycle != 'active':
        raise DatasetNotFound()
    if record.publication_state != 'ready':
        raise DatasetUnavailable()
    return ReadyDataset(record.id, record.display_name)
