"""Bounded trusted observations, not a complete security certification. Kata only."""
import errno
import json
import os
import platform
import time
from pathlib import Path

assert os.getuid() == os.getgid() == 10001
for path in ("/inputs/script.py", "/inputs/data.csv", "/opt/kataai/runner.py"):
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND)
    except OSError as exc:
        assert exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS)
    else:
        os.close(fd)
        raise AssertionError("required write denial failed")
assert os.statvfs("/").f_flag & os.ST_RDONLY
assert not Path("/var/run/secrets/kubernetes.io/serviceaccount").exists()
for path in (Path("/root/.kube"), Path("/home/runner/.kube")):
    try:
        assert not path.exists()
    except PermissionError:
        pass  # Inaccessible protected homes reveal no credential contents.
assert not any(name in os.environ for name in (
    "KUBECONFIG", "KUBERNETES_SERVICE_HOST", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"))
# Candidate receives the explicitly minimal environment only.
assert set(os.environ) <= {"PATH", "LANG", "HOME", "TMPDIR", "LC_CTYPE"}
mounts = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
assert "/var/run/secrets" not in mounts and "/.kube" not in mounts
assert sorted(path.name for path in Path("/inputs").iterdir() if not path.name.startswith("..")) == ["data.csv", "script.py"]
probe = Path("/tmp/scratch-probe")
probe.write_bytes(b"trusted scratch probe")
assert probe.read_bytes() == b"trusted scratch probe"
probe.unlink()
Path("/tmp/result.json").write_text(json.dumps({
    "uid": os.getuid(), "gid": os.getgid(), "guest_kernel": platform.release(),
    "input_write_denied": True, "root_readonly": True,
    "serviceaccount_absent": True, "known_credentials_absent": True,
    "scratch_writable": True,
}), encoding="utf-8")
# Allow an operator to collect live Pod/sandbox/QEMU correlation.
time.sleep(10)
