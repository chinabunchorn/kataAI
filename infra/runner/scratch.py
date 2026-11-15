"""Check guest scratch suitability before candidate execution."""

import os

from .contract import MOUNTINFO_BYTES, ContractError


def validate_scratch(stats: os.statvfs_result, mountinfo: bytes) -> None:
    """Validate the filesystem actually mounted in this guest, not YAML intent.

    Require a distinct writable tmpfs at /tmp with usable space. The existing
    unmodified Kata runtime does not guarantee an exact guest capacity; the
    workload's emptyDir sizeLimit is not a verified guest quota.
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
                mounts.append((after.split()[0], fields[5].split(",")))
        if len(mounts) != 1 or mounts[0][0] != "tmpfs" or "rw" not in mounts[0][1] or "ro" in mounts[0][1]:
            raise ValueError
        if stats.f_frsize <= 0 or stats.f_blocks <= 0:
            raise ValueError
        if stats.f_bavail <= 0:
            raise ValueError
        if stats.f_flag & os.ST_RDONLY:
            raise ValueError
    except (ValueError, UnicodeError):
        raise ContractError("INPUT_INVALID", "guest requires a writable tmpfs with available space at /tmp") from None
