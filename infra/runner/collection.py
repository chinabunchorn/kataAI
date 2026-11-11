"""Pure M4-facing collection adapter. Kubernetes API transport belongs to caller."""

from dataclasses import dataclass

from .contract import COMMAND, CONTAINER, EXITS, NAMESPACE, REPORT_BYTES, RUN_LABEL, RUNTIME_CLASS, ContractError
from .job import check_image
from .report import validate_report
from .staging import check_run_id


@dataclass(frozen=True)
class ExpectedRun:
    run_id: str
    job_uid: str
    pod_uid: str
    image: str
    namespace: str = NAMESPACE
    container: str = CONTAINER


def external_failure(job: dict, pod: dict | None = None, events: list | None = None) -> str | None:
    """Classify associated Kubernetes evidence, never infer OOM from exit 137.

    M4 must associate these snapshots/events with its recorded UIDs first. None
    means no distinguishable infrastructure cause, not execution success.
    """
    status = job.get("status", {})
    if any(condition.get("status") == "True" and condition.get("reason") == "DeadlineExceeded"
           and condition.get("type") in ("Failed", "FailureTarget")
           for condition in status.get("conditions", [])):
        return "RUN_TIMEOUT"
    pod_status = (pod or {}).get("status", {})
    for container in pod_status.get("containerStatuses", []):
        state = container.get("state", {})
        if state.get("terminated", {}).get("reason") == "OOMKilled":
            return "RESOURCE_LIMIT"
        if state.get("waiting", {}).get("reason") in {"ErrImagePull", "ImagePullBackOff", "InvalidImageName", "CreateContainerConfigError"}:
            return "INFRASTRUCTURE_FAILURE"
    if pod_status.get("reason") == "Evicted":
        message = pod_status.get("message", "").lower()
        if any(word in message for word in ("memory", "ephemeral-storage", "diskpressure", "disk pressure")):
            return "RESOURCE_LIMIT"
        return "INFRASTRUCTURE_FAILURE"
    for event in events or []:
        message = event.get("message", "").lower()
        if ("runtimeclass" in message and "not found" in message) or "no runtime for" in message:
            return "KATA_UNAVAILABLE"
    return None


def collect_result(pod: dict, expected: ExpectedRun) -> dict:
    """Returns host-owned outcome + separate result; never accepts logs as results.

    Caller bounds API responses and selects the exact recorded Pod before calling.
    Infrastructure errors are identifiers, not script exit guesses.
    """
    check_run_id(expected.run_id)
    check_image(expected.image)
    if (expected.namespace != NAMESPACE or expected.container != CONTAINER
            or not expected.job_uid or not expected.pod_uid):
        raise ContractError("RESULT_ORIGIN", "invalid expected identity")
    try:
        meta, spec, status = pod["metadata"], pod["spec"], pod["status"]
        owners = [owner for owner in meta.get("ownerReferences", []) if owner.get("controller") is True]
        if (meta["namespace"] != expected.namespace or meta["uid"] != expected.pod_uid
                or meta["labels"][RUN_LABEL] != expected.run_id or len(owners) != 1
                or owners[0].get("uid") != expected.job_uid
                or owners[0].get("kind") != "Job"
                or owners[0].get("apiVersion") != "batch/v1"
                or owners[0].get("name") != expected.run_id):
            raise ContractError("RESULT_ORIGIN", "Pod/Job association mismatch")
        if spec["runtimeClassName"] != RUNTIME_CLASS:
            raise ContractError("KATA_UNAVAILABLE")
        containers = spec["containers"]
        if (len(containers) != 1 or spec.get("initContainers") or spec.get("ephemeralContainers")
                or containers[0]["name"] != expected.container
                or containers[0]["image"] != expected.image
                or containers[0]["command"] != COMMAND
                or containers[0].get("args")):
            raise ContractError("RESULT_ORIGIN", "unexpected workload")
        statuses = status.get("containerStatuses", [])
        if len(statuses) != 1 or statuses[0]["name"] != expected.container:
            raise ContractError("INFRASTRUCTURE_FAILURE", "no unique container status")
        container_status = statuses[0]
        if container_status.get("restartCount") != 0:
            raise ContractError("RESULT_ORIGIN", "unexpected restart")
        # imageID is runtime-dependent (manifest vs config digest). It is evidence,
        # not assumed equal to a multiarch reference; verify pinned spec + imageID.
        if not container_status.get("imageID") or not container_status.get("containerID"):
            raise ContractError("INFRASTRUCTURE_FAILURE", "missing runtime identity")
        terminated = container_status.get("state", {}).get("terminated")
        if not terminated:
            if status.get("reason") == "Evicted":
                raise ContractError(external_failure({}, pod) or "INFRASTRUCTURE_FAILURE")
            raise ContractError("NOT_TERMINAL")
        if terminated.get("reason") == "OOMKilled":
            raise ContractError("RESOURCE_LIMIT", "observed OOMKilled")
        if status.get("phase") not in ("Succeeded", "Failed"):
            raise ContractError("NOT_TERMINAL")
        message = terminated.get("message", "")
        if not isinstance(message, str) or len(message) > REPORT_BYTES:
            raise ContractError("REPORT_INVALID")
        try:
            raw = message.encode("utf-8", errors="strict")
        except UnicodeError:
            raise ContractError("REPORT_INVALID") from None
        report = validate_report(raw, run_id=expected.run_id, pod_uid=expected.pod_uid)
        if (type(terminated["exitCode"]) is not int
                or terminated["exitCode"] != EXITS[report["code"]]
                or (report["code"] == "OK" and
                    (status["phase"] != "Succeeded" or terminated.get("signal", 0) != 0))):
            raise ContractError("REPORT_INVALID", "exit/status mismatch")
        outcome = {"run_id": expected.run_id, "job_uid": expected.job_uid,
                   "pod_uid": expected.pod_uid, "code": report["code"],
                   "exit_code": terminated["exitCode"],
                   "script_exit_code": report["script_exit_code"]}
        if report["code"] == "OK":
            outcome["result"] = report["result"]
        return outcome
    except (KeyError, TypeError, IndexError):
        raise ContractError("RESULT_ORIGIN", "incomplete Pod evidence") from None
