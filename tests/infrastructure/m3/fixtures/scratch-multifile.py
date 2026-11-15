"""Trusted aggregate quota probe. Kata only; at most 20 MiB across five files."""
import errno
import json
import os
from pathlib import Path

assert os.statvfs("/tmp").f_frsize * os.statvfs("/tmp").f_blocks == 16 * 1024 * 1024
paths = [Path(f"/tmp/scratch-part-{i}") for i in range(5)]
written = 0
exhausted = False
try:
    for path in paths:
        with path.open("wb", buffering=0) as target:
            for _ in range(64):
                written += target.write(b"x" * 65536)
except OSError as exc:
    assert exc.errno == errno.ENOSPC, "unexpected aggregate scratch failure"
    exhausted = True
finally:
    for path in paths:
        path.unlink(missing_ok=True)
assert exhausted, "aggregate scratch capacity was not enforced"
assert 0 < written <= 16 * 1024 * 1024
Path("/tmp/result.json").write_text(json.dumps({"scratch_enospc": True, "bytes_written": written,
                                              "multifile": True}), encoding="utf-8")
