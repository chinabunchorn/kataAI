"""Read-only trusted scratch feasibility observations, plus a 10 s hold. Kata only."""
import json
import os
import time
from pathlib import Path

stats = os.statvfs("/tmp")
mounts = [line for line in Path("/proc/self/mountinfo").read_text().splitlines()
          if line.split()[4] == "/tmp"]
print("scratch mountinfo: " + " | ".join(mounts)[:2048])
Path("/tmp/result.json").write_text(json.dumps({
    "scratch_reported_bytes": stats.f_frsize * stats.f_blocks,
    "scratch_available_bytes": stats.f_frsize * stats.f_bavail,
    "mountinfo": [line[:512] for line in mounts[:1]],
}), encoding="utf-8")
time.sleep(10)
