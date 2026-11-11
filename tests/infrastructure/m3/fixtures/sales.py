"""Trusted canonical calculation. Execute only inside the approved Kata Job."""
import csv
import json
from pathlib import Path

sales = {}
with open("/inputs/data.csv", newline="", encoding="utf-8") as source:
    for row in csv.DictReader(source):
        sales.setdefault(row["product"], {})[row["month"]] = int(row["units"])
product = min(sales, key=lambda name: sales[name]["November"] - sales[name]["October"])
result = {"product": product, "october_units": sales[product]["October"],
          "november_units": sales[product]["November"],
          "change_units": sales[product]["November"] - sales[product]["October"]}
Path("/tmp/result.json").write_text(json.dumps(result), encoding="utf-8")
print("trusted sales diagnostic; result travels through its dedicated file")
