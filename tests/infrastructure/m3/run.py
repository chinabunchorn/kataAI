"""Opt-in trusted fixture harness. Rendering performs no cluster mutation."""

import argparse
import base64
import json
from pathlib import Path
import sys
import time

# Explicit trusted source root; candidate programs are read as bytes only.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from catalog import CASES, case_script
from kube import Kube, SSHKube, bounded_command
from infra.runner.collection import ExpectedRun, collect_result
from infra.runner.contract import NAMESPACE, RUN_LABEL, RUNTIME_CLASS, ContractError
from infra.runner.job import make_job
from infra.runner.staging import stage_inputs
from infra.runner.validation import encode_json


def save(directory: Path, name: str, value: object):
    (directory / name).write_bytes(encode_json(value) + b"\n")


def check_preconditions(kube: Kube, directory: Path):
    runtime = kube.call("get", "runtimeclass", RUNTIME_CLASS, "-o", "json")
    if runtime.get("handler") != RUNTIME_CLASS:
        raise RuntimeError("approved Kata handler unavailable; no fallback")
    namespace = kube.call("get", "namespace", NAMESPACE, "-o", "json")
    policies = kube.get("networkpolicies")
    policy = policies.get("items", [])
    if len(policy) != 1 or policy[0]["metadata"]["name"] != "default-deny":
        raise RuntimeError("unexpected namespace policy set; review without weakening policy")
    spec = policy[0]["spec"]
    if (spec.get("podSelector") != {} or set(spec.get("policyTypes", [])) != {"Ingress", "Egress"}
            or spec.get("ingress") or spec.get("egress")):
        raise RuntimeError("required namespace denial is absent")
    # Fail if inspection is forbidden. A namespace policy alone does not override
    # other Calico tiers or cluster-wide allows.
    global_policies = kube.call("get", "globalnetworkpolicies.projectcalico.org", "-o", "json")
    calico_policies = kube.call("get", "networkpolicies.projectcalico.org", "-A", "-o", "json")
    # Calico NetworkPolicy is namespaced; other namespaces' policies cannot
    # select kata-lab subjects. Global policies remain an explicit review gate.
    relevant = [item for item in calico_policies.get("items", [])
                if item.get("metadata", {}).get("namespace") == NAMESPACE]
    if global_policies.get("items") or relevant:
        raise RuntimeError("additional applicable Calico policy requires operator review")
    if namespace["metadata"].get("deletionTimestamp"):
        raise RuntimeError("namespace is terminating")
    for name, value in (("runtime.json", runtime), ("networkpolicies.json", policies),
                        ("global-policies.json", global_policies), ("calico-policies.json", calico_policies)):
        save(directory, name, value)
    return runtime


def cleanup(kube: Kube, run_id: str, inventory: dict, directory: Path):
    observations = {}
    for kind, path, name in (
        ("job", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs/{run_id}", run_id),
        ("configmap", f"/api/v1/namespaces/{NAMESPACE}/configmaps/{run_id}-inputs", run_id + "-inputs"),
    ):
        if kind in inventory:
            kube.delete_uid(path, inventory[kind])
            observations[kind] = {"uid": inventory[kind], "delete_requested": True}
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        pods = kube.call("get", "pods", "-n", NAMESPACE, "-l", f"{RUN_LABEL}={run_id}", "-o", "json")
        job = kube.get("job", run_id)
        cm = kube.get("configmap", run_id + "-inputs")
        if not job and not cm and not pods.get("items"):
            observations["api_absent"] = True
            observations["vm_teardown_verified"] = False
            save(directory, "cleanup.json", observations)
            return
        time.sleep(1)
    save(directory, "cleanup.json", observations | {"api_absent": False})
    raise RuntimeError("cleanup did not converge; inspect only recorded resource UIDs")


def verify_diagnostics(kube: Kube, pod: dict, directory: Path):
    name = pod["metadata"]["name"]
    # Limit + 1 catches truncation, rather than accepting a valid truncated prefix.
    raw = bounded_command(kube.argv("logs", name, "-n", NAMESPACE,
        "-c", "runner", "--limit-bytes=24577", "--tail=-1"))
    if len(raw) > 24576:
        raise RuntimeError("container log exceeded expected bounded diagnostic framing")
    (directory / "diagnostics.jsonl").write_bytes(raw)
    for line in raw.splitlines():
        record = json.loads(line)
        if set(record) != {"stream", "encoding", "data"} or record["encoding"] != "base64":
            raise RuntimeError("unexpected diagnostic framing")
        if record["stream"] not in {"stdout", "stderr"} or len(base64.b64decode(record["data"], validate=True)) > 8192:
            raise RuntimeError("diagnostic bounds violated")


def execute(args, cm, job, directory):
    kube = SSHKube(args.ssh_host) if args.ssh_host else Kube(args.kubeconfig, args.context)
    check_preconditions(kube, directory)
    if kube.get("job", args.run_id) or kube.get("configmap", args.run_id + "-inputs"):
        raise RuntimeError("run name collision; existing resources will not be altered")
    if args.case == "missing-runtime":
        if kube.call("get", "runtimeclass", job["spec"]["template"]["spec"]["runtimeClassName"],
                     "--ignore-not-found=true", "-o", "json"):
            raise RuntimeError("negative RuntimeClass unexpectedly exists")
    inventory = {}
    try:
        created = kube.call("create", "-f", "-", "-o", "json", body=cm)
        inventory["configmap"] = created["metadata"]["uid"]
        save(directory, "inventory.json", inventory)
        created = kube.call("create", "-f", "-", "-o", "json", body=job)
        inventory["job"] = created["metadata"]["uid"]
        save(directory, "inventory.json", inventory)
        deadline = time.monotonic() + (20 if args.case == "missing-runtime" else 150)
        expected_pod_uid = None
        terminal = None
        while time.monotonic() < deadline:
            current_job = kube.get("job", args.run_id)
            save(directory, "job-status.json", current_job)
            if not current_job or current_job["metadata"]["uid"] != inventory["job"]:
                raise RuntimeError("created Job disappeared or was replaced")
            pods = kube.call("get", "pods", "-n", NAMESPACE, "-l", f"{RUN_LABEL}={args.run_id}", "-o", "json")
            save(directory, "pods.json", pods)
            if len(pods.get("items", [])) > 1:
                raise RuntimeError("unexpected multiple Pod attempts")
            if args.case == "missing-runtime":
                if pods.get("items"):
                    raise RuntimeError("missing RuntimeClass created a Pod; inspect fail-closed evidence")
                time.sleep(1)
                continue
            if pods.get("items"):
                pod = pods["items"][0]
                owner = [item for item in pod["metadata"].get("ownerReferences", []) if item.get("controller")]
                if len(owner) != 1 or owner[0]["uid"] != inventory["job"]:
                    raise RuntimeError("Pod owner mismatch")
                uid = pod["metadata"]["uid"]
                if expected_pod_uid is not None and uid != expected_pod_uid:
                    raise RuntimeError("Pod attempt changed")
                expected_pod_uid = uid
                if pod.get("status", {}).get("phase") in ("Succeeded", "Failed"):
                    terminal = pod
                    break
            time.sleep(1)
        if args.case == "missing-runtime":
            events = kube.call("get", "events", "-n", NAMESPACE,
                "--field-selector", f"involvedObject.uid={inventory['job']}", "-o", "json")
            save(directory, "events.json", events)
            if not any("runtimeclass" in event.get("message", "").lower() and
                       "not found" in event.get("message", "").lower() for event in events.get("items", [])):
                raise RuntimeError("no explicit missing-RuntimeClass rejection event; acceptance unverified")
            outcome = {"code": "KATA_UNAVAILABLE", "no_pod_created": True}
        else:
            if terminal is None:
                raise RuntimeError("no terminal Pod within harness budget; inspect Job conditions")
            # Preserve even startup-failure logs before validation/cleanup.
            verify_diagnostics(kube, terminal, directory)
            outcome = collect_result(terminal, ExpectedRun(args.run_id, inventory["job"],
                expected_pod_uid, args.image))
            if outcome["code"] != CASES[args.case][1]:
                raise RuntimeError("fixture outcome mismatch: " + outcome["code"])
            expected_result = CASES[args.case][2]
            if expected_result is not None and outcome.get("result") != expected_result:
                raise RuntimeError("fixture result mismatch")
            if args.case == "security":
                result = outcome["result"]
                if result.get("uid") != 10001 or result.get("gid") != 10001 or not all(
                    result.get(key) is True for key in ("input_write_denied", "root_readonly",
                        "serviceaccount_absent", "known_credentials_absent", "scratch_writable")):
                    raise RuntimeError("security observations failed")
            if args.case == "scratch" and outcome["result"].get("scratch_enospc") is not True:
                raise RuntimeError("scratch limit not observed")
        save(directory, "outcome.json", outcome)
        print(f"{args.case}: {outcome['code']}; API checks passed, node VM evidence still required")
    except Exception as exc:
        save(directory, "failure.json", {"error": str(exc)[:4000],
            "note": "If create response was lost, inspect exact planned names before cleanup; do not rerun blindly."})
        raise
    finally:
        try:
            cleanup(kube, args.run_id, inventory, directory)
        except Exception as exc:
            save(directory, "cleanup-failure.json", {"error": str(exc)[:4000],
                "inventory": inventory, "api_absent": False, "vm_teardown_verified": False})
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=sorted(CASES))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--image", required=True, help="built runner repository@sha256:digest")
    parser.add_argument("--execute", action="store_true", help="create ONLY this trusted case in Kata")
    parser.add_argument("--kubeconfig")
    parser.add_argument("--context")
    parser.add_argument("--ssh-host", help="existing trusted-operator SSH alias; test-only alternative transport")
    args = parser.parse_args()
    if args.ssh_host and (args.kubeconfig or args.context):
        parser.error("select SSH operator transport OR explicit kubeconfig/context")
    if args.execute and not args.ssh_host and (not args.kubeconfig or not args.context):
        parser.error("execution requires explicit kubeconfig/context or existing operator SSH alias")
    script = case_script(args.case)
    csv = (ROOT / "tests/infrastructure/m1/data.csv").read_bytes()
    cm = stage_inputs(args.run_id, script, csv)
    job = make_job(args.run_id, args.image)
    if args.case == "missing-runtime":
        # The only test-only runtime override; cannot select ordinary-container runtime.
        job["spec"]["template"]["spec"]["runtimeClassName"] = args.run_id + "-absent"
    directory = ROOT / ".m3-runs" / args.run_id
    directory.mkdir(parents=True, exist_ok=False)
    save(directory, "inputs.json", cm)
    save(directory, "job.json", job)
    save(directory, "test.json", {"case": args.case, "image": args.image,
        "expected_code": CASES[args.case][1], "executed": bool(args.execute)})
    if args.execute:
        execute(args, cm, job, directory)
    else:
        print(f"Rendered {directory}; nothing submitted or executed")


if __name__ == "__main__":
    main()
