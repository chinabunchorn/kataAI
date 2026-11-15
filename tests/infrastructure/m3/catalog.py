"""Team-controlled trusted test programs, staged as data; never execute on host.

All execution cases were covered by approved design revision 1. No external code
or arbitrary fixture file is accepted by the integration CLI.
"""

import json
from pathlib import Path

FIXTURES = Path(__file__).with_name("fixtures")
SALES = {"product": "Notebook", "october_units": 120,
         "november_units": 80, "change_units": -40}
TOTALS = [{"month": "October", "units": 170}, {"month": "November", "units": 125}]


def _raw(payload: bytes) -> str:
    # repr creates a Python bytes literal; this code is executed only in Kata.
    return f"from pathlib import Path\nPath('/tmp/result.json').write_bytes({payload!r})\n"


CASES = {
    "sales": (None, "OK", SALES),
    "totals": (None, "OK", TOTALS),
    "security": (None, "OK", None),
    "scratch": (None, "OK", None),
    "scratch-multifile": (None, "OK", None),
    "scratch-layout": (None, "OK", None),
    "network": (None, "OK", None),
    "invalid-json": (_raw(b"{oops}"), "RESULT_JSON", None),
    "empty": (_raw(b""), "RESULT_EMPTY", None),
    "blank": (_raw(b" \n\t"), "RESULT_EMPTY", None),
    "missing": ("# Intentionally no result\n", "RESULT_MISSING", None),
    "oversized": (_raw(b"[" + b"0," * 1024 + b"0]"), "RESULT_LIMIT", None),
    "deep": (_raw(b"[" * 17 + b"]" * 17), "RESULT_LIMIT", None),
    "collection": (_raw(json.dumps([0] * 129).encode()), "RESULT_LIMIT", None),
    "total-items": (_raw(json.dumps([[0] * 128, [0] * 127]).encode()), "RESULT_LIMIT", None),
    "scalar": (_raw(b"42"), "RESULT_SHAPE", None),
    "null": (_raw(b"null"), "RESULT_SHAPE", None),
    "utf8": (_raw(b"[\xff]"), "RESULT_ENCODING", None),
    "multiple": (_raw(b"{}\n[]"), "RESULT_JSON", None),
    "duplicate-key": (_raw(b'{"x":1,"x":2}'), "RESULT_JSON", None),
    "nan": (_raw(b"[NaN]"), "RESULT_JSON", None),
    "infinite-number": (_raw(b"[1e9999]"), "RESULT_SHAPE", None),
    "surrogate": (_raw(b'["\\ud800"]'), "RESULT_SHAPE", None),
    "syntax": ("def broken(:\n", "SCRIPT_FAILED", None),
    "runtime": ("raise RuntimeError('trusted fixture failure')\n", "SCRIPT_FAILED", None),
    "scratch-failure": ("with open('/tmp/fill', 'wb', buffering=0) as f:\n    for _ in range(320):\n        f.write(b'x' * 65536)\n", "SCRIPT_FAILED", None),
    "timeout": ("while True:\n    pass\n", "RUN_TIMEOUT", None),
    "diagnostics": ("import os\nwhile True:\n    os.write(1, b'x' * 4096)\n", "DIAGNOSTIC_LIMIT", None),
    "stderr-diagnostics": ("import os\nwhile True:\n    os.write(2, b'x' * 4096)\n", "DIAGNOSTIC_LIMIT", None),
    "result-symlink": ("import os\nos.symlink('/inputs/data.csv', '/tmp/result.json')\n", "RESULT_SHAPE", None),
    "result-fifo": ("import os\nos.mkfifo('/tmp/result.json')\n", "RESULT_SHAPE", None),
    "status-spoof": (_raw(b'{"status":"success","code":"OK"}') +
                     "raise RuntimeError('result cannot override child failure')\n", "SCRIPT_FAILED", None),
    "missing-runtime": ("# Must never execute\n", "KATA_UNAVAILABLE", None),
}

# Preserve the original probes and expectations for historical interpretation.
# They depend on the abandoned exact-capacity contract and are excluded from
# the executable release catalog; no historical failure is reclassified as OK.
LEGACY_SCRATCH_CASES = {
    name: CASES.pop(name) for name in ("scratch", "scratch-failure", "scratch-multifile")
}


def case_script(name: str) -> bytes:
    source = CASES[name][0]
    if source is None:
        return (FIXTURES / f"{name}.py").read_bytes()
    return source.encode("utf-8")
