"""Linux guest supervisor. Candidate execution is ONLY permitted inside Kata."""

import base64
import errno
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import time

from .contract import (
    CSV_BYTES, DIAGNOSTIC_BYTES, DIAGNOSTIC_TOTAL, EXITS, GID, REPORT_PATH,
    RESULT_BYTES, RESULT_PATH, SCRIPT_BYTES, SCRIPT_SECONDS, UID, MOUNTINFO_BYTES, ContractError,
)
from .report import make_report
from .staging import check_run_id, input_text
from .scratch import validate_scratch
from .validation import encode_json, validate_result


def _read_file(path: str, cap: int, *, nofollow: bool) -> bytes:
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC
    if nofollow:
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ContractError("RESULT_SHAPE", "regular file required")
        if metadata.st_size > cap:
            raise ContractError("RESULT_LIMIT", "file byte cap")
        chunks = bytearray()
        while len(chunks) <= cap:
            chunk = os.read(fd, min(4096, cap + 1 - len(chunks)))
            if not chunk:
                return bytes(chunks)
            chunks.extend(chunk)
        raise ContractError("RESULT_LIMIT", "file byte cap")
    finally:
        os.close(fd)


def _denied_write(path: str) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CLOEXEC)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
            return
        raise
    else:
        os.close(fd)  # No input bytes are changed by the probe.
        raise ContractError("INPUT_INVALID", "required path is writable")


def preflight() -> tuple[str, str]:
    if sys.platform != "linux" or os.getuid() != UID or os.getgid() != GID:
        raise ContractError("INPUT_INVALID", "expected Linux guest UID/GID")
    run_id = os.environ.get("KATAAI_RUN_ID", "")
    pod_uid = os.environ.get("KATAAI_POD_UID", "")
    check_run_id(run_id)
    if not pod_uid or len(pod_uid) > 128:
        raise ContractError("INPUT_INVALID", "Pod UID required")
    if Path("/var/run/secrets/kubernetes.io/serviceaccount").exists():
        raise ContractError("INPUT_INVALID", "ServiceAccount mount present")
    for name, cap in (("script.py", SCRIPT_BYTES), ("data.csv", CSV_BYTES)):
        path = Path("/inputs") / name
        # Kubernetes projected files use symlinks; require resolved target in inputs.
        try:
            if not path.resolve(strict=True).is_relative_to(Path("/inputs")):
                raise ContractError("INPUT_INVALID", "input path escaped projection")
            input_text(_read_file(str(path), cap, nofollow=False), cap)
        except (ContractError, OSError):
            raise ContractError("INPUT_INVALID", "input validation failed") from None
        _denied_write(str(path))
    _denied_write("/opt/kataai/runner.py")
    # Probe root mount without creating a file if policy is accidentally writable.
    if not os.statvfs("/").f_flag & os.ST_RDONLY:
        raise ContractError("INPUT_INVALID", "root filesystem is not read-only")
    try:
        validate_scratch(os.statvfs("/tmp"),
                         _read_file("/proc/self/mountinfo", MOUNTINFO_BYTES, nofollow=True))
    except (ContractError, OSError):
        raise ContractError("INPUT_INVALID", "guest scratch capacity is not enforced") from None
    return run_id, pod_uid


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_child() -> tuple[str, int, dict[str, bytes]]:
    retained = {"stdout": bytearray(), "stderr": bytearray()}
    observed = 0
    code = "OK"
    child = subprocess.Popen(
        [sys.executable, "-I", "-B", "/inputs/script.py"],
        cwd="/tmp", env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
                         "HOME": "/tmp", "TMPDIR": "/tmp"},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True, close_fds=True,
    )
    deadline = time.monotonic() + SCRIPT_SECONDS
    drain_deadline = None
    selector = selectors.DefaultSelector()
    try:
        for name, pipe in (("stdout", child.stdout), ("stderr", child.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while True:
            now = time.monotonic()
            if child.poll() is not None and drain_deadline is None:
                _kill_group(child)
                drain_deadline = now + 1
            if child.poll() is not None and not selector.get_map():
                break
            if now >= deadline and child.poll() is None:
                code = "RUN_TIMEOUT"
                break
            if drain_deadline is not None and now >= drain_deadline:
                break
            for key, _ in selector.select(timeout=0.05):
                try:
                    chunk = os.read(key.fileobj.fileno(), 4096)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                observed += len(chunk)
                target = retained[key.data]
                target.extend(chunk[:max(0, DIAGNOSTIC_BYTES - len(target))])
                if observed > DIAGNOSTIC_TOTAL:
                    code = "DIAGNOSTIC_LIMIT"
                    break
            if code != "OK":
                break
    finally:
        _kill_group(child)
        selector.close()
        for pipe in (child.stdout, child.stderr):
            pipe.close()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            raise ContractError("RUNNER_INTERNAL", "child could not be reaped") from None
    if code == "OK" and child.returncode != 0:
        code = "SCRIPT_FAILED"
    return code, child.returncode, {key: bytes(value) for key, value in retained.items()}


def _write_report(raw: bytes) -> None:
    # Kubelet may bind-mount this file: write in place, never rename/unlink it.
    # O_NONBLOCK and fstat prevent FIFO/device substitution from hanging the runner.
    fd = os.open(REPORT_PATH, os.O_WRONLY | os.O_CREAT | os.O_NONBLOCK |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ContractError("RUNNER_INTERNAL", "termination path not regular")
        os.ftruncate(fd, 0)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if not written:
                raise OSError("short report write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    run_id = os.environ.get("KATAAI_RUN_ID", "")
    pod_uid = os.environ.get("KATAAI_POD_UID", "")
    code, child_exit, result = "RUNNER_INTERNAL", None, None
    diagnostics = {}
    try:
        run_id, pod_uid = preflight()
        if os.path.lexists(RESULT_PATH):
            raise ContractError("INPUT_INVALID", "stale result")
        code, child_exit, diagnostics = run_child()
        if code == "OK":
            try:
                raw = _read_file(RESULT_PATH, RESULT_BYTES, nofollow=True)
            except FileNotFoundError:
                raise ContractError("RESULT_MISSING") from None
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise ContractError("RESULT_SHAPE", "result symlink") from None
                raise
            result = validate_result(raw)
    except ContractError as exc:
        code = exc.code if exc.code in EXITS else "RUNNER_INTERNAL"
    except OSError:
        code = "RUNNER_INTERNAL"
    except Exception:
        code = "RUNNER_INTERNAL"
    # These are bounded diagnostic records; never a result protocol.
    try:
        for stream, raw in diagnostics.items():
            sys.stdout.buffer.write(encode_json({"stream": stream,
                "encoding": "base64", "data": base64.b64encode(raw).decode("ascii")}) + b"\n")
        sys.stdout.buffer.flush()
        try:
            report = make_report(run_id, pod_uid, code, child_exit, result)
        except ContractError as exc:
            # A valid result can expand beyond raw/result framing limits.
            code = "RESULT_LIMIT" if code == "OK" else "RUNNER_INTERNAL"
            report = make_report(run_id, pod_uid, code, child_exit)
        _write_report(report)
    except Exception:
        return EXITS["RUNNER_INTERNAL"]
    return EXITS[code]
