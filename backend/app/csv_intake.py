"""Bounded, provisional CSV validation; no storage or execution side effects."""

import codecs
from dataclasses import dataclass
from typing import BinaryIO, Iterable, Literal


@dataclass(frozen=True)
class CsvLimits:
    max_bytes: int = 10_000_000
    max_rows: int = 100_000
    max_columns: int = 256
    max_field_chars: int = 65_536

    def __post_init__(self) -> None:
        for value in (self.max_bytes, self.max_rows, self.max_columns, self.max_field_chars):
            if type(value) is not int or value < 1:
                raise ValueError('CSV limits must be positive integers.')
        if self.max_bytes > 10_000_000:
            raise ValueError('CSV byte limit cannot exceed 10,000,000.')


@dataclass(frozen=True)
class CsvMetadata:
    columns: tuple[str, ...]
    byte_size: int
    row_count: int


class CsvIntakeError(Exception):
    def __init__(self, code: Literal['INVALID_UPLOAD', 'UPLOAD_TOO_LARGE', 'UNSUPPORTED_ENCODING']):
        self.code = code
        super().__init__({'INVALID_UPLOAD': 'Invalid CSV upload.',
                          'UPLOAD_TOO_LARGE': 'CSV upload is too large.',
                          'UNSUPPORTED_ENCODING': 'CSV must be UTF-8.'}[code])


def validate_csv(source: BinaryIO | Iterable[bytes], limits: CsvLimits = CsvLimits()) -> CsvMetadata:
    """Consume binary input once, returning only validated header and counts."""
    decoder = codecs.getincrementaldecoder('utf-8-sig')('strict')
    size = 0
    header: tuple[str, ...] | None = None
    fields: list[str] = []
    field: list[str] = []
    field_length = 0
    width = 0
    rows = 0
    state = 'start'  # start, plain, quoted, closed
    active = False
    skip_lf = False

    def finish_field() -> None:
        nonlocal width, field_length, field, state
        width += 1
        if width > limits.max_columns:
            raise CsvIntakeError('INVALID_UPLOAD')
        if header is None:
            fields.append(''.join(field))
        field = []
        field_length = 0
        state = 'start'

    def finish_row() -> None:
        nonlocal header, width, rows, active
        finish_field()
        if header is None:
            if any(not name.strip() for name in fields) or len(set(fields)) != len(fields):
                raise CsvIntakeError('INVALID_UPLOAD')
            header = tuple(fields)
            fields.clear()
        else:
            if width != len(header):
                raise CsvIntakeError('INVALID_UPLOAD')
            rows += 1
            if rows > limits.max_rows:
                raise CsvIntakeError('INVALID_UPLOAD')
        width = 0
        active = False

    def add_char(char: str) -> None:
        nonlocal field_length
        field_length += 1
        if field_length > limits.max_field_chars:
            raise CsvIntakeError('INVALID_UPLOAD')
        if header is None:
            field.append(char)

    def consume(text: str) -> None:
        nonlocal state, active, skip_lf
        for char in text:
            if char == '\x00':
                raise CsvIntakeError('INVALID_UPLOAD')
            if skip_lf:
                skip_lf = False
                if char == '\n':
                    continue
            if state == 'quoted':
                if char == '"':
                    state = 'closed'
                else:
                    add_char(char)
                continue
            if state == 'closed' and char == '"':
                add_char(char)
                state = 'quoted'
                continue
            if char in '\r\n':
                if not active and not width:
                    raise CsvIntakeError('INVALID_UPLOAD')
                finish_row()
                skip_lf = char == '\r'
            elif char == ',':
                finish_field()
                active = True
            elif state == 'closed':
                raise CsvIntakeError('INVALID_UPLOAD')
            elif char == '"':
                if state != 'start':
                    raise CsvIntakeError('INVALID_UPLOAD')
                state = 'quoted'
                active = True
            else:
                add_char(char)
                state = 'plain'
                active = True

    invalid = False
    bad_encoding = False
    code = 'INVALID_UPLOAD'
    try:
        if hasattr(source, 'read'):
            def chunks():
                while True:
                    chunk = source.read(65_536)
                    if chunk == b'':
                        break
                    yield chunk
            stream = chunks()
        else:
            stream = iter(source)
        empty_chunks = 0
        for chunk in stream:
            if not isinstance(chunk, bytes):
                break
            if not chunk:
                empty_chunks += 1
                if empty_chunks > 1024:
                    break
            if len(chunk) > limits.max_bytes - size:
                code = 'UPLOAD_TOO_LARGE'
                break
            size += len(chunk)
            # Continue scanning after syntax errors for higher-priority errors.
            for offset in range(0, len(chunk), 65_536):
                if bad_encoding:
                    break
                try:
                    text = decoder.decode(chunk[offset:offset + 65_536])
                except UnicodeDecodeError:
                    bad_encoding = True
                    break
                if not invalid:
                    try:
                        consume(text)
                    except CsvIntakeError:
                        invalid = True
        else:
            if not bad_encoding:
                try:
                    text = decoder.decode(b'', final=True)
                except UnicodeDecodeError:
                    bad_encoding = True
                else:
                    if not invalid:
                        try:
                            consume(text)
                            if state == 'quoted':
                                raise CsvIntakeError('INVALID_UPLOAD')
                            if active or width:
                                finish_row()
                            if header is None:
                                raise CsvIntakeError('INVALID_UPLOAD')
                        except CsvIntakeError:
                            invalid = True
            if bad_encoding:
                code = 'UNSUPPORTED_ENCODING'
            elif not invalid and header is not None:
                return CsvMetadata(header, size, rows)
    except Exception:
        # Source exceptions, including CsvIntakeError, are never trusted.
        code = 'INVALID_UPLOAD'
    # Raise outside the handler: source exceptions and their data do not escape.
    raise CsvIntakeError(code)
