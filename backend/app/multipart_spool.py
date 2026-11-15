"""Bounded, private multipart staging; this module does not expose an endpoint.

The existing root and its ancestors must be trusted. POSIX mode/owner checks do
not exclude ACLs, inherited ACLs, or same-UID access. Limits do not bound caller
allocations, concurrent requests, runtime, or aggregate disk use. The caller
must close exactly once after the returned stream is no longer needed, including
on failures. Cleanup uncertainty raises MultipartSpoolError('CLEANUP_UNCERTAIN');
there is no crash recovery. No published name is ever removed here.
"""
import logging
import os
import re
import secrets
import stat
import unicodedata

from python_multipart.multipart import MultipartParser


class MultipartSpoolError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


_TOKEN = rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+"
_OPTION = re.compile(rb'\s*;\s*(' + _TOKEN + rb')\s*=\s*(?:"([^"\\\r\n]*)"|(' + _TOKEN + rb'))')


def _options(value):
    if b'\r' in value or b'\n' in value or any(c < 32 and c != 9 for c in value):
        raise MultipartSpoolError('INVALID_MULTIPART')
    primary, sep, rest = value.partition(b';')
    options = {}
    remaining = (sep + rest) if sep else b''
    while remaining:
        match = _OPTION.match(remaining)
        if not match:
            raise MultipartSpoolError('INVALID_MULTIPART')
        key = match.group(1).lower()
        if key in options:
            raise MultipartSpoolError('INVALID_MULTIPART')
        options[key] = match.group(2) if match.group(2) is not None else match.group(3)
        remaining = remaining[match.end():]
    return primary.strip().lower(), options


class MultipartSpool:
    """Feed exact bytes, finish once to obtain (name, seekable binary stream).

    Exactly one file part is accepted. A missing filename uses 'upload.csv'.
    Only an optional CRLF may follow the closing delimiter. All bytes, including
    epilogue, count against 10,065,536; file data is limited to 10,000,000.
    Calls after an error are invalid except close(). Exceptions never include
    supplied bytes or OS error text. close() closes the returned stream itself.
    """
    def __init__(self, root, content_type):
        self._dir = self._stream = self._name = None
        self._closed = self._failed = self._finished = False
        self._raw = self._size = self._parts = self._header_bytes = 0
        self._ended = self._part_ended = False
        self._headers = {}
        self._field = self._value = b''
        self._tail = b''
        self._epilogue = b''
        try:
            if not isinstance(content_type, str) or len(content_type) > 8192:
                raise MultipartSpoolError('INVALID_MULTIPART')
            primary, opts = _options(content_type.encode('ascii'))
            boundary = opts.get(b'boundary', b'')
            if (primary != b'multipart/form-data' or set(opts) != {b'boundary'}
                    or not 1 <= len(boundary) <= 70
                    or not re.fullmatch(rb"[0-9A-Za-z'()+_,./:=?-]+", boundary)):
                raise MultipartSpoolError('INVALID_MULTIPART')
            if (not all(hasattr(os, attr) for attr in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_CLOEXEC'))
                    or os.open not in os.supports_dir_fd or os.unlink not in os.supports_dir_fd):
                raise MultipartSpoolError('STORAGE_ERROR')
            path = os.fspath(root)
            if not isinstance(path, str):
                raise MultipartSpoolError('STORAGE_ERROR')
            path = path.rstrip('/')
            if not path or path.rsplit('/', 1)[-1] in ('.', '..'):
                raise MultipartSpoolError('STORAGE_ERROR')
            self._dir = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            info = os.fstat(self._dir)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o7077:
                raise MultipartSpoolError('STORAGE_ERROR')
            for _ in range(16):
                name = '.upload-' + secrets.token_hex(24)
                try:
                    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=self._dir)
                    self._name = name
                    break
                except FileExistsError:
                    continue
            else:
                raise MultipartSpoolError('STORAGE_ERROR')
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o7077:
                    raise MultipartSpoolError('STORAGE_ERROR')
                self._stream = os.fdopen(fd, 'w+b', buffering=0)
            except BaseException:
                os.close(fd)
                raise
            callbacks = {f'on_{name}': getattr(self, f'_{name}') for name in (
                'part_begin', 'header_field', 'header_value', 'header_end', 'headers_finished',
                'part_data', 'part_end', 'end')}
            self._parser = MultipartParser(boundary, callbacks, max_header_size=8192, max_header_count=100)
            self._parser.logger = logging.Logger('multipart_spool.silent', level=logging.CRITICAL + 1)
            self._parser.logger.disabled = True
            self._marker = b'\r\n--' + boundary + b'--'
            self._opening = b'--' + boundary + b'\r\n'
            self._header_scan = b''
            self._header_done = False
        except BaseException as exc:
            try:
                self.close()
            except MultipartSpoolError:
                raise
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(exc, MultipartSpoolError):
                raise
            code = 'INVALID_MULTIPART' if isinstance(exc, UnicodeError) else 'STORAGE_ERROR'
            raise MultipartSpoolError(code) from None

    def _part_begin(self):
        self._parts += 1
        if self._parts != 1:
            raise MultipartSpoolError('INVALID_MULTIPART')

    def _header_field(self, data, start, end):
        self._header_bytes += end - start
        if self._header_bytes > 8192:
            raise MultipartSpoolError('INVALID_MULTIPART')
        self._field += data[start:end]

    def _header_value(self, data, start, end):
        self._header_bytes += end - start
        if self._header_bytes > 8192:
            raise MultipartSpoolError('INVALID_MULTIPART')
        self._value += data[start:end]

    def _header_end(self):
        self._header_bytes += 4
        if self._header_bytes > 8192:
            raise MultipartSpoolError('INVALID_MULTIPART')
        field = self._field.lower()
        if field in self._headers:
            raise MultipartSpoolError('INVALID_MULTIPART')
        self._headers[field] = self._value
        self._field = self._value = b''

    def _headers_finished(self):
        if b'content-disposition' not in self._headers:
            raise MultipartSpoolError('INVALID_MULTIPART')
        primary, opts = _options(self._headers[b'content-disposition'])
        if primary != b'form-data' or opts.get(b'name') != b'file' or set(opts) - {b'name', b'filename'}:
            raise MultipartSpoolError('INVALID_MULTIPART')
        try:
            name = opts.get(b'filename', b'upload.csv').decode('utf-8')
        except UnicodeDecodeError:
            raise MultipartSpoolError('INVALID_MULTIPART') from None
        if (not 1 <= len(name) <= 255 or name != name.strip() or name in ('.', '..')
                or '/' in name or '\\' in name or any(unicodedata.category(c).startswith('C') for c in name)):
            raise MultipartSpoolError('INVALID_MULTIPART')
        self._display_name = name

    def _part_data(self, data, start, end):
        self._size += end - start
        if self._size > 10_000_000:
            raise MultipartSpoolError('FILE_TOO_LARGE')
        view = memoryview(data)[start:end]
        while view:
            count = self._stream.write(view)
            if not isinstance(count, int) or count <= 0 or count > len(view):
                raise MultipartSpoolError('STORAGE_ERROR')
            view = view[count:]

    def _part_end(self):
        self._part_ended = True

    def _end(self):
        self._ended = True

    def _write_parser(self, data):
        if data and self._parser.write(data) != len(data):
            raise MultipartSpoolError('INVALID_MULTIPART')

    def feed(self, data):
        if self._closed or self._failed or self._finished:
            raise MultipartSpoolError('INVALID_STATE')
        try:
            if type(data) is not bytes:
                raise MultipartSpoolError('INVALID_MULTIPART')
            self._raw += len(data)
            if self._raw > 10_065_536:
                raise MultipartSpoolError('BODY_TOO_LARGE')
            for offset in range(0, len(data), 4096):
                incoming = data[offset:offset + 4096]
                if not self._header_done:
                    self._header_scan += incoming
                    prefix = self._header_scan[:len(self._opening)]
                    if not self._opening.startswith(prefix):
                        raise MultipartSpoolError('INVALID_MULTIPART')
                    end = self._header_scan.find(b'\r\n\r\n', len(self._opening))
                    if end >= 0:
                        if end + 4 - len(self._opening) > 8192:
                            raise MultipartSpoolError('INVALID_MULTIPART')
                        self._header_done = True
                        self._header_scan = b''
                    elif len(self._header_scan) - len(self._opening) > 8192:
                        raise MultipartSpoolError('INVALID_MULTIPART')
                chunk = self._tail + incoming
                self._tail = b''
                if self._ended:
                    self._epilogue += chunk
                    if not b'\r\n'.startswith(self._epilogue):
                        raise MultipartSpoolError('INVALID_MULTIPART')
                    continue
                while chunk:
                    pos = chunk.find(self._marker)
                    if pos < 0:
                        keep = min(len(chunk), len(self._marker) - 1)
                        self._write_parser(chunk[:-keep] if keep else chunk)
                        self._tail = chunk[-keep:] if keep else b''
                        break
                    self._write_parser(chunk[:pos + len(self._marker)])
                    chunk = chunk[pos + len(self._marker):]
                    if self._ended:
                        self._epilogue += chunk
                        if not b'\r\n'.startswith(self._epilogue):
                            raise MultipartSpoolError('INVALID_MULTIPART')
                        break
        except Exception as exc:
            self._failed = True
            if isinstance(exc, MultipartSpoolError):
                raise
            raise MultipartSpoolError('STORAGE_ERROR' if isinstance(exc, OSError) else 'INVALID_MULTIPART') from None

    def finish(self):
        if self._closed or self._failed or self._finished:
            raise MultipartSpoolError('INVALID_STATE')
        try:
            self._write_parser(self._tail)
            self._tail = b''
            if not self._ended or not self._part_ended or self._parts != 1 or self._epilogue not in (b'', b'\r\n'):
                raise MultipartSpoolError('INVALID_MULTIPART')
            self._stream.seek(0)
            self._finished = True
            return self._display_name, self._stream
        except Exception as exc:
            self._failed = True
            if isinstance(exc, MultipartSpoolError):
                raise
            raise MultipartSpoolError('STORAGE_ERROR' if isinstance(exc, OSError) else 'INVALID_MULTIPART') from None

    def close(self):
        if self._closed:
            raise MultipartSpoolError('INVALID_STATE')
        self._closed = True
        uncertain = False
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                uncertain = True
        if self._name is not None and self._dir is not None:
            try:
                os.unlink(self._name, dir_fd=self._dir)
                os.fsync(self._dir)
            except OSError:
                uncertain = True
        if self._dir is not None:
            try:
                os.close(self._dir)
            except OSError:
                uncertain = True
        if uncertain:
            raise MultipartSpoolError('CLEANUP_UNCERTAIN')
