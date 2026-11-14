"""Explicit fake-only processing; no generated Python is ever executed."""
from .dataset_columns import read_dataset_columns
from .dataset_store import DatasetNotFound, PostgresDatasetStore
from .fake_flow import run_fake_flow
from .fakes import FakeModel
from .ready_dataset import DatasetUnavailable


def process_claim(connection, root, claim, *, model=None):
    """Return a predetermined result, not a computation from the dataset."""
    dataset = PostgresDatasetStore(connection).get(claim.dataset_id)
    if dataset.lifecycle != 'active':
        raise DatasetNotFound()
    if dataset.publication_state != 'ready':
        raise DatasetUnavailable()
    columns = read_dataset_columns(root, dataset.storage_key)
    # End the read-only transaction before a possibly slow model call; the
    # owning session lock remains held by the caller's dedicated connection.
    connection.commit()
    if model is None:
        model = FakeModel([{'name': 'run_python', 'arguments': {'code': '# fake proposal; not executed'}}])
    return run_fake_flow(model, {'example': [1, 2]}, claim.question, columns,
                         request_id=claim.id, dataset_id=claim.dataset_id)
