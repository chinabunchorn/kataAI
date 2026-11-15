from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import errno
import os
from uuid import uuid4

import pytest

from app.csv_intake import CsvLimits
from app.local_csv_storage import CsvStorageError, publish_csv


def test_publish_valid_csv_in_private_directory(tmp_path):
    key = uuid4()
    metadata = publish_csv(tmp_path, BytesIO(b'a,b\n1,2\n'), key)
    assert metadata.columns == ('a', 'b')
    assert (tmp_path / str(key)).read_bytes() == b'a,b\n1,2\n'
    assert (tmp_path / str(key)).stat().st_mode & 0o777 == 0o600
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize('data,limits,code', [
    (b'a\n\xff', CsvLimits(), 'UNSUPPORTED_ENCODING'),
    (b'a,b\n1', CsvLimits(), 'INVALID_UPLOAD'),
    (b'a\n12', CsvLimits(max_bytes=3), 'UPLOAD_TOO_LARGE'),
])
def test_invalid_input_is_not_published(tmp_path, data, limits, code):
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(data), uuid4(), limits)
    assert exc.value.code == code
    assert exc.value.publication == 'not_published'
    assert exc.value.cleanup == 'confirmed'
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('kind', ['file', 'directory', 'symlink'])
def test_collision_preserves_existing_entry(tmp_path, kind):
    key = uuid4()
    target = tmp_path / str(key)
    if kind == 'file':
        target.write_bytes(b'original')
    elif kind == 'directory':
        target.mkdir()
    else:
        target.symlink_to('absent')
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a\n1'), key)
    assert exc.value.code == 'KEY_COLLISION'
    assert exc.value.publication == 'indeterminate'
    assert list(tmp_path.iterdir()) == [target]
    if kind == 'file':
        assert target.read_bytes() == b'original'
    elif kind == 'symlink':
        assert target.is_symlink() and os.readlink(target) == 'absent'
    else:
        assert target.is_dir()


@pytest.mark.parametrize('suffix', ['', '/', '/.', '/./'])
def test_rejects_symlink_root_even_with_trailing_slash(tmp_path, suffix):
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    alias = tmp_path / 'alias'
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(CsvStorageError):
        publish_csv(str(alias) + suffix, BytesIO(b'a'), uuid4())
    assert list(root.iterdir()) == []


def test_rejects_nonprivate_root_without_modifying_it(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), uuid4())
    assert exc.value.code == 'INVALID_ROOT'
    assert tmp_path.stat().st_mode & 0o777 == 0o755


def test_source_error_is_sanitized_and_cleans_temp(tmp_path):
    class BadSource:
        def read(self, size):
            raise RuntimeError('secret path and content')
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BadSource(), uuid4())
    assert exc.value.code == 'SOURCE_ERROR'
    assert 'secret' not in repr(exc.value)
    assert exc.value.__context__ is None
    assert list(tmp_path.iterdir()) == []


def test_short_writes_are_retried(tmp_path, monkeypatch):
    real_write = os.write
    monkeypatch.setattr(os, 'write', lambda fd, data: real_write(fd, data[:1]))
    key = uuid4()
    publish_csv(tmp_path, BytesIO(b'abc\n123'), key)
    assert (tmp_path / str(key)).read_bytes() == b'abc\n123'


def test_low_disk_cleans_temporary_file(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError(errno.ENOSPC, 'secret')
    monkeypatch.setattr(os, 'write', fail)
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), uuid4())
    assert exc.value.code == 'STORAGE_ERROR'
    assert exc.value.cleanup == 'confirmed'
    assert list(tmp_path.iterdir()) == []


def test_cleanup_failure_reports_unknown_and_retains_file(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('secret')
    monkeypatch.setattr(os, 'unlink', fail)
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), uuid4())
    assert exc.value.publication == 'indeterminate'
    assert exc.value.cleanup == 'unknown'
    assert len(list(tmp_path.iterdir())) == 2


def test_link_failure_after_side_effect_is_unknown(tmp_path, monkeypatch):
    real_link = os.link
    def fail_after(*args, **kwargs):
        real_link(*args, **kwargs)
        raise OSError('secret')
    monkeypatch.setattr(os, 'link', fail_after)
    key = uuid4()
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), key)
    assert exc.value.publication == 'indeterminate'
    assert (tmp_path / str(key)).read_bytes() == b'a'


def test_concurrent_same_key_has_one_winner(tmp_path):
    key = uuid4()
    def submit(data):
        try:
            publish_csv(tmp_path, BytesIO(data), key)
            return 'ok'
        except CsvStorageError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [b'a\n1', b'a\n2']))
    assert sorted(results) == ['KEY_COLLISION', 'ok']
    assert (tmp_path / str(key)).read_bytes() in (b'a\n1', b'a\n2')
    assert len(list(tmp_path.iterdir())) == 1


def test_staged_read_failure_is_storage_error(tmp_path, monkeypatch):
    real_fdopen = os.fdopen
    class BrokenReader:
        def __init__(self, fd, mode):
            self.stream = real_fdopen(fd, mode)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def read(self, size):
            raise OSError('sensitive')
    monkeypatch.setattr(os, 'fdopen', BrokenReader)
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), uuid4())
    assert exc.value.code == 'STORAGE_ERROR'
    assert exc.value.__context__ is None
    assert list(tmp_path.iterdir()) == []


def test_directory_fsync_failure_after_link_is_indeterminate(tmp_path, monkeypatch):
    real_fsync = os.fsync
    calls = 0
    def fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('secret')
        real_fsync(fd)
    monkeypatch.setattr(os, 'fsync', fsync)
    key = uuid4()
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), key)
    assert exc.value.publication == 'indeterminate'
    assert exc.value.cleanup == 'unknown'
    assert (tmp_path / str(key)).read_bytes() == b'a'


def test_file_fsync_failure_is_not_published(tmp_path, monkeypatch):
    def fail(fd):
        raise OSError('secret')
    monkeypatch.setattr(os, 'fsync', fail)
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), uuid4())
    assert exc.value.publication == 'not_published'
    assert exc.value.cleanup == 'unknown'
    assert list(tmp_path.iterdir()) == []


def test_non_uuid_key_and_unsupported_primitives_fail_closed(tmp_path, monkeypatch):
    import app.local_csv_storage as storage
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), '../secret')
    assert exc.value.code == 'INVALID_KEY'
    monkeypatch.setattr(storage, '_DIR_FD_SUPPORTED', False)
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), uuid4())
    assert exc.value.code == 'UNSUPPORTED_PLATFORM'
    assert list(tmp_path.iterdir()) == []


def test_eintr_write_retries(tmp_path, monkeypatch):
    real_write = os.write
    calls = 0
    def write(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise InterruptedError()
        return real_write(fd, data)
    monkeypatch.setattr(os, 'write', write)
    key = uuid4()
    publish_csv(tmp_path, BytesIO(b'a'), key)
    assert (tmp_path / str(key)).read_bytes() == b'a'


def test_temporary_name_collision_does_not_remove_existing_file(tmp_path, monkeypatch):
    import app.local_csv_storage as storage
    monkeypatch.setattr(storage.secrets, 'token_hex', lambda _: 'fixed')
    existing = tmp_path / '.stage-fixed'
    existing.write_bytes(b'original')
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), uuid4())
    assert exc.value.code == 'STORAGE_ERROR'
    assert exc.value.cleanup == 'confirmed'
    assert existing.read_bytes() == b'original'


def test_zero_byte_write_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'write', lambda fd, data: 0)
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), uuid4())
    assert exc.value.code == 'STORAGE_ERROR'
    assert exc.value.cleanup == 'confirmed'
    assert not list(tmp_path.iterdir())


def test_root_wrong_owner_fails_closed(tmp_path, monkeypatch):
    import app.local_csv_storage as storage
    real_fstat = os.fstat
    def other_owner(fd):
        info = real_fstat(fd)
        from types import SimpleNamespace
        return SimpleNamespace(st_mode=info.st_mode, st_uid=info.st_uid + 1)
    monkeypatch.setattr(storage.os, 'fstat', other_owner)
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), uuid4())
    assert exc.value.code == 'INVALID_ROOT'
    assert not list(tmp_path.iterdir())


def test_interruption_propagates_and_cleans_owned_stage(tmp_path):
    class InterruptingSource:
        def read(self, size):
            raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        publish_csv(tmp_path, InterruptingSource(), uuid4())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('truth', [True, False])
def test_hostile_source_bytes_never_reach_stage(tmp_path, monkeypatch, truth):
    calls = []

    class Hostile(bytes):
        def __len__(self):
            calls.append('len')
            return 1

        def __bool__(self):
            calls.append('bool')
            return truth

        def __eq__(self, other):
            calls.append('eq')
            return True

        def __getitem__(self, item):
            calls.append('slice')
            return b'a'

    class Source:
        def read(self, size):
            return Hostile(b'x' * 30_000)

    real_write = os.write
    writes = []

    def write(fd, data):
        writes.append(len(data))
        return real_write(fd, data)

    monkeypatch.setattr(os, 'write', write)
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, Source(), uuid4(), CsvLimits(max_bytes=3))
    assert exc.value.code == 'SOURCE_ERROR'
    assert exc.value.publication == 'not_published'
    assert exc.value.__context__ is None
    assert writes == []
    assert calls == []
    assert list(tmp_path.iterdir()) == []


def test_link_that_succeeds_then_raises_file_exists_is_indeterminate(tmp_path, monkeypatch):
    real_link = os.link

    def link_then_error(*args, **kwargs):
        real_link(*args, **kwargs)
        raise FileExistsError('secret')

    monkeypatch.setattr(os, 'link', link_then_error)
    key = uuid4()
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), key)
    assert exc.value.publication == 'indeterminate'
    assert exc.value.__context__ is None
    assert (tmp_path / str(key)).read_bytes() == b'a'
    assert list(tmp_path.iterdir()) == [tmp_path / str(key)]


def test_fdopen_failure_closes_duplicate_and_cleans_stage(tmp_path, monkeypatch):
    real_dup = os.dup
    duplicates = []

    def dup(fd):
        duplicate = real_dup(fd)
        duplicates.append(duplicate)
        return duplicate

    def fail_fdopen(*args, **kwargs):
        raise OSError('secret')

    monkeypatch.setattr(os, 'dup', dup)
    monkeypatch.setattr(os, 'fdopen', fail_fdopen)
    with pytest.raises(CsvStorageError) as exc:
        publish_csv(tmp_path, BytesIO(b'a'), uuid4())
    assert exc.value.code == 'STORAGE_ERROR'
    assert exc.value.publication == 'not_published'
    assert exc.value.cleanup == 'confirmed'
    assert exc.value.__context__ is None
    assert 'secret' not in str(exc.value)
    assert len(duplicates) == 1
    with pytest.raises(OSError) as closed:
        os.fstat(duplicates[0])
    assert closed.value.errno == errno.EBADF
    assert list(tmp_path.iterdir()) == []


def test_source_keyboard_interrupt_is_sanitized_and_cleans_stage(tmp_path):
    class Source:
        def read(self, size):
            raise KeyboardInterrupt('secret')

    with pytest.raises(KeyboardInterrupt) as exc:
        publish_csv(tmp_path, Source(), uuid4())
    assert 'secret' not in str(exc.value)
    assert exc.value.__context__ is None
    assert list(tmp_path.iterdir()) == []


def test_link_interrupt_propagates_and_preserves_possible_publication(tmp_path, monkeypatch):
    real_link = os.link

    def link_then_interrupt(*args, **kwargs):
        real_link(*args, **kwargs)
        raise KeyboardInterrupt()

    monkeypatch.setattr(os, 'link', link_then_interrupt)
    key = uuid4()
    with pytest.raises(KeyboardInterrupt):
        publish_csv(tmp_path, BytesIO(b'a'), key)
    assert (tmp_path / str(key)).read_bytes() == b'a'
    assert list(tmp_path.iterdir()) == [tmp_path / str(key)]
