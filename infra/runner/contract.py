"""Approved M3 v1 constants. This module never executes candidate code."""

VERSION = "0.1.0"
PROTOCOL = "kataai.runner.v1"
BASE_IMAGE = "docker.io/library/python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b"
NAMESPACE = "kata-lab"
RUNTIME_CLASS = "kata-qemu-runtime-rs"
CONTAINER = "runner"
RUN_LABEL = "kataai-m3-run"
INPUTS = "/inputs"
RESULT_PATH = "/tmp/result.json"
REPORT_PATH = "/tmp/runner-termination.json"
COMMAND = ["python3", "-I", "-B", "/opt/kataai/runner.py"]
SCRIPT_BYTES = 32 * 1024
CSV_BYTES = 512 * 1024
CONFIGMAP_BYTES = 768 * 1024
RESULT_BYTES = 2048
REPORT_BYTES = 3072
MAX_DEPTH = 16
MAX_ITEMS = 128
TOTAL_ITEMS = 256
DIAGNOSTIC_BYTES = 8192
DIAGNOSTIC_TOTAL = 16384
SCRIPT_SECONDS = 30
JOB_SECONDS = 120
UID = GID = 10001

EXITS = {
    "OK": 0,
    "SCRIPT_FAILED": 10,
    "RESULT_MISSING": 11,
    "RESULT_EMPTY": 12,
    "RESULT_ENCODING": 13,
    "RESULT_JSON": 14,
    "RESULT_SHAPE": 15,
    "RESULT_LIMIT": 16,
    "RUN_TIMEOUT": 17,
    "DIAGNOSTIC_LIMIT": 18,
    "INPUT_INVALID": 19,
    "RUNNER_INTERNAL": 20,
}


class ContractError(ValueError):
    """Stable identifier, with bounded trusted detail; no guest text required."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code + (": " + detail if detail else ""))
        self.code = code
