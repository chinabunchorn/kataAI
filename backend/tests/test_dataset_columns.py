import os
from uuid import uuid4

import pytest

from app.csv_intake import CsvLimits
from app.dataset_columns import DatasetColumnsUnavailable, read_dataset_columns


def test_reads_only_validated_columns_from_published_csv(tmp_path):
    key = uuid4()
    (tmp_path / str(key)).write_bytes(b'\xef\xbb\xbf"first\nname",second\nprivate,row\n')
    assert read_dataset_columns(tmp_path, key) == ('first\nname', 'second')


@pytest.mark.parametrize('body, expected', [
    (b'a,b\n1,2\n', ('a', 'b')),
    (b'"a,b","c""d"\r\n1,2\r\n', ('a,b', 'c"d')),
    (b'header', ('header',)),
])
def test_valid_variants(tmp_path, body, expected):
    key = uuid4()
    (tmp_path / str(key)).write_bytes(body)
    assert read_dataset_columns(tmp_path, key) == expected


@pytest.mark.parametrize('body', [b'a,b\nsecret\n', b'a,b\n"secret,2', b'a,b\n\xff,secret', b'a,a\n1,2'])
def test_entire_file_is_validated_without_exposing_rows(tmp_path, body):
    key = uuid4()
    (tmp_path / str(key)).write_bytes(body)
    with pytest.raises(DatasetColumnsUnavailable) as exc:
        read_dataset_columns(tmp_path, key)
    assert str(exc.value) == 'Dataset columns unavailable.'
    assert exc.value.__context__ is None


def test_size_limit_is_enforced(tmp_path):
    key = uuid4()
    (tmp_path / str(key)).write_bytes(b'a\n123456\n')
    with pytest.raises(DatasetColumnsUnavailable):
        read_dataset_columns(tmp_path, key, CsvLimits(max_bytes=8))


def test_missing_and_non_uuid_key_are_unavailable(tmp_path):
    key = uuid4()
    for value in (key, '../secret', str(key)):
        with pytest.raises(DatasetColumnsUnavailable):
            read_dataset_columns(tmp_path, value)


def test_symlink_and_nonregular_files_are_unavailable(tmp_path):
    key = uuid4()
    target = tmp_path / 'other'
    target.write_bytes(b'a\n1\n')
    entry = tmp_path / str(key)
    entry.symlink_to(target)
    with pytest.raises(DatasetColumnsUnavailable):
        read_dataset_columns(tmp_path, key)
    entry.unlink()
    os.mkfifo(entry)
    with pytest.raises(DatasetColumnsUnavailable):
        read_dataset_columns(tmp_path, key)


def test_symlink_root_and_insecure_root_are_unavailable(tmp_path):
    root = tmp_path / 'root'
    root.mkdir(mode=0o700)
    key = uuid4()
    (root / str(key)).write_bytes(b'a\n1\n')
    link = tmp_path / 'link'
    link.symlink_to(root, target_is_directory=True)
    for path in (link, str(link) + '/', str(link) + '/.'):
        with pytest.raises(DatasetColumnsUnavailable):
            read_dataset_columns(path, key)
    root.chmod(0o755)
    with pytest.raises(DatasetColumnsUnavailable):
        read_dataset_columns(root, key)


def test_close_failure_is_sanitized(tmp_path, monkeypatch):
    key = uuid4()
    (tmp_path / str(key)).write_bytes(b'a\n1\n')
    close = os.close
    def failing_close(fd):
        close(fd)
        raise OSError('private information')
    monkeypatch.setattr(os, 'close', failing_close)
    with pytest.raises(DatasetColumnsUnavailable) as exc:
        read_dataset_columns(tmp_path, key)
    assert 'private information' not in str(exc.value)
