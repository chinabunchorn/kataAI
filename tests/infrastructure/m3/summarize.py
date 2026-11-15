"""Consolidate bounded local harness records; never execute candidate programs."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from catalog import CASES, case_script
from infra.runner.collection import ExpectedRun, collect_result, external_failure
from infra.runner.job import check_image


def read(path):
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("unexpected evidence size")
    return json.loads(path.read_bytes())


def summarize(image):
    check_image(image)
    rows = {}
    for directory in sorted((ROOT / ".m3-runs").iterdir()):
        if not (directory / "test.json").is_file():
            continue
        test = read(directory / "test.json")
        if test["image"] != image:
            continue
        name = test["case"]
        expected = CASES[name][1]
        if not (directory / "inventory.json").is_file():
            continue
        inventory = read(directory / "inventory.json")
        pods = read(directory / "pods.json")["items"]
        cleanup = read(directory / "cleanup.json") if (directory / "cleanup.json").is_file() else {}
        outcome = None
        evidence = {"case": name, "run_id": directory.name, "expected_code": expected,
                    "job_uid": inventory.get("job"), "api_cleanup_absent": cleanup.get("api_absent", False)}
        if name == "missing-runtime":
            events = read(directory / "events.json")["items"]
            associated = [event for event in events if event.get("involvedObject", {}).get("uid") == inventory["job"]]
            outcome = {"code": external_failure({}, events=associated), "no_pod_created": not pods}
            evidence["events"] = associated
            valid = outcome["code"] == expected and not pods
        else:
            if len(pods) != 1:
                raise ValueError("unexpected Pod attempts in evidence")
            pod = pods[0]
            uid = pod["metadata"]["uid"]
            outcome = collect_result(pod, ExpectedRun(directory.name, inventory["job"], uid, image))
            evidence.update(pod_uid=uid, runtime_class=pod["spec"]["runtimeClassName"],
                image=pod["spec"]["containers"][0]["image"],
                container_status=pod["status"]["containerStatuses"][0])
            valid = outcome["code"] == expected
            if CASES[name][2] is not None:
                valid = valid and outcome.get("result") == CASES[name][2]
            diagnostics = directory / "diagnostics.jsonl"
            if diagnostics.is_file():
                if diagnostics.stat().st_size > 24576:
                    raise ValueError("unexpected diagnostic evidence size")
                evidence["diagnostic_retained_bytes"] = {record["stream"]: len(base64.b64decode(record["data"], validate=True))
                    for record in map(json.loads, diagnostics.read_bytes().splitlines())}
        inputs = read(directory / "inputs.json")
        evidence["script_sha256"] = inputs["metadata"]["annotations"]["kataai/script-sha256"]
        if evidence["script_sha256"] != hashlib.sha256(case_script(name)).hexdigest():
            raise ValueError("fixture changed since execution")
        evidence["outcome"] = outcome
        if (directory / "failure.json").is_file():
            evidence["failure"] = read(directory / "failure.json")
            valid = False
        evidence["status"] = "passed" if valid and evidence["api_cleanup_absent"] else "failed"
        rows[name] = evidence
    for name in CASES:
        rows.setdefault(name, {"case": name, "status": "not_run", "expected_code": CASES[name][1]})
    return {"image": image, "counts": {status: sum(row["status"] == status for row in rows.values())
            for status in ("passed", "failed", "not_run")}, "cases": list(rows.values()),
            "scope": "Active trusted fixture contract/API outcomes only; independent node evidence is required for VM correlation and teardown. Exact 16 MiB guest scratch capacity is excluded by the 2026-11-15 policy; historical failed/unrun quota evidence is preserved separately."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; preserve earlier evidence")
    result = summarize(args.image)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"]))
