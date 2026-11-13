"""Provisional request HTTP boundary; no execution is performed here."""
from uuid import UUID

from fastapi.responses import JSONResponse

from .dataset_store import DatasetNotFound


def queue_factory(connection):
    # Imported lazily so absent queue/config fails closed without breaking other routes.
    from .request_queue import RequestQueue
    return RequestQueue(connection)


def error(status, code, message):
    return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message}},
                        headers={'Cache-Control': 'no-store'})


def public_record(record, *, include_detail=False):
    if record.status not in {'queued', 'running', 'fake_completed', 'unknown'}:
        raise ValueError('unsupported status')
    result = {'id': str(UUID(str(record.id))), 'status': record.status, 'provisional': True}
    if include_detail:
        if not isinstance(record.question, str) or not 1 <= len(record.question) <= 4096:
            raise ValueError('invalid question')
        if record.created_at.utcoffset() is None:
            raise ValueError('invalid timestamp')
        result.update(dataset_id=str(UUID(str(record.dataset_id))), question=record.question,
                      created_at=record.created_at.isoformat())
    if record.status == 'fake_completed':
        result['fake'] = True
    return result


def status(runtime, request_id):
    try:
        if runtime is None:
            raise RuntimeError('runtime unavailable')
        with runtime.connection() as connection:
            record = queue_factory(connection).get(request_id)
            if record is None:
                return error(404, 'REQUEST_NOT_FOUND', 'Request not found.')
            return JSONResponse(public_record(record, include_detail=True), headers={'Cache-Control': 'no-store'})
    except Exception:
        return error(503, 'EXECUTION_UNAVAILABLE', 'Request processing is unavailable.')


def history(runtime, limit):
    try:
        if runtime is None:
            raise RuntimeError('runtime unavailable')
        with runtime.connection() as connection:
            records = queue_factory(connection).history(limit)
            return JSONResponse({'requests': [public_record(record, include_detail=True) for record in records[:limit]]},
                                headers={'Cache-Control': 'no-store'})
    except Exception:
        return error(503, 'EXECUTION_UNAVAILABLE', 'Request processing is unavailable.')


def create_request(payload, runtime):
    try:
        if runtime is None:
            raise RuntimeError('runtime unavailable')
        with runtime.connection() as connection:
            record, created = queue_factory(connection).create(
                UUID(payload.client_request_id), UUID(payload.dataset_id), payload.question)
            body = public_record(record)
            if created:
                connection.commit()
        return JSONResponse(status_code=201 if created else 200, content=body, headers={'Cache-Control': 'no-store'})
    except DatasetNotFound:
        return error(404, 'DATASET_NOT_FOUND', 'Dataset not found.')
    except Exception as exc:
        try:
            from .request_queue import IdempotencyConflict
            if isinstance(exc, IdempotencyConflict):
                return error(409, 'IDEMPOTENCY_CONFLICT', 'Request ID already used for different input.')
        except ImportError:
            pass
        return error(503, 'EXECUTION_UNAVAILABLE', 'Request processing is unavailable.')
