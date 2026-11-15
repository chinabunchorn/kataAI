import os

import pytest

from app.multipart_spool import MultipartSpool, MultipartSpoolError


def body(disposition=b'form-data; name="file"; filename="a.csv"', data=b'data', extra=b''):
    return (b'--abc\r\nContent-Disposition: ' + disposition + b'\r\n' + extra
            + b'\r\n' + data + b'\r\n--abc--\r\n')


def run(root, data, content_type='multipart/form-data; boundary=abc'):
    spool = MultipartSpool(root, content_type)
    try:
        spool.feed(data)
        name, stream = spool.finish()
        return name, stream.read()
    finally:
        spool.close()


@pytest.mark.parametrize('chunk', [1, 2, 3, 7, 32, 4096])
def test_chunk_splits(tmp_path, chunk):
    spool = MultipartSpool(tmp_path, 'multipart/form-data; boundary=abc')
    data = body(data=b'hello\r\n--abc-X\r\nworld')
    try:
        for i in range(0, len(data), chunk):
            spool.feed(data[i:i + chunk])
        assert spool.finish()[1].read() == b'hello\r\n--abc-X\r\nworld'
    finally:
        spool.close()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('data', [
    body()[:-3], body()[:-1], body() + b'x',
    body(disposition=b'form-data; name="file"; name="file"'),
    body(disposition=b'form-data; name="other"; filename="x"'),
    body(disposition=b'form-data; name="file"; filename="../a"'),
    body(disposition=b'form-data; name="file"; filename="x\\\\y"'),
    body(disposition=b'form-data; name="file"; filename="."'),
    body(extra=b'Content-Disposition: form-data; name="file"\r\n'),
    body(extra=b'X-A: ' + b'a' * 8193 + b'\r\n'),
    body()[:-9] + b'\r\n--abc\r\nContent-Disposition: form-data; name="file"\r\n\r\nx\r\n--abc--\r\n',
])
def test_invalid_inputs_cleanup(tmp_path, data):
    with pytest.raises(MultipartSpoolError):
        run(tmp_path, data)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('content_type', [
    'multipart/form-data; boundary=abc; boundary=xyz',
    'multipart/form-data; boundary=abc\r\nX: y',
    'multipart/form-data; boundary=' + 'x' * 71,
    'multipart/form-data; boundary="abc def"',
    'text/plain; boundary=abc',
])
def test_bad_content_type(tmp_path, content_type):
    with pytest.raises(MultipartSpoolError):
        MultipartSpool(tmp_path, content_type)
    assert not list(tmp_path.iterdir())


def test_filename_fallback_and_unicode(tmp_path):
    assert run(tmp_path, body(b'form-data; name="file"')) == ('upload.csv', b'data')
    assert run(tmp_path, body('form-data; name="file"; filename="ข้อมูล.csv"'.encode()))[0] == 'ข้อมูล.csv'


def test_size_caps_and_nonbytes(tmp_path):
    spool = MultipartSpool(tmp_path, 'multipart/form-data; boundary=abc')
    with pytest.raises(MultipartSpoolError, match='FILE_TOO_LARGE'):
        spool.feed(body(data=b'x' * 10_000_001))
    spool.close()
    spool = MultipartSpool(tmp_path, 'multipart/form-data; boundary=abc')
    with pytest.raises(MultipartSpoolError, match='BODY_TOO_LARGE'):
        spool.feed(b'x' * 10_065_537)
    spool.close()
    spool = MultipartSpool(tmp_path, 'multipart/form-data; boundary=abc')
    with pytest.raises(MultipartSpoolError):
        spool.feed(bytearray(b'x'))
    spool.close()


def test_no_log_or_error_disclosure(tmp_path, caplog):
    secret = b'SUPER_SECRET_DATA'
    spool = MultipartSpool(tmp_path, 'multipart/form-data; boundary=abc')
    with pytest.raises(MultipartSpoolError) as error:
        spool.feed(b'--' + secret + b'\r\n')
        spool.finish()
    spool.close()
    assert secret.decode() not in str(error.value)
    assert secret.decode() not in caplog.text


def test_root_permissions_and_symlink(tmp_path):
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    link = tmp_path / 'link'
    link.symlink_to(root, target_is_directory=True)
    for path in (str(link), str(link) + '/', str(link) + '/.'):
        with pytest.raises(MultipartSpoolError):
            MultipartSpool(path, 'multipart/form-data; boundary=abc')
    root.chmod(0o755)
    with pytest.raises(MultipartSpoolError):
        MultipartSpool(root, 'multipart/form-data; boundary=abc')


def test_cleanup_uncertainty(tmp_path, monkeypatch):
    spool = MultipartSpool(tmp_path, 'multipart/form-data; boundary=abc')
    real_unlink = os.unlink
    def fail(*args, **kwargs):
        raise OSError('SECRET')
    monkeypatch.setattr(os, 'unlink', fail)
    with pytest.raises(MultipartSpoolError, match='CLEANUP_UNCERTAIN'):
        spool.close()
    monkeypatch.setattr(os, 'unlink', real_unlink)
    for item in tmp_path.iterdir():
        item.unlink()


def test_spool_mode_and_state(tmp_path):
    spool = MultipartSpool(tmp_path, 'multipart/form-data; boundary=abc')
    path, = tmp_path.iterdir()
    assert path.name.startswith('.upload-')
    assert path.stat().st_mode & 0o777 == 0o600
    spool.feed(body())
    _, stream = spool.finish()
    assert stream.tell() == 0
    with pytest.raises(MultipartSpoolError):
        spool.feed(b'')
    spool.close()
    assert stream.closed
    with pytest.raises(MultipartSpoolError):
        spool.close()


def test_special_root_bits_and_unsupported_dirfd(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    root.mkdir(mode=0o700)
    root.chmod(0o1700)
    with pytest.raises(MultipartSpoolError, match='STORAGE_ERROR'):
        MultipartSpool(root, 'multipart/form-data; boundary=abc')
    root.chmod(0o700)
    monkeypatch.setattr(os, 'supports_dir_fd', set())
    with pytest.raises(MultipartSpoolError, match='STORAGE_ERROR'):
        MultipartSpool(root, 'multipart/form-data; boundary=abc')


@pytest.mark.parametrize('write_count', [1, 0])
def test_partial_and_zero_writes(tmp_path, write_count):
    spool = MultipartSpool(tmp_path, 'multipart/form-data; boundary=abc')
    stream = spool._stream
    class ShortWriter:
        def write(self, data):
            return stream.write(data[:write_count]) if write_count else 0
        def seek(self, *args):
            return stream.seek(*args)
        def close(self):
            return stream.close()
    spool._stream = ShortWriter()
    try:
        if write_count:
            spool.feed(body(data=b'longer content'))
            _, result = spool.finish()
            result.seek(0)
            assert stream.read() == b'longer content'
        else:
            with pytest.raises(MultipartSpoolError, match='STORAGE_ERROR'):
                spool.feed(body(data=b'longer content'))
                spool.finish()
    finally:
        spool.close()


def test_low_disk_spool_failure_is_sanitized_and_cleans_owned_file(tmp_path, monkeypatch):
    import errno

    spool = MultipartSpool(tmp_path, 'multipart/form-data; boundary=abc')
    stream = spool._stream
    assert stream is not None

    class FullDisk:
        def write(self, _data):
            raise OSError(errno.ENOSPC, 'private path and contents')

        def close(self):
            stream.close()

    monkeypatch.setattr(spool, '_stream', FullDisk())
    try:
        with pytest.raises(MultipartSpoolError) as error:
            spool.feed(body(data=b'synthetic private payload'))
            spool.finish()
        assert error.value.code == 'STORAGE_ERROR'
        assert 'private' not in str(error.value)
    finally:
        spool.close()
    assert not list(tmp_path.iterdir())


def test_cleanup_fsync_failure(tmp_path, monkeypatch):
    spool = MultipartSpool(tmp_path, 'multipart/form-data; boundary=abc')
    def fail(_fd):
        raise OSError('private error')
    monkeypatch.setattr(os, 'fsync', fail)
    with pytest.raises(MultipartSpoolError, match='CLEANUP_UNCERTAIN'):
        spool.close()
    assert not list(tmp_path.iterdir())
