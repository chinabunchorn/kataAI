import traceback

import pytest

from app.csv_intake import CsvIntakeError, CsvLimits, validate_csv


@pytest.mark.parametrize('stage', ['iter', 'next', 'read'])
@pytest.mark.parametrize('source_code', ['UNSUPPORTED_ENCODING', 'SECRET_CODE'])
def test_source_csv_error_is_never_trusted(stage, source_code):
    original = CsvIntakeError('UPLOAD_TOO_LARGE')
    original.args = ('SECRET_MESSAGE',)
    original.code = source_code

    class Source:
        def __iter__(self):
            if stage == 'iter':
                raise original
            return self

        def __next__(self):
            raise original

    class Reader:
        def read(self, size):
            raise original

    with pytest.raises(CsvIntakeError) as failure:
        validate_csv(Reader() if stage == 'read' else Source())
    assert failure.value is not original
    assert failure.value.code == 'INVALID_UPLOAD'
    assert failure.value.__context__ is None
    assert 'SECRET_MESSAGE' not in ''.join(traceback.format_exception(failure.value))


@pytest.mark.parametrize(('payload', 'max_bytes', 'expected'), [
    (b'a\n"x"z\n\xff', 100, 'UNSUPPORTED_ENCODING'),
    (b'a\nx"y' + b'z' * 10, 8, 'UPLOAD_TOO_LARGE'),
    (b'a\n"x"z\n\xe0\xb8', 100, 'UNSUPPORTED_ENCODING'),
    (b'a\n\xff' + b'z' * 10, 8, 'UPLOAD_TOO_LARGE'),
])
def test_classification_does_not_depend_on_chunk_boundaries(payload, max_bytes, expected):
    chunkings = [[payload], [bytes([b]) for b in payload]]
    chunkings.extend([payload[:i], payload[i:]] for i in range(1, len(payload)))
    for chunks in chunkings:
        with pytest.raises(CsvIntakeError) as failure:
            validate_csv(iter(chunks), CsvLimits(max_bytes=max_bytes))
        assert failure.value.code == expected


def test_empty_chunks_are_limited_in_total():
    def chunks():
        for _ in range(1025):
            yield b''
            yield b'a'
    with pytest.raises(CsvIntakeError) as failure:
        validate_csv(chunks())
    assert failure.value.code == 'INVALID_UPLOAD'


def test_source_failure_after_syntax_or_encoding_error_is_generic():
    for prefix in (b'a\nx"y', b'a\n\xff'):
        def chunks():
            yield prefix
            raise OSError('SECRET_IO')
        with pytest.raises(CsvIntakeError) as failure:
            validate_csv(chunks())
        assert failure.value.code == 'INVALID_UPLOAD'
        assert 'SECRET_IO' not in ''.join(traceback.format_exception(failure.value))
