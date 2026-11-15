"""Backend FutureExecutor implementation; candidate source is only ever staged.

Backend contract types are loaded lazily from app.executor_contract, allowing
infra and backend branches to be integrated without duplicating production types.
Transport, dataset authorization, image provenance and node observations are
trusted application dependencies, never model/HTTP-selected settings.
"""

from copy import deepcopy
import hashlib
import importlib
from uuid import UUID
from urllib.parse import urlencode

from infra.runner.collection import ExpectedRun, collect_result, external_failure
from infra.runner.contract import CSV_BYTES, NAMESPACE, PROTOCOL, RUN_LABEL, RUNTIME_CLASS, SCRIPT_SECONDS, ContractError
from infra.runner.job import check_image, make_job
from infra.runner.staging import stage_inputs
from infra.runner.validation import encode_json
from .transport import ApiError, MAX_RESPONSE_BYTES

BASE = f"/api/v1/namespaces/{NAMESPACE}"
JOBS = f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs"
ANNOTATION = "kataai/"


class ExecutorError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _subset(actual, expected):
    """Allow API default fields, but require exact list lengths/order and values."""
    if type(expected) is dict:
        return type(actual) is dict and all(k in actual and _subset(actual[k], v) for k, v in expected.items())
    if type(expected) is list:
        return type(actual) is list and len(actual) == len(expected) and all(
            _subset(a, e) for a, e in zip(actual, expected))
    return type(actual) is type(expected) and actual == expected


def _workload(spec, expected):
    if not _subset(spec, expected):
        raise ExecutorError("RESULT_ORIGIN")
    if any(spec.get(k) for k in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace",
                                "initContainers", "ephemeralContainers")):
        raise ExecutorError("RESULT_ORIGIN")
    container = spec["containers"][0]
    security = container.get("securityContext", {})
    if (any(container.get(k) for k in ("args", "envFrom", "lifecycle", "volumeDevices"))
            or security.get("privileged") or security.get("procMount", "Default") != "Default"):
        raise ExecutorError("RESULT_ORIGIN")


class KataExecutor:
    """Implements submit/status/read_result/cancel/cleanup from FutureExecutor.

    resolve_dataset(request, cap) must authorize an ACTIVE/READY dataset and read
    at most cap+1 bytes without following caller-selected paths. authorize(request)
    must return exactly True for an approved execution (trusted fixtures until
    isolation acceptance). verify_image(image, container_status) must return True
    only for a proven released artifact. observe_teardown(record) is a trusted
    node observer returning True/False/None; API absence alone never confirms it.

    The caller persists its request/run UUID before submit and periodically calls
    status/cleanup for store.pending(). No threads, servers or model calls start.
    """

    def __init__(self, api, store, *, image, resolve_dataset, authorize=None,
                 verify_image=None, observe_teardown=None, contracts=None, decode_result=None):
        check_image(image)
        self.api, self.store, self.image = api, store, image
        self.resolve_dataset, self.authorize = resolve_dataset, authorize
        self.verify_image, self.observe_teardown = verify_image, observe_teardown
        self.types = contracts or importlib.import_module("app.executor_contract")
        self.decode_result = decode_result or importlib.import_module("app.executor_results").decode_execution_result

    @staticmethod
    def _ids(request_id, run_id):
        if type(request_id) is not UUID or type(run_id) is not UUID:
            raise ValueError("INVALID_EXECUTOR_REQUEST")

    def _load(self, request_id, run_id):
        record = self.store.get(str(run_id))
        if record and record["request_id"] != str(request_id):
            raise ExecutorError("RESULT_ORIGIN")
        return record

    def _ack(self, request_id, run_id, status):
        return self.types.ExecutorResult(request_id, run_id, self.types.ExecutorStatus(status))

    @staticmethod
    def _callback(function, code, *args):
        if function is None:
            raise ExecutorError(code)
        try:
            return function(*args)
        except Exception:
            # Provider exceptions can contain local paths, dataset data or tokens.
            raise ExecutorError(code) from None

    def _get(self, path):
        value = self.api.request("GET", path)
        if value is not None and (type(value) is not dict or len(encode_json(value)) > MAX_RESPONSE_BYTES):
            raise ApiError()
        return value

    def _list(self, path, **query):
        value = self._get(path + "?" + urlencode(query))
        if (not value or type(value.get("items")) is not list
                or value.get("metadata", {}).get("continue")):
            raise ApiError()
        return value["items"]

    def _preflight(self):
        runtime = self._get("/apis/node.k8s.io/v1/runtimeclasses/" + RUNTIME_CLASS)
        namespace = self._get("/api/v1/namespaces/" + NAMESPACE)
        if not runtime or runtime.get("handler") != RUNTIME_CLASS:
            raise ExecutorError("KATA_UNAVAILABLE")
        if not namespace or namespace.get("metadata", {}).get("deletionTimestamp"):
            raise ExecutorError("INFRASTRUCTURE_FAILURE")
        policies = self._list(f"/apis/networking.k8s.io/v1/namespaces/{NAMESPACE}/networkpolicies")
        if len(policies) != 1 or policies[0].get("metadata", {}).get("name") != "default-deny":
            raise ExecutorError("ISOLATION_UNVERIFIED")
        spec = policies[0].get("spec", {})
        if (spec.get("podSelector") != {} or set(spec.get("policyTypes", [])) != {"Ingress", "Egress"}
                or spec.get("ingress") or spec.get("egress")):
            raise ExecutorError("ISOLATION_UNVERIFIED")
        for path in ("/apis/projectcalico.org/v3/globalnetworkpolicies",
                     f"/apis/projectcalico.org/v3/namespaces/{NAMESPACE}/networkpolicies"):
            if self._list(path):
                raise ExecutorError("ISOLATION_UNVERIFIED")

    def _new(self, request):
        if (type(request) is not self.types.ExecutorRequest or type(request.dataset_id) is not UUID
                or request.timeout_seconds != SCRIPT_SECONDS or type(request.timeout_seconds) is not int):
            raise ExecutorError("INPUT_INVALID")
        script = request.proposal.code.encode("utf-8")
        if len(script) > 16384:
            raise ExecutorError("INPUT_INVALID")
        csv = self._callback(self.resolve_dataset, "DATASET_UNAVAILABLE", request, CSV_BYTES)
        if type(csv) is not bytes:
            raise ExecutorError("INPUT_INVALID")
        name = "ka-" + request.run_id.hex
        cm, job = stage_inputs(name, script, csv), make_job(name, self.image)
        identity = {"request-id": str(request.request_id), "run-id": str(request.run_id),
                    "dataset-id": str(request.dataset_id), "protocol": PROTOCOL}
        fingerprint = hashlib.sha256(encode_json({"identity": identity, "cm": cm, "job": job})).hexdigest()
        annotations = {ANNOTATION + k: v for k, v in identity.items()}
        annotations[ANNOTATION + "fingerprint"] = fingerprint
        for manifest in (cm, job):
            manifest["metadata"].setdefault("annotations", {}).update(annotations)
        return {"request_id": str(request.request_id), "run_id": str(request.run_id),
                "dataset_id": str(request.dataset_id), "code_hash": hashlib.sha256(script).hexdigest(),
                "image": self.image, "name": name, "cm": cm, "job": job,
                "cm_uid": None, "job_uid": None, "pods": {}, "cm_intent": False, "job_intent": False,
                "cancel": False, "state": "queued", "cleanup": "not_started", "outcome": None,
                "api_absent": False, "guest_teardown_verified": False, "last_error": None}

    def _check(self, actual, expected, uid=None):
        if type(actual) is not dict or actual.get("kind") != expected["kind"] or actual.get("apiVersion") != expected["apiVersion"]:
            raise ExecutorError("RESULT_ORIGIN")
        metadata = actual.get("metadata", {})
        if (not _subset(metadata, expected["metadata"]) or not metadata.get("uid")
                or (uid and metadata["uid"] != uid)):
            raise ExecutorError("RESULT_ORIGIN")
        if expected["kind"] == "ConfigMap":
            if actual.get("immutable") is not True or actual.get("data") != expected["data"] or actual.get("binaryData"):
                raise ExecutorError("RESULT_ORIGIN")
        else:
            if not _subset(actual.get("spec"), expected["spec"]):
                raise ExecutorError("RESULT_ORIGIN")
            _workload(actual["spec"]["template"]["spec"], expected["spec"]["template"]["spec"])
        return metadata["uid"]

    def _ensure(self, record, kind, path):
        expected = record[kind]
        current = self._get(path)
        if current:
            if current.get("metadata", {}).get("deletionTimestamp"):
                raise ExecutorError("SUBMISSION_UNKNOWN")
            uid = self._check(current, expected, record[kind + "_uid"])
        else:
            # A previously attempted create could have succeeded and disappeared.
            # Never recreate it automatically, even if the last response was lost.
            if record[kind + "_intent"] or record[kind + "_uid"]:
                raise ExecutorError("SUBMISSION_UNKNOWN")
            record[kind + "_intent"] = True
            self.store.save(record)
            created = self.api.request("POST", path.rsplit("/", 1)[0], expected)
            uid = self._check(created, expected)
        record[kind + "_uid"] = uid
        self.store.save(record)

    def submit(self, request):
        if type(request) is not self.types.ExecutorRequest:
            raise ValueError("INVALID_EXECUTOR_REQUEST")
        self._ids(request.request_id, request.run_id)
        with self.store.operation():
            record = None
            try:
                record = self._load(request.request_id, request.run_id)
                if record and record["cancel"]:
                    return self._ack(request.request_id, request.run_id, "rejected")
                if self._callback(self.authorize, "EXECUTION_NOT_APPROVED", request) is not True:
                    raise ExecutorError("EXECUTION_NOT_APPROVED")
                if record:
                    if (record["cancel"] or record["cleanup"] != "not_started"
                            or record["dataset_id"] != str(request.dataset_id) or record["image"] != self.image
                            or request.timeout_seconds != SCRIPT_SECONDS
                            or record["code_hash"] != hashlib.sha256(request.proposal.code.encode("utf-8")).hexdigest()):
                        raise ExecutorError("INPUT_INVALID")
                    if record["outcome"]:
                        return self._ack(request.request_id, request.run_id, "accepted")
                else:
                    record = self._new(request)
                    self.store.save(record)  # Durable intent and exact input snapshot precede any API mutation.
                self._preflight()
                self._ensure(record, "cm", BASE + "/configmaps/" + record["name"] + "-inputs")
                self._ensure(record, "job", JOBS + "/" + record["name"])
                record["last_error"] = None
                self.store.save(record)
                return self._ack(request.request_id, request.run_id, "accepted")
            except (ExecutorError, ContractError, ApiError, ValueError) as exc:
                if record:
                    record["last_error"] = getattr(exc, "code", "KUBERNETES_API_UNAVAILABLE")
                    self.store.save(record)
                unknown = isinstance(exc, ApiError) and exc.status not in (401, 403)
                unknown |= getattr(exc, "code", "") == "SUBMISSION_UNKNOWN"
                return self._ack(request.request_id, request.run_id, "unknown" if unknown else "rejected")

    def _snapshots(self, record):
        job = self._get(JOBS + "/" + record["name"])
        if job:
            record["job_uid"] = self._check(job, record["job"], record["job_uid"])
        pods = self._list(BASE + "/pods", labelSelector=RUN_LABEL + "=" + record["name"])
        for pod in pods:
            meta = pod.get("metadata", {})
            owners = [o for o in meta.get("ownerReferences", []) if o.get("controller") is True]
            if (meta.get("namespace") != NAMESPACE or meta.get("labels", {}).get(RUN_LABEL) != record["name"]
                    or not meta.get("uid") or not meta.get("name") or len(owners) != 1 or not record["job_uid"]
                    or not _subset(owners[0], {"apiVersion": "batch/v1", "kind": "Job", "name": record["name"],
                                               "uid": record["job_uid"], "controller": True})):
                raise ExecutorError("RESULT_ORIGIN")
            record["pods"][meta["uid"]] = {"name": meta["name"], "node": pod.get("spec", {}).get("nodeName"),
                                           "uid": meta["uid"], "phase": pod.get("status", {}).get("phase"),
                                           "containers": [{k: s.get(k) for k in ("name", "containerID", "imageID")}
                                               for s in pod.get("status", {}).get("containerStatuses", [])]}
        self.store.save(record)
        return job, pods

    def _observe(self, record):
        if record["cleanup"] == "confirmed":
            return
        if record["cleanup"] != "not_started":
            self._clean(record)
            return
        if record["outcome"]:
            return
        job, pods = self._snapshots(record)
        if len(record["pods"]) > 1:
            record.update(state="failed", outcome={"code": "MULTIPLE_POD_ATTEMPTS"})
            return
        if not job:
            record["state"] = "unknown" if (record["job_intent"] or
                (record["cm_intent"] and not record["cm_uid"])) else "queued"
            return
        pod = pods[0] if pods else None
        allowed = {record["job_uid"], *record["pods"]}
        events = []
        for uid in sorted(allowed):
            events.extend(self._list(BASE + "/events", fieldSelector="involvedObject.uid=" + uid))
        events = [e for e in events if e.get("metadata", {}).get("namespace") == NAMESPACE
                  and e.get("involvedObject", {}).get("uid") in allowed]
        failure = external_failure(job, pod, events)
        if failure:
            record.update(state="failed", outcome={"code": failure})
            return
        if not pod:
            if any(c.get("status") == "True" and c.get("type") in {"Complete", "Failed"}
                   for c in job.get("status", {}).get("conditions", [])):
                raise ExecutorError("RESULT_UNAVAILABLE")
            record["state"] = "queued"
            return
        _workload(pod.get("spec", {}), record["job"]["spec"]["template"]["spec"])
        if pod.get("status", {}).get("phase") not in ("Succeeded", "Failed"):
            record["state"] = "running" if pod.get("status", {}).get("phase") == "Running" else "queued"
            return
        statuses = pod.get("status", {}).get("containerStatuses", [])
        if len(statuses) != 1 or self._callback(self.verify_image, "IMAGE_PROVENANCE_UNVERIFIED",
                record["image"], deepcopy(statuses[0])) is not True:
            raise ExecutorError("IMAGE_PROVENANCE_UNVERIFIED")
        outcome = collect_result(pod, ExpectedRun(record["name"], record["job_uid"], pod["metadata"]["uid"], record["image"]))
        if outcome["code"] == "OK":
            raw = encode_json(outcome["result"])
            try:
                self.decode_result(raw)  # Also honor the backend's stricter NUL/integer checks.
            except ValueError:
                raise ExecutorError("MALFORMED_EXECUTION_RESULT") from None
            outcome["result_bytes"] = raw.decode("utf-8")
        record.update(state="completed" if outcome["code"] == "OK" else "failed", outcome=outcome)

    def status(self, request_id, run_id):
        self._ids(request_id, run_id)
        with self.store.operation():
            record = self._load(request_id, run_id)
            if record is None:
                return self.types.ExecutorObservation(request_id, run_id, self.types.RunState("unknown"),
                                                      self.types.CleanupState("unknown"))
            try:
                self._observe(record)
                record["last_error"] = None
            except (ApiError, ExecutorError, ContractError) as exc:
                record["last_error"] = getattr(exc, "code", "KUBERNETES_API_UNAVAILABLE")
                if not record["outcome"]:
                    record["state"] = "unknown"
            self.store.save(record)
            return self.types.ExecutorObservation(request_id, run_id, self.types.RunState(record["state"]),
                                                  self.types.CleanupState(record["cleanup"]))

    def read_result(self, request_id, run_id):
        self._ids(request_id, run_id)
        self.status(request_id, run_id)
        with self.store.operation():
            record = self._load(request_id, run_id)
            if not record or not record["outcome"] or record["state"] != "completed":
                raise ExecutorError("RESULT_UNAVAILABLE")
            return record["outcome"]["result_bytes"].encode("utf-8")

    def outcome(self, request_id, run_id):
        """Host-owned error/provenance detail, separate from read_result JSON bytes."""
        self._ids(request_id, run_id)
        with self.store.operation():
            record = self._load(request_id, run_id)
            if not record or not record["outcome"]:
                return None
            result = deepcopy(record["outcome"])
            result.update(request_id=record["request_id"], run_id=record["run_id"],
                          kubernetes_run_name=record["name"])
            return result

    def reconcile(self):
        """One bounded pass over pending runs; caller chooses scheduling/backoff.

        Observes existing work and retries requested cleanup, never submits code.
        Prepared/uncertain submissions require submit with the same persisted
        request identity; absent uncertain creates require operator resolution.
        """
        return [self.status(UUID(r["request_id"]), UUID(r["run_id"])) for r in self.store.pending()]

    def _delete(self, path, uid):
        try:
            self.api.request("DELETE", path, {"apiVersion": "v1", "kind": "DeleteOptions",
                             "preconditions": {"uid": uid}, "propagationPolicy": "Foreground"})
        except ApiError as exc:
            if exc.status != 404:
                raise

    def _clean(self, record):
        if "job" not in record:  # Cancellation tombstone: no submit could have occurred in this journal.
            return
        job, pods = self._snapshots(record)
        if job:
            self._delete(JOBS + "/" + record["name"], record["job_uid"])
        # A vanished Job may leave associated Pods. Delete only their observed UIDs.
        for pod in pods:
            self._delete(BASE + "/pods/" + pod["metadata"]["name"], pod["metadata"]["uid"])
        cm_path = BASE + "/configmaps/" + record["name"] + "-inputs"
        cm = self._get(cm_path)
        if cm:
            record["cm_uid"] = self._check(cm, record["cm"], record["cm_uid"])
            self.store.save(record)
            self._delete(cm_path, record["cm_uid"])
        job, pods = self._snapshots(record)
        record["api_absent"] = not job and not pods and self._get(cm_path) is None
        if record["api_absent"]:
            if any(record[k + "_intent"] and not record[k + "_uid"] for k in ("cm", "job")):
                # An unacknowledged API create could still arrive after these GETs.
                # Neither current absence nor a node observation fences that create.
                record["cleanup"] = "unknown"
                return
            no_dispatch = not record["job_intent"] and not record["job_uid"] and not record["pods"]
            verified = no_dispatch or (self.observe_teardown is not None
                and self._callback(self.observe_teardown, "TEARDOWN_UNKNOWN", deepcopy(record)) is True)
            record["guest_teardown_verified"] = verified
            record["cleanup"] = "confirmed" if verified else "pending"
            if verified and record["cancel"]:
                record["state"] = "cancelled"

    def _finish(self, request_id, run_id, *, cancel):
        self._ids(request_id, run_id)
        with self.store.operation():
            record = self._load(request_id, run_id)
            if record is None:
                if not cancel:
                    return self._ack(request_id, run_id, "rejected")
                record = {"request_id": str(request_id), "run_id": str(run_id), "cancel": True,
                          "state": "cancelled", "cleanup": "confirmed", "outcome": None}
                self.store.save(record)
                return self._ack(request_id, run_id, "accepted")
            if cancel and record["outcome"]:
                return self._ack(request_id, run_id, "rejected")
            if not cancel and not record["outcome"] and not record["cancel"]:
                return self._ack(request_id, run_id, "rejected")  # Preserve unread terminal evidence.
            record["cancel"] |= cancel
            if record["cleanup"] == "confirmed":
                return self._ack(request_id, run_id, "accepted")
            record["cleanup"] = "pending"
            self.store.save(record)
            try:
                self._clean(record)
                record["last_error"] = None
                self.store.save(record)
                return self._ack(request_id, run_id, "accepted")
            except (ApiError, ExecutorError, ContractError) as exc:
                record["last_error"] = getattr(exc, "code", "KUBERNETES_API_UNAVAILABLE")
                record["cleanup"] = "unknown"
                self.store.save(record)
                return self._ack(request_id, run_id, "unknown")

    def cancel(self, request_id, run_id):
        return self._finish(request_id, run_id, cancel=True)

    def cleanup(self, request_id, run_id):
        return self._finish(request_id, run_id, cancel=False)
