from io import BytesIO

import pytest

from app.csv_intake import validate_csv


def test_metadata_is_derived_from_csv_bytes():
    data = 'ชื่อ,amount\nชา,3\n'.encode()
    result = validate_csv(BytesIO(data))
    assert result.columns == ('ชื่อ', 'amount')
    assert result.byte_size == len(data)
    assert result.row_count == 1


def test_incremental_input_with_quoted_multiline_and_split_bom():
    data = '\ufeffชื่อ,amount\r\n"ชา\nไทย",3\r\n'.encode()
    result = validate_csv(iter(bytes([b]) for b in data))
    assert result.columns == ('ชื่อ', 'amount')
    assert result.row_count == 1
    assert result.byte_size == len(data)


def test_byte_limit_is_inclusive_and_read_is_bounded():
    from app.csv_intake import CsvIntakeError, CsvLimits

    class Stream(BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 65536
            return super().read(size)

    assert validate_csv(Stream(b'a\n1'), CsvLimits(max_bytes=3)).byte_size == 3
    with pytest.raises(CsvIntakeError) as exc:
        validate_csv(Stream(b'a\n12'), CsvLimits(max_bytes=3))
    assert exc.value.code == 'UPLOAD_TOO_LARGE'


@pytest.mark.parametrize('data', [b'', b'\xef\xbb\xbf', b'a,\n1,2', b'a,a\n1,2',
                                  b' ,b\n1,2', b'a,b\n1', b'a\n"unfinished',
                                  b'a\n"x"z', b'a\nx"y', b'\n', b'a\n\x00'])
def test_invalid_csv_is_rejected(data):
    from app.csv_intake import CsvIntakeError

    with pytest.raises(CsvIntakeError) as exc:
        validate_csv(BytesIO(data))
    assert exc.value.code == 'INVALID_UPLOAD'


@pytest.mark.parametrize('data', [b'a\n\xff', b'a\n\xe0\xb8'])
def test_invalid_or_truncated_utf8_is_rejected_safely(data):
    from app.csv_intake import CsvIntakeError

    with pytest.raises(CsvIntakeError) as exc:
        validate_csv(iter([data]))
    assert exc.value.code == 'UNSUPPORTED_ENCODING'


def test_repeated_empty_chunks_do_not_hang():
    from itertools import repeat
    from app.csv_intake import CsvIntakeError

    with pytest.raises(CsvIntakeError):
        validate_csv(repeat(b''))


def test_limits_and_redacted_source_errors():
    from app.csv_intake import CsvIntakeError, CsvLimits

    for data, limits in [
        (b'a\n1\n2', CsvLimits(max_rows=1)),
        (b'a,b', CsvLimits(max_columns=1)),
        (b'abc', CsvLimits(max_field_chars=2)),
    ]:
        with pytest.raises(CsvIntakeError) as exc:
            validate_csv(iter([data]), limits)
        assert exc.value.code == 'INVALID_UPLOAD'
    def broken():
        raise OSError('sensitive input content')
        yield b''
    with pytest.raises(CsvIntakeError) as exc:
        validate_csv(broken())
    assert 'sensitive' not in str(exc.value)
    assert exc.value.__cause__ is None


def test_actual_decimal_ten_megabyte_boundary():
    from app.csv_intake import CsvIntakeError

    data = b'a\n' + (b'x' * 99 + b'\n') * 99_999 + b'x' * 98
    assert len(data) == 10_000_000
    result = validate_csv(BytesIO(data))
    assert result.byte_size == 10_000_000
    assert result.row_count == 100_000
    with pytest.raises(CsvIntakeError) as exc:
        validate_csv(iter([data + b'x']))
    assert exc.value.code == 'UPLOAD_TOO_LARGE'


def test_oversized_producer_chunk_is_rejected_before_decode():
    from app.csv_intake import CsvIntakeError, CsvLimits

    class Oversized:
        def read(self, size):
            return b'\xff' * 100_000
    with pytest.raises(CsvIntakeError) as exc:
        validate_csv(Oversized(), CsvLimits(max_bytes=10))
    assert exc.value.code == 'UPLOAD_TOO_LARGE'


def test_late_failure_and_stream_ownership():
    from app.csv_intake import CsvIntakeError

    stream = BytesIO(b'a\n1\n\xff')
    with pytest.raises(CsvIntakeError) as exc:
        validate_csv(stream)
    assert exc.value.code == 'UNSUPPORTED_ENCODING'
    assert not stream.closed
    good = BytesIO(b'a\n1')
    validate_csv(good)
    assert not good.closed
    def source():
        yield b'a\n1\n'
        raise OSError('secret')
    with pytest.raises(CsvIntakeError) as failure:
        validate_csv(source())
    assert failure.value.code == 'INVALID_UPLOAD'
    assert failure.value.__context__ is None


def test_csv_does_not_execute_text_or_change_stdlib_global_limit(monkeypatch):
    import builtins
    import csv

    limit = csv.field_size_limit()
    def forbidden(*args, **kwargs):
        raise AssertionError('execution attempted')
    monkeypatch.setattr(builtins, 'exec', forbidden)
    monkeypatch.setattr(builtins, 'eval', forbidden)
    result = validate_csv(iter([b'code\n__import__(os).system(command)']))
    assert result.row_count == 1
    assert csv.field_size_limit() == limit
