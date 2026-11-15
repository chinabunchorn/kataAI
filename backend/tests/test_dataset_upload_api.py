import asyncio
import io
import sys
import threading
import types
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_missing_content_type_rejected_without_reading_body(tmp_path):
    from app.dataset_upload_api import create_upload_router
    app = FastAPI()
    app.include_router(create_upload_router(lambda: object()))
    response = TestClient(app).post('/v1/datasets', content=b'secret')
    assert response.status_code == 422
    assert 'secret' not in response.text


@pytest.fixture
def harness(tmp_path, monkeypatch):
    from app import dataset_upload_api as upload
    tmp_path.chmod(0o700)
    state = SimpleNamespace(feeds=[], closed=0, publishes=0, gate=None, entered=threading.Event(), error=None)

    class SpoolError(Exception):
        def __init__(self, code):
            self.code = code

    class Spool:
        def __init__(self, root, content_type):
            self.data = b''
        def feed(self, data):
            state.feeds.append(data)
            if state.error:
                raise SpoolError(state.error)
            if state.gate == 'feed':
                state.entered.set()
                assert state.release.wait(5)
                assert state.closed == 0
            self.data += data
        def finish(self):
            if self.data != b'valid':
                raise SpoolError('INVALID_MULTIPART')
            return 'safe.csv', io.BytesIO(b'a,b\n')
        def close(self):
            state.closed += 1

    fake = types.ModuleType('app.multipart_spool')
    fake.MultipartSpool = Spool
    fake.MultipartSpoolError = SpoolError
    monkeypatch.setitem(sys.modules, 'app.multipart_spool', fake)

    class Runtime:
        root = tmp_path
        @contextmanager
        def connection(self):
            yield object()
    runtime = Runtime()
    def publish(conn, root, name, source):
        state.publishes += 1
        assert name == 'safe.csv' and source.read() == b'a,b\n'
        if state.gate == 'publish':
            state.entered.set()
            assert state.release.wait(5)
            assert state.closed == 0
        return SimpleNamespace(dataset=SimpleNamespace(id=uuid4(), display_name=name, publication_state='ready'))
    monkeypatch.setattr(upload, 'publish_dataset_on_connection', publish)
    app = FastAPI()
    app.include_router(upload.create_upload_router(lambda: runtime))
    return app, state, upload


async def call(app, messages, headers=None):
    sent = []
    events = iter(messages)
    async def receive():
        return next(events)
    async def send(message):
        sent.append(message)
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
             'method': 'POST', 'scheme': 'http', 'path': '/v1/datasets', 'raw_path': b'/v1/datasets',
             'query_string': b'', 'root_path': '', 'server': ('localhost', 80), 'client': ('localhost', 1),
             'headers': headers if headers is not None else [(b'content-type', b'multipart/form-data; boundary=abc')]}
    await app(scope, receive, send)
    return sent


def msg(body, more=False):
    return {'type': 'http.request', 'body': body, 'more_body': more}


@pytest.mark.parametrize('csv', [b'a,b\n1\n', b'a,b\n1,\xff\n'])
def test_invalid_csv_never_opens_database(tmp_path, monkeypatch, caplog, csv):
    from app import dataset_upload_api as upload
    tmp_path.chmod(0o700)
    connections = []
    class Runtime:
        root = tmp_path
        @contextmanager
        def connection(self):
            connections.append(True)
            yield object()
    app = FastAPI()
    app.include_router(upload.create_upload_router(lambda: Runtime()))
    body = (b'--abc\r\nContent-Disposition: form-data; name="file"; filename="secret.csv"\r\n\r\n'
            + csv + b'\r\n--abc--\r\n')
    sent = asyncio.run(call(app, [msg(body)]))
    assert sent[0]['status'] == 422
    assert b'INVALID_UPLOAD' in sent[1]['body']
    assert b'secret' not in sent[1]['body'] and 'secret' not in caplog.text
    assert not connections
    assert {p.name for p in tmp_path.iterdir()} == {'.upload-admission.lock'}


def test_spool_read_error_is_unavailable_without_database(tmp_path, monkeypatch, caplog):
    from app import dataset_upload_api as upload, multipart_spool
    tmp_path.chmod(0o700)
    original = multipart_spool.MultipartSpool.finish
    class BrokenReader:
        def read(self, size):
            raise OSError('secret disk path')
    def broken_finish(self):
        name, _ = original(self)
        return name, BrokenReader()
    monkeypatch.setattr(multipart_spool.MultipartSpool, 'finish', broken_finish)
    class Runtime:
        root = tmp_path
        def connection(self):
            pytest.fail('database must not be opened')
    app = FastAPI()
    app.include_router(upload.create_upload_router(lambda: Runtime()))
    body = b'--abc\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n\r\na,b\r\n--abc--\r\n'
    sent = asyncio.run(call(app, [msg(body)]))
    assert sent[0]['status'] == 503
    assert b'UPLOAD_UNAVAILABLE' in sent[1]['body']
    assert b'secret' not in sent[1]['body'] and 'secret' not in caplog.text
    assert {p.name for p in tmp_path.iterdir()} == {'.upload-admission.lock'}


def test_csv_byte_limit_maps_to_413_before_database(harness, monkeypatch):
    from app.csv_intake import CsvLimits
    app, state, upload = harness
    original = upload.validate_csv
    monkeypatch.setattr(upload, 'validate_csv', lambda stream: original(stream, CsvLimits(max_bytes=2)))
    sent = asyncio.run(call(app, [msg(b'valid')]))
    assert sent[0]['status'] == 413
    assert b'UPLOAD_TOO_LARGE' in sent[1]['body']
    assert state.publishes == 0 and state.closed == 1


def test_validation_deadline_prevents_publication(harness, monkeypatch):
    import time
    app, state, upload = harness
    original = upload.validate_csv
    def slow_validate(source):
        time.sleep(0.03)
        return original(source)
    monkeypatch.setattr(upload, 'validate_csv', slow_validate)
    monkeypatch.setattr(upload, 'TOTAL_SECONDS', 0.01)
    sent = asyncio.run(call(app, [msg(b'valid')]))
    assert sent[0]['status'] == 408
    assert state.publishes == 0 and state.closed == 1


def test_cancellation_during_validation_holds_admission(harness, monkeypatch):
    app, state, upload = harness
    entered, release = threading.Event(), threading.Event()
    original = upload.validate_csv
    def blocked_validate(source):
        entered.set()
        assert release.wait(5)
        assert state.closed == 0
        return original(source)
    monkeypatch.setattr(upload, 'validate_csv', blocked_validate)
    async def run():
        task = asyncio.create_task(call(app, [msg(b'valid')]))
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        task.cancel()
        assert (await call(app, []))[0]['status'] == 503
        assert not task.done() and state.closed == 0
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert state.closed == 1 and state.publishes == 0
    asyncio.run(run())


def test_empty_nonfinal_chunks_are_bounded_but_final_empty_is_allowed(harness):
    app, state, _ = harness
    sent = asyncio.run(call(app, [msg(b'', True)] * 1025 + [msg(b'valid')]))
    assert sent[0]['status'] == 422
    assert state.publishes == 0 and state.closed == 1
    assert b'INVALID_UPLOAD' in sent[1]['body']
    sent = asyncio.run(call(app, [msg(b'valid', True), msg(b'')]))
    assert sent[0]['status'] == 201


def test_success_and_actual_body_limit(harness, monkeypatch):
    app, state, upload = harness
    monkeypatch.setattr(upload, 'MAX_BODY_BYTES', 5)
    sent = asyncio.run(call(app, [msg(b'va', True), msg(b'lid')]))
    assert sent[0]['status'] == 201
    assert state.feeds == [b'va', b'lid'] and state.publishes == 1 and state.closed == 1
    sent = asyncio.run(call(app, [msg(b'valid', True), msg(b'x')]))
    assert sent[0]['status'] == 413
    assert state.feeds == [b'va', b'lid', b'valid'] and state.publishes == 1


@pytest.mark.parametrize('messages', [[{'type': 'http.disconnect'}], [msg(b'bad')], [{'type': 'http.request', 'body': 'bad'}]])
def test_invalid_stream_rejected(harness, messages):
    app, state, _ = harness
    assert asyncio.run(call(app, messages))[0]['status'] == 422
    assert state.closed == 1 and state.publishes == 0


@pytest.mark.parametrize('stage', ['feed', 'publish'])
def test_cancellation_waits_for_worker_and_holds_admission(harness, stage):
    app, state, _ = harness
    state.gate = stage
    state.release = threading.Event()
    async def run():
        first = asyncio.create_task(call(app, [msg(b'valid')]))
        assert await asyncio.to_thread(state.entered.wait, 3)
        first.cancel()
        await asyncio.sleep(0.02)
        first.cancel()
        second = await call(app, [msg(b'valid')])
        assert second[0]['status'] == 503
        assert state.closed == 0 and not first.done()
        state.release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert state.closed == 1
        state.gate = None
        third = await call(app, [msg(b'valid')])
        assert third[0]['status'] == 201
    asyncio.run(run())
    assert state.publishes == (1 if stage == 'feed' else 2)


@pytest.mark.parametrize('code,status', [('FILE_TOO_LARGE', 413), ('BODY_TOO_LARGE', 413),
                                         ('STORAGE_ERROR', 503), ('CLEANUP_UNCERTAIN', 503),
                                         ('INVALID_MULTIPART', 422), ('INVALID_STATE', 503)])
def test_spool_error_mapping_and_envelope(harness, code, status):
    import json
    app, state, _ = harness
    state.error = code
    sent = asyncio.run(call(app, [msg(b'valid')]))
    assert sent[0]['status'] == status
    body = json.loads(sent[1]['body'])
    assert set(body['error']) == {'code', 'message'}
    assert code not in str(body)


def test_lock_directory_close_failure_does_not_leak_lock(tmp_path, monkeypatch):
    import os
    from app import dataset_upload_api as upload
    tmp_path.chmod(0o700)
    original_close = os.close
    directory_fd = None
    real_open = os.open
    def opening(*args, **kwargs):
        nonlocal directory_fd
        fd = real_open(*args, **kwargs)
        if kwargs.get('dir_fd') is None:
            directory_fd = fd
        return fd
    def closing(fd):
        if fd == directory_fd:
            original_close(fd)
            raise OSError('synthetic close failure')
        return original_close(fd)
    with monkeypatch.context() as m:
        m.setattr(upload.os, 'open', opening)
        m.setattr(upload.os, 'close', closing)
        with pytest.raises(OSError):
            upload._acquire(tmp_path)
    fd = upload._acquire(tmp_path)
    os.close(fd)


def test_total_deadline_includes_startup(harness, monkeypatch):
    import time
    app, state, upload = harness
    original = upload._Session.start
    def slow_start(self, content_type):
        time.sleep(0.03)
        original(self, content_type)
    monkeypatch.setattr(upload, 'TOTAL_SECONDS', 0.01)
    monkeypatch.setattr(upload._Session, 'start', slow_start)
    sent = asyncio.run(call(app, [msg(b'valid')]))
    assert sent[0]['status'] == 408
    assert not state.feeds and not state.publishes and state.closed == 1


def test_idle_deadline_includes_blocking_feed(harness, monkeypatch):
    import time
    app, state, upload = harness
    original = upload._Session.feed
    def slow_feed(self, data):
        time.sleep(0.03)
        original(self, data)
    monkeypatch.setattr(upload, 'IDLE_SECONDS', 0.01)
    monkeypatch.setattr(upload._Session, 'feed', slow_feed)
    sent = asyncio.run(call(app, [msg(b'va', True), msg(b'lid')]))
    assert sent[0]['status'] == 408
    assert state.feeds == [b'va'] and state.publishes == 0


def test_actual_multipart_spool_integration(tmp_path, monkeypatch):
    from app import dataset_upload_api as upload
    tmp_path.chmod(0o700)
    class Runtime:
        root = tmp_path
        @contextmanager
        def connection(self):
            yield object()
    calls = []
    def publish(connection, root, name, source):
        calls.append((name, source.read()))
        return SimpleNamespace(dataset=SimpleNamespace(id=uuid4(), display_name=name, publication_state='ready'))
    monkeypatch.setattr(upload, 'publish_dataset_on_connection', publish)
    app = FastAPI()
    app.include_router(upload.create_upload_router(lambda: Runtime()))
    body = b'--abc\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n\r\nx,y\r\n--abc--\r\n'
    sent = asyncio.run(call(app, [msg(body[:30], True), msg(body[30:])]))
    assert sent[0]['status'] == 201 and calls == [('a.csv', b'x,y')]
    assert {p.name for p in tmp_path.iterdir()} == {'.upload-admission.lock'}
    sent = asyncio.run(call(app, [msg(body[:-5])]))
    assert sent[0]['status'] == 422 and len(calls) == 1


def test_duplicate_content_type_and_lock_contention_do_not_read(harness):
    app, state, upload = harness
    async def run():
        headers = [(b'content-type', b'multipart/form-data; boundary=abc')] * 2
        assert (await call(app, [], headers))[0]['status'] == 422
        fd = upload._acquire(upload_root)
        try:
            assert (await call(app, []))[0]['status'] == 503
        finally:
            import os
            os.close(fd)
    # The fixture's dependency carries the root through its closure.
    upload_root = next(route for route in app.routes if getattr(route, 'path', None) == '/v1/datasets').dependant.dependencies[0].call().root
    asyncio.run(run())
    assert not state.feeds and state.closed == 0


def test_lock_rejects_symlink_root_even_with_dot_suffix(tmp_path):
    from app.dataset_upload_api import _acquire
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    link = tmp_path / 'alias'
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        _acquire(str(link) + '/.')


def test_real_spool_and_publication_with_disposable_fake_store(tmp_path, monkeypatch):
    from dataclasses import replace
    from app import dataset_publication as publication
    from app import dataset_upload_api as upload
    from app.dataset_store import MemoryDatasetStore
    tmp_path.chmod(0o700)
    store = MemoryDatasetStore()
    class Store:
        def __init__(self, connection):
            pass
        def create(self, name):
            return store.create(name)
        def get(self, dataset_id):
            return store.get(dataset_id)
        def mark_ready(self, record):
            ready = replace(record, publication_state='ready')
            store._records[record.id] = ready
            return ready
    commits = []
    class Connection:
        def commit(self):
            commits.append(True)
    class Runtime:
        root = tmp_path
        @contextmanager
        def connection(self):
            yield Connection()
    monkeypatch.setattr(publication, 'PostgresDatasetStore', Store)
    app = FastAPI()
    app.include_router(upload.create_upload_router(lambda: Runtime()))
    body = b'--abc\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n\r\nx,y\r\n1,2\r\n--abc--\r\n'
    sent = asyncio.run(call(app, [msg(body)]))
    assert sent[0]['status'] == 201 and len(commits) == 2
    record = next(iter(store._records.values()))
    assert record.publication_state == 'ready'
    assert (tmp_path / str(record.storage_key)).read_bytes() == b'x,y\r\n1,2'
    assert str(record.storage_key).encode() not in sent[1]['body']


def test_cancellation_during_cleanup_holds_lock(harness, monkeypatch):
    app, state, upload = harness
    entered, release = threading.Event(), threading.Event()
    original = upload._Session.close
    def blocked_close(self):
        if self.spool is not None:
            entered.set()
            assert release.wait(5)
        original(self)
    monkeypatch.setattr(upload._Session, 'close', blocked_close)
    async def run():
        task = asyncio.create_task(call(app, [msg(b'valid')]))
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        task.cancel()
        assert (await call(app, []))[0]['status'] == 503
        assert not task.done() and state.closed == 0
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert state.closed == 1 and state.publishes == 1
    asyncio.run(run())


def test_cleanup_failure_after_publication_is_503_no_retry(harness, monkeypatch):
    app, state, upload = harness
    original = upload._Session.close
    def uncertain(self):
        original(self)
        raise OSError('secret path')
    monkeypatch.setattr(upload._Session, 'close', uncertain)
    sent = asyncio.run(call(app, [msg(b'valid')]))
    assert sent[0]['status'] == 503 and state.publishes == 1
    assert b'secret' not in sent[1]['body']


def test_idle_receive_timeout(harness, monkeypatch):
    app, state, upload = harness
    monkeypatch.setattr(upload, 'IDLE_SECONDS', 0.01)
    original = asyncio.wait_for
    async def force_timeout(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError()
    monkeypatch.setattr(asyncio, 'wait_for', force_timeout)
    sent = asyncio.run(call(app, [msg(b'valid')]))
    assert sent[0]['status'] == 408 and not state.feeds
    monkeypatch.setattr(asyncio, 'wait_for', original)


def test_admission_lock_is_interprocess(tmp_path):
    import os
    import subprocess
    import sys
    from app.dataset_upload_api import _acquire
    tmp_path.chmod(0o700)
    fd = _acquire(tmp_path)
    try:
        result = subprocess.run([sys.executable, '-c',
            'from app.dataset_upload_api import _acquire; import sys; _acquire(sys.argv[1])', str(tmp_path)],
            capture_output=True, timeout=5)
        assert result.returncode != 0 and b'BlockingIOError' in result.stderr
    finally:
        os.close(fd)
