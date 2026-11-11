"""Bounded kubectl transport for an explicitly selected trusted-operator context."""

import json
import re
import shlex
import subprocess
import threading


def bounded_command(argv: list[str], payload: bytes | None = None,
                    timeout: int = 25) -> bytes:
    """Bound both pipes while draining; no capture_output/communicate buffering."""
    process = subprocess.Popen(argv, stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    exceeded = threading.Event()
    buffers = [bytearray(), bytearray()]

    def drain(pipe, target, cap):
        try:
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    break
                remaining = max(0, cap - len(target))
                target.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    exceeded.set()
                    process.kill()
                    break
        finally:
            pipe.close()

    readers = [threading.Thread(target=drain, args=(process.stdout, buffers[0], 1024 * 1024), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, buffers[1], 16384), daemon=True)]
    for thread in readers:
        thread.start()

    def write_input():
        try:
            process.stdin.write(payload)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    writer = None
    if payload is not None:
        writer = threading.Thread(target=write_input, daemon=True)
        writer.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
        raise RuntimeError("bounded kubectl request timed out; remote outcome may be uncertain") from None
    finally:
        for thread in readers:
            thread.join(timeout=2)
        if writer:
            writer.join(timeout=2)
    if any(thread.is_alive() for thread in readers) or exceeded.is_set():
        raise RuntimeError("kubectl response limit exceeded")
    if process.returncode:
        # API diagnostics can contain staged code: preserve only bounded diagnostics
        # locally and never tokens/kubeconfig. CLI does not request Secret objects.
        raise RuntimeError("kubectl failed: " + bytes(buffers[1]).decode("utf-8", errors="replace")[:2000])
    return bytes(buffers[0])


class Kube:
    def __init__(self, kubeconfig: str, context: str):
        if not kubeconfig or not context:
            raise ValueError("explicit kubeconfig and context required")
        self.prefix = ["kubectl", "--kubeconfig", kubeconfig, "--context", context,
                       "--request-timeout=20s"]

    def argv(self, *args: str) -> list[str]:
        return self.prefix + list(args)

    def call(self, *args: str, body: dict | None = None) -> object:
        payload = None if body is None else json.dumps(body, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
        raw = bounded_command(self.argv(*args), payload)
        return json.loads(raw) if raw.strip() else None

    def get(self, resource: str, name: str | None = None):
        args = ["get", resource]
        if name:
            args.extend([name, "--ignore-not-found=true"])
        return self.call(*args, "-n", "kata-lab", "-o", "json")

    def delete_uid(self, api_path: str, uid: str):
        # Raw API DeleteOptions supplies an actual UID precondition, unlike labels.
        return self.call("delete", "--raw", api_path, "-f", "-", body={
            "apiVersion": "v1", "kind": "DeleteOptions",
            "preconditions": {"uid": uid}, "propagationPolicy": "Foreground",
        })


class SSHKube(Kube):
    """Operator-only test transport using existing SSH authorization.

    No new kubeconfig, bearer token or RBAC is copied/provisioned. This is a
    disposable lab harness option, not the future M4 application transport.
    """

    def __init__(self, host: str):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,100}", host):
            raise ValueError("SSH host must be an existing simple host alias")
        self.host = host

    def argv(self, *args: str) -> list[str]:
        return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", self.host,
                shlex.join(["kubectl", "--request-timeout=20s", *args])]
