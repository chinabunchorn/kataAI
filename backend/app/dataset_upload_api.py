"""Streaming upload router; mount behind LocalSecurityMiddleware.

Publication is not transactional across the filesystem and database. A lost
response or a 503 can mean publication committed; never automatically retry.
The private root and its ancestors must be trusted, including against same-UID
mutation. All cooperating processes must use this admission lock.
"""
import asyncio
import fcntl
import os
import stat
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .csv_intake import CsvIntakeError, validate_csv
from .dataset_publication import publish_dataset_on_connection

MAX_BODY_BYTES = 10_065_536
IDLE_SECONDS = 15.0
TOTAL_SECONDS = 60.0


class _Rejected(Exception):
    def __init__(self, status):
        self.status = status


def _error(status):
    code, message = {413: ('UPLOAD_TOO_LARGE', 'Upload too large.'),
                     422: ('INVALID_UPLOAD', 'Invalid upload.'),
                     408: ('UPLOAD_TIMEOUT', 'Upload timed out.'),
                     503: ('UPLOAD_UNAVAILABLE', 'Upload unavailable.')}[status]
    return JSONResponse({'error': {'code': code, 'message': message}}, status_code=status)


def _acquire(root):
    if not all(hasattr(os, flag) for flag in ('O_DIRECTORY', 'O_NOFOLLOW')):
        raise OSError('unsupported')
    directory = os.open(os.path.normpath(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fd = None
    try:
        info = os.fstat(directory)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o7077:
            raise OSError('invalid root')
        fd = os.open('.upload-admission.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o7077 or info.st_nlink != 1):
            raise OSError('invalid lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        closing, directory = directory, None
        os.close(closing)
        result, fd = fd, None
        return result
    finally:
        try:
            if directory is not None:
                os.close(directory)
        finally:
            if fd is not None:
                os.close(fd)


async def _worker(fn, *args):
    """Wait for the real thread even after repeated cancellation requests."""
    task = asyncio.create_task(asyncio.to_thread(fn, *args))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.done():
                # A cancellation of the worker itself is not a successful operation.
                if task.cancelled():
                    raise
                try:
                    result = task.result()
                except BaseException:
                    if cancelled:
                        raise asyncio.CancelledError from None
                    raise
                cancelled = True
                break
            cancelled = True
        except BaseException:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
    if cancelled:
        raise asyncio.CancelledError
    return result


class _Session:
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = None
        self.spool = None
        self.finished = None
        self.result = None

    def start(self, content_type):
        from .multipart_spool import MultipartSpool
        self.lock = _acquire(self.runtime.root)
        self.spool = MultipartSpool(self.runtime.root, content_type)

    def feed(self, chunk):
        self.spool.feed(chunk)

    def finish(self):
        self.finished = self.spool.finish()
        _, stream = self.finished
        # validate_csv deliberately sanitizes source exceptions as invalid input;
        # remember read failures separately so disk errors remain server errors.
        class TrackedReader:
            failed = False

            def read(self, size):
                try:
                    return stream.read(size)
                except Exception:
                    self.failed = True
                    raise

        reader = TrackedReader()
        try:
            validate_csv(reader)
        except CsvIntakeError as exc:
            if reader.failed:
                raise _Rejected(503) from None
            raise _Rejected(413 if exc.code == 'UPLOAD_TOO_LARGE' else 422) from None
        stream.seek(0)

    def publish(self):
        name, stream = self.finished
        runtime = self.runtime
        manager = runtime.connection() if callable(getattr(runtime, 'connection', None)) else runtime.engine.connect()
        with manager as connection:
            self.result = publish_dataset_on_connection(connection, runtime.root, name, stream)

    def close(self):
        try:
            if self.spool is not None:
                self.spool.close()
        finally:
            if self.lock is not None:
                os.close(self.lock)
                self.lock = None


def create_upload_router(runtime_dependency):
    router = APIRouter()

    @router.post('/v1/datasets')
    async def upload(request: Request, runtime=Depends(runtime_dependency)):
        types = [v for k, v in request.scope.get('headers', []) if k.lower() == b'content-type']
        if len(types) != 1 or len(types[0]) > 1024:
            return _error(422)
        try:
            content_type = types[0].decode('ascii')
        except (UnicodeError, AttributeError):
            return _error(422)
        if not content_type.lower().startswith('multipart/form-data;'):
            return _error(422)
        session = _Session(runtime)
        failure = None
        start = time.monotonic()
        try:
            await _worker(session.start, content_type)
            received = 0
            empty_chunks = 0
            last_chunk = start
            while True:
                now = time.monotonic()
                remaining = min(TOTAL_SECONDS - (now - start), IDLE_SECONDS - (now - last_chunk))
                if remaining <= 0:
                    raise _Rejected(408)
                try:
                    message = await asyncio.wait_for(request.receive(), remaining)
                except asyncio.TimeoutError:
                    raise _Rejected(408) from None
                now = time.monotonic()
                if now - start >= TOTAL_SECONDS or now - last_chunk >= IDLE_SECONDS:
                    raise _Rejected(408)
                last_chunk = now
                if not isinstance(message, dict) or message.get('type') != 'http.request':
                    raise _Rejected(422)
                chunk = message.get('body', b'')
                more = message.get('more_body', False)
                if type(chunk) is not bytes or type(more) is not bool:
                    raise _Rejected(422)
                if not chunk and more:
                    empty_chunks += 1
                    if empty_chunks > 1024:
                        raise _Rejected(422)
                received += len(chunk)
                if received > MAX_BODY_BYTES:
                    raise _Rejected(413)
                await _worker(session.feed, chunk)
                if time.monotonic() - start >= TOTAL_SECONDS:
                    raise _Rejected(408)
                if not more:
                    break
            await _worker(session.finish)
            if time.monotonic() - start >= TOTAL_SECONDS:
                raise _Rejected(408)
            await _worker(session.publish)
        except _Rejected as exc:
            failure = exc.status
        except Exception as exc:
            from .multipart_spool import MultipartSpoolError
            if isinstance(exc, MultipartSpoolError):
                failure = {'BODY_TOO_LARGE': 413, 'FILE_TOO_LARGE': 413,
                           'INVALID_MULTIPART': 422}.get(exc.code, 503)
            else:
                failure = 503
        finally:
            try:
                await _worker(session.close)
            except Exception:
                failure = 503
        if failure is not None:
            return _error(failure)
        dataset = session.result.dataset
        return JSONResponse({'dataset_id': str(dataset.id), 'display_name': dataset.display_name,
                             'state': dataset.publication_state}, status_code=201)

    return router
