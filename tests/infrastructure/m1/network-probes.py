"""Trusted, bounded endpoint probes. Execute ONLY in the verified Kata guest."""
import json
import socket

# Observed addresses on 2026-11-11; re-inspect before reuse.
targets = [
    ("api-service", "10.96.0.1", 443),
    ("node-api", "10.77.10.138", 6443),
    ("node-kubelet", "10.77.10.138", 10250),
    ("metadata", "169.254.169.254", 80),
    ("internet", "1.1.1.1", 443),
    ("dns-service", "10.96.0.10", 53),
    ("controlled-coredns-peer", "10.244.253.3", 53),
]
for name, host, port in targets:
    try:
        with socket.create_connection((host, port), timeout=2):
            observed = "CONNECTED"
    except OSError as exc:
        observed = type(exc).__name__
    print(json.dumps(dict(name=name, host=host, port=port, protocol="TCP", observed=observed)), flush=True)

query = b"\x4d\x31\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
for label in "kubernetes.default.svc.cluster.local".split("."):
    encoded = label.encode("ascii")
    query += bytes([len(encoded)]) + encoded
query += b"\x00\x00\x01\x00\x01"
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    sock.settimeout(2)
    sock.sendto(query, ("10.96.0.10", 53))
    try:
        sock.recvfrom(512)
        observed = "RESPONSE"
    except OSError as exc:
        observed = type(exc).__name__
print(json.dumps(dict(name="dns-service", host="10.96.0.10", port=53,
                      protocol="UDP", observed=observed)), flush=True)
