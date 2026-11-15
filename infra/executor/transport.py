"""Bounded kubectl API transport; no shell, SSH/admin fallback or automatic retries."""

import json
import subprocess
import threading
from urllib.parse import urlsplit

from infra.runner.validation import encode_json

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = 768 * 1024


class ApiError(RuntimeError):
    def __init__(self, status=None):
        self.status = status
        super().__init__("KUBERNETES_API_UNAVAILABLE")


def bounded_command(argv, payload=None, *, timeout=25):
    """Bound both pipes while draining and bound the complete process lifetime."""
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        raise ApiError() from None
    exceeded = threading.Event()
    buffers = [bytearray(), bytearray()]

    def drain(pipe, target, cap):
        try:
            while chunk := pipe.read(4096):
                remaining = cap - len(target)
                target.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    exceeded.set()
                    process.kill()
                    return
        finally:
            pipe.close()

    def write():
        try:
            process.stdin.write(payload)
        except OSError:
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    threads = [threading.Thread(target=drain, args=(process.stdout, buffers[0], MAX_RESPONSE_BYTES), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, buffers[1], 16384), daemon=True)]
    if payload is not None:
        threads.append(threading.Thread(target=write, daemon=True))
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait(timeout=2)
    finally:
        for thread in threads:
            thread.join(timeout=2)
    if timed_out or exceeded.is_set() or any(t.is_alive() for t in threads):
        raise ApiError()
    if process.returncode:
        # Never return kubectl diagnostics: they can contain staged code or credentials.
        status = next((code for name, code in ((b"NotFound", 404), (b"AlreadyExists", 409),
                                               (b"Forbidden", 403), (b"Unauthorized", 401))
                       if b"(" + name + b")" in buffers[1]), None)
        raise ApiError(status)
    return bytes(buffers[0])


class KubectlAPI:
    def __init__(self, kubeconfig, context, *, executable="kubectl"):
        if not kubeconfig or not context:
            raise ValueError("explicit kubeconfig and context required")
        self.prefix = [executable, "--kubeconfig", str(kubeconfig), "--context", context,
                       "--request-timeout=20s"]

    def verify_tls(self):
        """Check the selected trusted configuration without exposing auth material."""
        try:
            config = json.loads(bounded_command(self.prefix + ["config", "view", "--minify", "-o", "json"]))
            clusters = config["clusters"]
            cluster = clusters[0]["cluster"]
            url = urlsplit(cluster["server"])
            if (len(clusters) != 1 or url.scheme != "https" or not url.hostname
                    or url.username or url.password or cluster.get("insecure-skip-tls-verify")
                    or not (cluster.get("certificate-authority") or cluster.get("certificate-authority-data"))):
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise ApiError() from None

    def request(self, method, path, body=None):
        if method not in {"GET", "POST", "DELETE"} or not path.startswith(("/api/", "/apis/")):
            raise ValueError("unsupported Kubernetes operation")
        self.verify_tls()
        args = {"GET": ["get", "--raw", path],
                "POST": ["create", "--raw", path, "-f", "-"],
                "DELETE": ["delete", "--raw", path, "-f", "-"]}[method]
        payload = None if body is None else encode_json(body)
        if payload is not None and len(payload) > MAX_REQUEST_BYTES:
            raise ApiError()
        try:
            raw = bounded_command(self.prefix + args, payload)
            value = json.loads(raw)
            if type(value) is not dict:
                raise ValueError
            return value
        except ApiError as exc:
            if method == "GET" and exc.status == 404:
                return None
            raise
        except (ValueError, UnicodeError, RecursionError):
            raise ApiError() from None
