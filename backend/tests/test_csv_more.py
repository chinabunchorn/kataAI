from io import BytesIO, StringIO
import csv

import pytest

from app.csv_intake import CsvIntakeError, CsvLimits, validate_csv


def test_byte_cap_cannot_be_configured_above_provisional_maximum():
    with pytest.raises(ValueError):
        CsvLimits(max_bytes=10_000_001)
    assert CsvLimits(max_bytes=2).max_bytes == 2


@pytest.mark.parametrize('data', [b'a\n\n', b'a,b\n\n'])
def test_blank_physical_records_rejected_at_any_width(data):
    with pytest.raises(CsvIntakeError):
        validate_csv(BytesIO(data))


def test_source_exception_cannot_spoof_error_message():
    def source():
        error = CsvIntakeError('INVALID_UPLOAD')
        error.args = ('secret data',)
        raise error
        yield b''
    with pytest.raises(CsvIntakeError) as exc:
        validate_csv(source())
    assert 'secret' not in str(exc.value)
    assert exc.value.__context__ is None


def test_explicit_quoted_empty_record_is_allowed():
    assert validate_csv(BytesIO(b'a\n""\n')).row_count == 1


@pytest.mark.parametrize('text', [
    'a,b\r\n"x,y","two\nlines"\r\n',
    '"ชื่อ","b"\n"ชา","""quoted"""\n',
    'a,b\r"x\ry",z\r',
])
def test_valid_quoted_records_match_stdlib_csv_metadata(text):
    reference = list(csv.reader(StringIO(text, newline=''), strict=True))
    payload = text.encode('utf-8')
    metadata = validate_csv(iter(payload[i:i+2] for i in range(0, len(payload), 2)))
    assert metadata.columns == tuple(reference[0])
    assert metadata.row_count == len(reference) - 1
    assert metadata.byte_size == len(payload)
