"""Provisional request HTTP boundary; no execution is performed here."""
import base64
import binascii
from datetime import datetime
from uuid import UUID

from fastapi.responses import JSONResponse, Response

from .dataset_store import DatasetNotFound


def queue_factory(connection):
    # Imported lazily so absent queue/config fails closed without breaking other routes.
    from .request_queue import RequestQueue
    return RequestQueue(connection)


def error(status, code, message):
    return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message}},
                        headers={'Cache-Control': 'no-store'})


def public_record(record, *, include_detail=False):
    if record.status not in {'queued', 'running', 'fake_completed', 'unknown', 'cancelled', 'cancel_requested'}:
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


def cancel(runtime, request_id):
    try:
        if runtime is None:
            raise RuntimeError('runtime unavailable')
        with runtime.connection() as connection:
            record = queue_factory(connection).cancel(request_id)
            body = public_record(record) if record is not None else None
            connection.commit()
        if record is None:
            return error(404, 'REQUEST_NOT_FOUND', 'Request not found.')
        if record.status not in {'cancelled', 'cancel_requested'}:
            return error(409, 'REQUEST_CONFLICT', 'Request cannot be cancelled.')
        return JSONResponse(body, headers={'Cache-Control': 'no-store'})
    except Exception:
        return error(503, 'EXECUTION_UNAVAILABLE', 'Request processing is unavailable.')


def hide(runtime, request_id):
    try:
        if runtime is None:
            raise RuntimeError('runtime unavailable')
        with runtime.connection() as connection:
            record = queue_factory(connection).hide_history(request_id)
            connection.commit()
        if record is None:
            return error(404, 'REQUEST_NOT_FOUND', 'Request not found.')
        if record.status not in {'cancelled', 'fake_completed'}:
            return error(409, 'REQUEST_CONFLICT', 'Request cannot be hidden.')
        return Response(status_code=204, headers={'Cache-Control': 'no-store'})
    except Exception:
        return error(503, 'EXECUTION_UNAVAILABLE', 'Request processing is unavailable.')


def history(runtime, limit, cursor=None):
    before = None
    if cursor is not None:
        try:
            raw = base64.b64decode(cursor.encode('ascii'), altchars=b'-_', validate=True).decode('ascii')
            timestamp, identifier = raw.split('|')
            timestamp = datetime.fromisoformat(timestamp)
            if timestamp.utcoffset() is None:
                raise ValueError('naive timestamp')
            before = (timestamp, UUID(identifier))
        except (ValueError, UnicodeError, binascii.Error):
            return error(422, 'INVALID_REQUEST', 'Invalid request.')
    try:
        if runtime is None:
            raise RuntimeError('runtime unavailable')
        with runtime.connection() as connection:
            queue = queue_factory(connection)
            records = queue.history(limit) if before is None else queue.history(limit, before=before)
            records = records[:limit]
            result = {'requests': [public_record(record, include_detail=True) for record in records]}
            if len(records) == limit:
                last = records[-1]
                raw = f'{last.created_at.isoformat()}|{UUID(str(last.id))}'.encode('ascii')
                result['next_cursor'] = base64.urlsafe_b64encode(raw).decode('ascii')
            return JSONResponse(result, headers={'Cache-Control': 'no-store'})
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
