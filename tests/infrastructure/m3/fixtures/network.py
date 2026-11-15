"""Bounded trusted probes to M1-recorded destinations. Kata only.

Reinspect addresses before live reuse; no successful connection is acceptable.
This checks selected paths, not complete M6 network isolation.
"""
import json
import socket
from pathlib import Path

targets = [("api", "10.96.0.1", 443), ("node-api", "10.77.10.138", 6443),
           ("node-kubelet", "10.77.10.138", 10250),
           ("metadata", "169.254.169.254", 80), ("internet", "1.1.1.1", 443),
           ("dns-tcp", "10.96.0.10", 53), ("controlled-peer", "10.244.253.3", 53)]
observed = []
for name, host, port in targets:
    try:
        with socket.create_connection((host, port), timeout=2):
            pass
    except OSError:
        observed.append({"target": name, "connected": False})
    else:
        raise AssertionError("denied destination unexpectedly reachable")
query = b"\x4d\x33\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
for label in "kubernetes.default.svc.cluster.local".split("."):
    encoded = label.encode("ascii")
    query += bytes([len(encoded)]) + encoded
query += b"\x00\x00\x01\x00\x01"
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    sock.settimeout(2)
    try:
        sock.sendto(query, ("10.96.0.10", 53))
        sock.recvfrom(512)
    except OSError:
        observed.append({"target": "dns-udp", "connected": False})
    else:
        raise AssertionError("DNS unexpectedly answered")
Path("/tmp/result.json").write_text(json.dumps(observed), encoding="utf-8")
