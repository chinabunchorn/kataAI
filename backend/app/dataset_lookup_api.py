"""Ready-only dataset lookup router."""
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .dataset_runtime import load_dataset_runtime
from .dataset_store import DatasetNotFound, PostgresDatasetStore
from .ready_dataset import DatasetUnavailable, get_ready_dataset

router = APIRouter()


def get_dataset_runtime():
    """Trusted dependency; None means the configuration is unavailable."""
    try:
        return load_dataset_runtime()
    except Exception:
        return None


def _error(status, code, message):
    return JSONResponse({'error': {'code': code, 'message': message}}, status_code=status)


@router.get('/v1/datasets/{dataset_id}')
def lookup_dataset(dataset_id: str, runtime=Depends(get_dataset_runtime)):
    try:
        parsed = UUID(dataset_id)
        if str(parsed) != dataset_id:
            raise ValueError
    except ValueError:
        return _error(422, 'INVALID_DATASET_ID', 'Invalid dataset ID.')
    try:
        if runtime is None:
            raise DatasetUnavailable()
        with runtime.connection() as connection:
            result = get_ready_dataset(PostgresDatasetStore(connection), parsed)
        return {'dataset_id': str(result.dataset_id), 'display_name': result.display_name, 'state': result.state}
    except DatasetNotFound:
        return _error(404, 'DATASET_NOT_FOUND', 'Dataset not found.')
    except Exception:
        return _error(503, 'DATASET_UNAVAILABLE', 'Dataset unavailable.')
