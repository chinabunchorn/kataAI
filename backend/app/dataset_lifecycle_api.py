"""Router factory for conservative, file-retaining dataset deletion."""
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .dataset_lifecycle import DatasetDeletionConflict, DatasetDeletionNotFound, delete_dataset


def create_dataset_lifecycle_router(runtime_dependency):
    router = APIRouter()

    @router.delete('/v1/datasets/{dataset_id}')
    def delete(dataset_id: str, runtime=Depends(runtime_dependency)):
        def error(status, code, message):
            return JSONResponse({'error': {'code': code, 'message': message}}, status_code=status)

        try:
            parsed = UUID(dataset_id)
            if str(parsed) != dataset_id:
                raise ValueError
        except ValueError:
            return error(422, 'INVALID_DATASET_ID', 'Invalid dataset ID.')
        try:
            if runtime is None:
                raise ValueError
            delete_dataset(runtime, parsed)
        except DatasetDeletionNotFound:
            return error(404, 'DATASET_NOT_FOUND', 'Dataset not found.')
        except DatasetDeletionConflict:
            return error(409, 'DATASET_CONFLICT', 'Dataset cannot be deleted.')
        except Exception:
            return error(503, 'DATASET_UNAVAILABLE', 'Dataset unavailable.')
        return {'dataset_id': str(parsed), 'state': 'deleted', 'file_cleanup': 'not_attempted'}

    return router
