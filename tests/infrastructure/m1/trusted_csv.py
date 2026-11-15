"""Trusted M1 fixture. Run ONLY inside the approved Kata Job."""
import csv
import json
import os
import platform
import sys
import time

assert os.getuid() == 10001, "unexpected guest UID"
assert not os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")
# Check actual write behavior, rather than relying on manifest declarations.
try:
    with open("/inputs/data.csv", "a", encoding="utf-8"):
        pass
except OSError as exc:
    assert exc.errno in (13, 30), repr(exc)
else:
    raise AssertionError("input was writable")

sales = {}
with open("/inputs/data.csv", newline="", encoding="utf-8") as source:
    for row in csv.DictReader(source):
        sales.setdefault(row["product"], {})[row["month"]] = int(row["units"])
product = min(sales, key=lambda name: sales[name]["November"] - sales[name]["October"])
result = {
    "product": product,
    "october_units": sales[product]["October"],
    "november_units": sales[product]["November"],
    "change_units": sales[product]["November"] - sales[product]["October"],
}
assert result == {
    "product": "Notebook", "october_units": 120,
    "november_units": 80, "change_units": -40,
}
payload = json.dumps(result, separators=(",", ":"))
assert len(payload.encode("utf-8")) <= 1024
print(json.dumps({"uid": os.getuid(), "gid": os.getgid(),
                  "guest_kernel": platform.release(), "input_write_denied": True,
                  "serviceaccount_token_absent": True}), file=sys.stderr, flush=True)
print(payload, flush=True)
# A bounded observation window permits node-side VM correlation before exit.
# This is trusted test instrumentation, not the production runner protocol.
time.sleep(60)
