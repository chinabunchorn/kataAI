"""Bounded trusted ENOSPC probe. Kata only. Never writes more than 20 MiB."""
import errno
import json
from pathlib import Path

path = Path("/tmp/scratch-fill")
written = 0
exhausted = False
try:
    with path.open("wb", buffering=0) as target:
        while written < 20 * 1024 * 1024:
            written += target.write(b"x" * 65536)
except OSError as exc:
    assert exc.errno == errno.ENOSPC, "unexpected scratch failure"
    exhausted = True
finally:
    path.unlink(missing_ok=True)
assert exhausted, "scratch capacity was not enforced within the 20 MiB probe"
assert written <= 16 * 1024 * 1024
Path("/tmp/result.json").write_text(json.dumps({"scratch_enospc": True, "bytes_written": written}), encoding="utf-8")
