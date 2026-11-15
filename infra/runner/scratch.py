"""Fail closed on an ineffective guest scratch mount before candidate execution."""

import os

from .contract import MOUNTINFO_BYTES, SCRATCH_BYTES, ContractError


def validate_scratch(stats: os.statvfs_result, mountinfo: bytes) -> None:
    """Validate the filesystem actually mounted in this guest, not YAML intent.

    A runtime fix must supply the full approved 16 MiB tmpfs. No env/argument can
    bypass this check. Free space is not capacity; existing files cannot make an
    oversized filesystem pass by reducing its available space.
    """
    if len(mountinfo) > MOUNTINFO_BYTES:
        raise ContractError("INPUT_INVALID", "mountinfo cap")
    try:
        lines = mountinfo.decode("utf-8", errors="strict").splitlines()
        mounts = []
        for line in lines:
            before, separator, after = line.partition(" - ")
            fields = before.split()
            if len(fields) >= 6 and fields[4] == "/tmp":
                if not separator or not after.split():
                    raise ValueError
                mounts.append(after.split()[0])
        if mounts != ["tmpfs"]:
            raise ValueError
        if stats.f_frsize <= 0 or stats.f_blocks <= 0:
            raise ValueError
        if stats.f_frsize * stats.f_blocks != SCRATCH_BYTES:
            raise ValueError
        if stats.f_flag & os.ST_RDONLY:
            raise ValueError
    except (ValueError, UnicodeError):
        raise ContractError("INPUT_INVALID", "guest requires a writable 16 MiB tmpfs at /tmp") from None
