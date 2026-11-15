"""Private local CSV publication; not exposed through HTTP."""

import os
import secrets
import stat
from uuid import UUID

from .csv_intake import CsvIntakeError, CsvLimits, validate_csv

_DIR_FD_SUPPORTED = all(fn in os.supports_dir_fd for fn in (os.open, os.link, os.unlink))
_LINK_NOFOLLOW_SUPPORTED = os.link in os.supports_follow_symlinks


class _CheckedReader:
    def __init__(self, stream):
        self.stream = stream
        self.failed = False

    def read(self, size):
        try:
            return self.stream.read(size)
        except Exception:
            self.failed = True
            raise


class CsvStorageError(Exception):
    """Sanitized failure, with publication and temporary cleanup state."""

    def __init__(self, code, publication='not_published', cleanup='confirmed'):
        self.code = code
        self.publication = publication
        self.cleanup = cleanup
        super().__init__(code)


def publish_csv(root, source, key, limits=CsvLimits()):
    """Validate staged bytes and atomically link them to a nonexisting UUID name."""
    if not isinstance(key, UUID):
        raise CsvStorageError('INVALID_KEY')
    required = ('O_DIRECTORY', 'O_NOFOLLOW')
    if (any(not hasattr(os, name) for name in required)
            or not _DIR_FD_SUPPORTED or not _LINK_NOFOLLOW_SUPPORTED):
        raise CsvStorageError('UNSUPPORTED_PLATFORM')
    directory = fd = duplicate = None
    temp = None
    published = False
    linking = False
    failure = None
    metadata = None
    interrupted = False
    try:
        directory = os.open(os.path.normpath(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(directory)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o7077:
            raise CsvStorageError('INVALID_ROOT')
        temp = '.stage-' + secrets.token_hex(16)
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        os.fchmod(fd, 0o600)
        size = 0
        while True:
            try:
                chunk = source.read(min(65536, limits.max_bytes - size + 1))
            except Exception:
                raise CsvStorageError('SOURCE_ERROR') from None
            if type(chunk) is not bytes:
                raise CsvStorageError('SOURCE_ERROR')
            if not chunk:
                break
            if len(chunk) > limits.max_bytes - size:
                raise CsvStorageError('UPLOAD_TOO_LARGE')
            size += len(chunk)
            view = memoryview(chunk)
            while view:
                try:
                    count = os.write(fd, view)
                except InterruptedError:
                    continue
                if count <= 0:
                    raise OSError('short write')
                view = view[count:]
        os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        duplicate = os.dup(fd)
        staged = os.fdopen(duplicate, 'rb')
        duplicate = None  # The stream now owns the duplicate.
        with staged:
            reader = _CheckedReader(staged)
            try:
                metadata = validate_csv(reader, limits)
            except CsvIntakeError:
                if reader.failed:
                    raise CsvStorageError('STORAGE_ERROR') from None
                raise
        linking = True
        os.link(temp, str(key), src_dir_fd=directory, dst_dir_fd=directory,
                follow_symlinks=False)
        published = True
        linking = False
    except CsvIntakeError as exc:
        failure = (exc.code, 'not_published')
    except CsvStorageError as exc:
        failure = (exc.code, 'not_published')
    except FileExistsError:
        failure = ('KEY_COLLISION', 'indeterminate') if linking else ('STORAGE_ERROR', 'not_published')
    except Exception:
        failure = ('STORAGE_ERROR', 'indeterminate' if linking or published else 'not_published')
    except KeyboardInterrupt:
        interrupted = True
    finally:
        cleanup = 'confirmed'
        if duplicate is not None:
            try:
                os.close(duplicate)
            except OSError:
                failure = failure or ('STORAGE_ERROR', 'not_published')
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                failure = failure or ('STORAGE_ERROR', 'indeterminate' if published else 'not_published')
        if temp is not None and fd is not None and directory is not None:
            try:
                os.unlink(temp, dir_fd=directory)
                os.fsync(directory)
            except OSError:
                cleanup = 'unknown'
                if published:
                    failure = (failure[0] if failure else 'STORAGE_ERROR', 'indeterminate')
                else:
                    failure = failure or ('STORAGE_ERROR', 'not_published')
        if directory is not None:
            try:
                os.close(directory)
            except OSError:
                failure = failure or ('STORAGE_ERROR', 'indeterminate' if published else 'not_published')
    if interrupted:
        raise KeyboardInterrupt()
    if failure:
        raise CsvStorageError(*failure, cleanup)
    return metadata
