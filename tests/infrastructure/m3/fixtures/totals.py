"""Trusted alternative task returning a JSON array. Kata only."""
import csv
import json
from pathlib import Path

totals = {}
with open("/inputs/data.csv", newline="", encoding="utf-8") as source:
    for row in csv.DictReader(source):
        totals[row["month"]] = totals.get(row["month"], 0) + int(row["units"])
result = [{"month": month, "units": units} for month, units in totals.items()]
Path("/tmp/result.json").write_text(json.dumps(result), encoding="utf-8")
