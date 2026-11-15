"""Offline contract/recovery tests. No candidate program or cluster is executed."""

from copy import deepcopy
import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from infra.executor import ApiError, ExecutorError, KataExecutor, SQLiteRunStore
from infra.executor.adapter import BASE, JOBS
from infra.runner.contract import CONTAINER, EXITS, NAMESPACE, RUN_LABEL, RUNTIME_CLASS
from infra.runner.report import make_report

# Import the real pinned backend types in isolation, not approximated test enums.
with mock.patch.dict(sys.modules):
    package = types.ModuleType("app")
    package.__path__ = [str(Path(__file__).parent / "agreement" / "app")]
    sys.modules["app"] = package
    for key in ("app.executor_contract", "app.executor_results", "app.proposals"):
        sys.modules.pop(key, None)
    CONTRACT = importlib.import_module("app.executor_contract")
    DECODE = importlib.import_module("app.executor_results").decode_execution_result
    PROPOSALS = importlib.import_module("app.proposals")

IMAGE = "example.invalid/runner@sha256:" + "a" * 64
REQUEST = UUID("11111111-1111-4111-8111-111111111111")
RUN = UUID("22222222-2222-4222-8222-222222222222")
DATASET = UUID("33333333-3333-4333-8333-333333333333")


class FakeAPI:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.events = []
        self.fail_after = None
        self.fail_before = None
        self.missing_runtime = False
        self.extra_policy = False
        self.block_delete = False

    def request(self, method, path, body=None):
        self.calls.append((method, path, deepcopy(body)))
        if self.fail_before and method == self.fail_before[0] and self.fail_before[1] in path:
            self.fail_before = None
            raise ApiError()
        parsed = urlsplit(path)
        path = parsed.path
        if method == "GET":
            if "runtimeclasses" in path:
                return None if self.missing_runtime else {"handler": RUNTIME_CLASS}
            if path == "/api/v1/namespaces/" + NAMESPACE:
                return {"metadata": {"name": NAMESPACE}}
            if "networking.k8s.io" in path:
                policy = {"metadata": {"name": "default-deny"}, "spec": {
                    "podSelector": {}, "policyTypes": ["Ingress", "Egress"]}}
                return {"items": [policy, policy] if self.extra_policy else [policy]}
            if "projectcalico.org" in path:
                return {"items": []}
            if path == BASE + "/pods":
                return {"items": deepcopy([v for k, v in self.objects.items() if k.startswith(BASE + "/pods/")])}
            if path == BASE + "/events":
                uid = parse_qs(parsed.query)["fieldSelector"][0].split("=", 1)[1]
                return {"items": deepcopy([e for e in self.events if e["involvedObject"]["uid"] == uid])}
            return deepcopy(self.objects.get(path))
        if method == "POST":
            key = path + "/" + body["metadata"]["name"]
            if key in self.objects:
                raise ApiError(409)
            value = deepcopy(body)
            value["metadata"]["uid"] = "uid-" + body["kind"]
            self.objects[key] = value
            if self.fail_after == body["kind"]:
                self.fail_after = None
                raise ApiError()
            return deepcopy(value)
        if method == "DELETE":
            value = self.objects.get(path)
            if not value:
                raise ApiError(404)
            if body["preconditions"]["uid"] != value["metadata"]["uid"]:
                raise ApiError(409)
            if not self.block_delete:
                del self.objects[path]
            return {"kind": "Status", "status": "Success"}
        raise AssertionError(method)

    def pod(self, code="OK", child=0, result=None, *, uid="pod-1"):
        job = next(v for v in self.objects.values() if v["kind"] == "Job")
        pod = deepcopy(job["spec"]["template"])
        pod.update(apiVersion="v1", kind="Pod")
        name = job["metadata"]["name"]
        pod["metadata"].update(name=name + "-pod", namespace=NAMESPACE, uid=uid, ownerReferences=[{
            "apiVersion": "batch/v1", "kind": "Job", "name": name,
            "uid": job["metadata"]["uid"], "controller": True}])
        pod["spec"]["nodeName"] = "trusted-node"
        pod["status"] = {"phase": "Succeeded" if code == "OK" else "Failed", "containerStatuses": [{
            "name": CONTAINER, "restartCount": 0, "imageID": "containerd://verified-config",
            "containerID": "containerd://container-1", "state": {"terminated": {
                "exitCode": EXITS[code], "reason": "Completed", "message": make_report(
                    name, uid, code, child, {"answer": 7} if result is None else result).decode()}}}]}
        self.objects[BASE + "/pods/" + pod["metadata"]["name"]] = pod
        return pod


class AdapterTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[3] / ".m3-runs" / "executor-tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        assert Path(self.temp.name).resolve().is_relative_to(root.resolve())
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "runs.sqlite3"
        self.api = FakeAPI()
        self.dataset_calls = []
        self.teardown = True
        self.executor = self.make_executor()
        self.request = CONTRACT.ExecutorRequest(REQUEST, RUN, DATASET, PROPOSALS.PythonProposal("# inert fixture"), 30)

    def resolve(self, request, cap):
        self.dataset_calls.append((request.dataset_id, cap))
        return b"value\n7\n"

    def make_executor(self, **overrides):
        options = dict(image=IMAGE, resolve_dataset=self.resolve, authorize=lambda request: True,
                       verify_image=lambda image, status: status["imageID"] == "containerd://verified-config",
                       observe_teardown=lambda record: self.teardown, contracts=CONTRACT, decode_result=DECODE)
        options.update(overrides)
        return KataExecutor(self.api, SQLiteRunStore(self.path), **options)

    def submit(self):
        ack = self.executor.submit(self.request)
        self.assertIs(ack.status, CONTRACT.ExecutorStatus.ACCEPTED)
        return ack

    def record(self):
        return self.executor.store.get(str(RUN))

    def test_success_persists_result_and_survives_cleanup_and_restart(self):
        self.submit()
        self.api.pod()
        self.assertEqual(b'{"answer":7}', self.executor.read_result(REQUEST, RUN))
        self.assertIs(self.executor.cleanup(REQUEST, RUN).status, CONTRACT.ExecutorStatus.ACCEPTED)
        self.executor = self.make_executor()
        observation = self.executor.status(REQUEST, RUN)
        self.assertIs(observation.state, CONTRACT.RunState.COMPLETED)
        self.assertIs(observation.cleanup, CONTRACT.CleanupState.CONFIRMED)
        self.assertEqual(b'{"answer":7}', self.executor.read_result(REQUEST, RUN))
        self.assertFalse(self.api.objects)
        self.assertFalse(self.executor.store.pending())
        for method, _, body in self.api.calls:
            if method == "DELETE":
                self.assertTrue(body["preconditions"]["uid"])
                self.assertEqual("Foreground", body["propagationPolicy"])

    def test_repeated_submit_uses_same_snapshot_and_provider_objects(self):
        self.submit()
        self.executor = self.make_executor(resolve_dataset=lambda *_: self.fail("must reuse durable snapshot"))
        self.submit()
        self.assertEqual(2, sum(m == "POST" for m, _, _ in self.api.calls))
        self.assertEqual(1, len(self.dataset_calls))

    def test_lost_create_responses_reconcile_without_duplicate_jobs(self):
        for kind in ("ConfigMap", "Job"):
            with self.subTest(kind=kind):
                self.setUp()
                self.api.fail_after = kind
                self.assertIs(self.executor.submit(self.request).status, CONTRACT.ExecutorStatus.UNKNOWN)
                self.executor = self.make_executor()
                self.submit()
                self.assertEqual(2, sum(m == "POST" for m, _, _ in self.api.calls))

    def test_uncertain_create_with_absent_object_is_never_blindly_retried(self):
        self.api.fail_before = ("POST", JOBS)
        self.assertIs(self.executor.submit(self.request).status, CONTRACT.ExecutorStatus.UNKNOWN)
        self.executor = self.make_executor()
        self.assertIs(self.executor.submit(self.request).status, CONTRACT.ExecutorStatus.UNKNOWN)
        self.assertEqual(2, sum(m == "POST" for m, _, _ in self.api.calls))
        self.assertTrue(self.record()["job_intent"])

    def test_intent_and_snapshot_are_durable_before_remote_mutation(self):
        original = self.api.request

        def inspect(method, path, body=None):
            if method == "POST":
                record = SQLiteRunStore(self.path).get(str(RUN))
                self.assertEqual("# inert fixture", record["cm"]["data"]["script.py"])
                self.assertTrue(record["cm_intent" if body["kind"] == "ConfigMap" else "job_intent"])
            return original(method, path, body)

        self.api.request = inspect
        self.submit()

    def test_unapproved_execution_has_no_api_calls(self):
        self.executor = self.make_executor(authorize=None)
        self.assertIs(self.executor.submit(self.request).status, CONTRACT.ExecutorStatus.REJECTED)
        self.assertFalse(self.api.calls)

    def test_approval_is_rechecked_when_resuming_a_staged_attempt(self):
        self.api.fail_before = ("POST", JOBS)
        self.executor.submit(self.request)
        count = len(self.api.calls)
        self.executor = self.make_executor(authorize=lambda _: False)
        self.assertIs(self.executor.submit(self.request).status, CONTRACT.ExecutorStatus.REJECTED)
        self.assertEqual(count, len(self.api.calls))

    def test_runtime_or_policy_failure_prevents_mutation(self):
        for setting in ("missing_runtime", "extra_policy"):
            with self.subTest(setting=setting):
                setattr(self.api, setting, True)
                self.assertIs(self.executor.submit(self.request).status, CONTRACT.ExecutorStatus.REJECTED)
                self.assertFalse(any(m == "POST" for m, _, _ in self.api.calls))
                setattr(self.api, setting, False)

    def test_input_and_timeout_caps_precede_mutation(self):
        self.executor = self.make_executor(resolve_dataset=lambda *_: b"x" * (524288 + 1))
        self.assertIs(self.executor.submit(self.request).status, CONTRACT.ExecutorStatus.REJECTED)
        bad_timeout = CONTRACT.ExecutorRequest(REQUEST, RUN, DATASET, self.request.proposal, 60)
        self.assertIs(self.executor.submit(bad_timeout).status, CONTRACT.ExecutorStatus.REJECTED)
        self.assertFalse(self.api.calls)

    def test_changed_payload_cannot_rebind_existing_run(self):
        self.submit()
        changed = CONTRACT.ExecutorRequest(REQUEST, RUN, DATASET, PROPOSALS.PythonProposal("# changed"), 30)
        self.assertIs(self.executor.submit(changed).status, CONTRACT.ExecutorStatus.REJECTED)
        self.assertEqual(2, sum(m == "POST" for m, _, _ in self.api.calls))

    def test_other_request_cannot_read_or_delete_run(self):
        self.submit()
        for operation in (self.executor.status, self.executor.read_result, self.executor.cancel, self.executor.cleanup):
            with self.subTest(operation=operation.__name__), self.assertRaisesRegex(ExecutorError, "RESULT_ORIGIN"):
                operation(DATASET, RUN)
        self.assertFalse(any(m == "DELETE" for m, _, _ in self.api.calls))

    def test_foreign_or_replaced_job_is_not_adopted_or_deleted(self):
        self.submit()
        job = next(v for v in self.api.objects.values() if v["kind"] == "Job")
        job["metadata"]["uid"] = "replacement"
        self.assertIs(self.executor.status(REQUEST, RUN).state, CONTRACT.RunState.UNKNOWN)
        self.assertIs(self.executor.cancel(REQUEST, RUN).status, CONTRACT.ExecutorStatus.UNKNOWN)
        self.assertFalse(any(m == "DELETE" for m, _, _ in self.api.calls))

    def test_wrong_report_identity_is_not_a_result(self):
        self.submit()
        pod = self.api.pod()
        pod["status"]["containerStatuses"][0]["state"]["terminated"]["message"] = make_report(
            "other-run", "pod-1", "OK", 0, {"answer": 7}).decode()
        with self.assertRaisesRegex(ExecutorError, "RESULT_UNAVAILABLE"):
            self.executor.read_result(REQUEST, RUN)
        self.assertEqual("RESULT_ORIGIN", self.record()["last_error"])

    def test_image_provenance_is_required(self):
        self.submit()
        self.api.pod()["status"]["containerStatuses"][0]["imageID"] = "containerd://unknown"
        self.assertIs(self.executor.status(REQUEST, RUN).state, CONTRACT.RunState.UNKNOWN)
        self.assertEqual("IMAGE_PROVENANCE_UNVERIFIED", self.record()["last_error"])

    def test_injected_workload_cannot_supply_result(self):
        self.submit()
        self.api.pod()["spec"]["hostNetwork"] = True
        self.assertIs(self.executor.status(REQUEST, RUN).state, CONTRACT.RunState.UNKNOWN)

    def test_multiple_or_replacement_pods_fail_closed(self):
        self.submit()
        first = self.api.pod()
        self.executor.status(REQUEST, RUN)
        # Do not accept a second attempt even if it appears only after the first.
        self.executor.store.save(self.record() | {"outcome": None, "state": "running"})
        first["metadata"]["uid"] = "pod-2"
        self.assertIs(self.executor.status(REQUEST, RUN).state, CONTRACT.RunState.FAILED)
        self.assertEqual("MULTIPLE_POD_ATTEMPTS", self.executor.outcome(REQUEST, RUN)["code"])

    def test_script_failure_does_not_publish_json(self):
        self.submit()
        self.api.pod("SCRIPT_FAILED", 1)
        self.assertIs(self.executor.status(REQUEST, RUN).state, CONTRACT.RunState.FAILED)
        self.assertEqual("SCRIPT_FAILED", self.executor.outcome(REQUEST, RUN)["code"])
        with self.assertRaises(ExecutorError):
            self.executor.read_result(REQUEST, RUN)
        self.assertIs(self.executor.cleanup(REQUEST, RUN).status, CONTRACT.ExecutorStatus.ACCEPTED)

    def test_job_deadline_uses_external_evidence(self):
        self.submit()
        job = next(v for v in self.api.objects.values() if v["kind"] == "Job")
        job["status"] = {"conditions": [{"status": "True", "reason": "DeadlineExceeded", "type": "Failed"}]}
        self.assertIs(self.executor.status(REQUEST, RUN).state, CONTRACT.RunState.FAILED)
        self.assertEqual("RUN_TIMEOUT", self.executor.outcome(REQUEST, RUN)["code"])

    def test_oom_uses_authoritative_termination_not_exit_137(self):
        self.submit()
        pod = self.api.pod("SCRIPT_FAILED", 137)
        pod["status"]["containerStatuses"][0]["state"]["terminated"]["reason"] = "OOMKilled"
        self.executor.status(REQUEST, RUN)
        self.assertEqual("RESOURCE_LIMIT", self.executor.outcome(REQUEST, RUN)["code"])

    def test_backend_nul_rule_is_preserved(self):
        self.submit()
        self.api.pod(result={"x": "\x00"})
        self.assertIs(self.executor.status(REQUEST, RUN).state, CONTRACT.RunState.UNKNOWN)
        self.assertEqual("MALFORMED_EXECUTION_RESULT", self.record()["last_error"])

    def test_cancel_before_submit_is_a_durable_tombstone(self):
        self.assertIs(self.executor.cancel(REQUEST, RUN).status, CONTRACT.ExecutorStatus.ACCEPTED)
        self.executor = self.make_executor()
        self.assertIs(self.executor.submit(self.request).status, CONTRACT.ExecutorStatus.REJECTED)
        self.assertIs(self.executor.status(REQUEST, RUN).state, CONTRACT.RunState.CANCELLED)
        self.assertFalse(self.api.calls)

    def test_cancel_staged_run_cleans_inputs_without_dispatching(self):
        self.api.fail_before = ("POST", JOBS)
        self.executor.submit(self.request)
        self.executor.cancel(REQUEST, RUN)
        self.assertFalse(self.api.objects)
        self.assertIs(self.executor.submit(self.request).status, CONTRACT.ExecutorStatus.REJECTED)

    def test_cancel_running_run_requires_teardown_evidence(self):
        self.submit()
        self.api.pod()
        self.teardown = None
        self.assertIs(self.executor.cancel(REQUEST, RUN).status, CONTRACT.ExecutorStatus.ACCEPTED)
        observation = self.executor.status(REQUEST, RUN)
        self.assertIs(observation.cleanup, CONTRACT.CleanupState.PENDING)
        self.assertIsNot(observation.state, CONTRACT.RunState.CANCELLED)
        self.assertTrue(self.record()["api_absent"])
        self.teardown = True
        self.assertIs(self.executor.status(REQUEST, RUN).state, CONTRACT.RunState.CANCELLED)

    def test_cleanup_preserves_uncollected_results_and_retries_after_restart(self):
        self.submit()
        self.api.pod()
        self.assertIs(self.executor.cleanup(REQUEST, RUN).status, CONTRACT.ExecutorStatus.REJECTED)
        self.executor.read_result(REQUEST, RUN)
        self.api.fail_before = ("DELETE", JOBS)
        self.assertIs(self.executor.cleanup(REQUEST, RUN).status, CONTRACT.ExecutorStatus.UNKNOWN)
        self.executor = self.make_executor()
        self.assertIs(self.executor.status(REQUEST, RUN).cleanup, CONTRACT.CleanupState.CONFIRMED)

    def test_delete_acknowledgement_does_not_confirm_api_absence(self):
        self.submit()
        self.api.pod()
        self.executor.read_result(REQUEST, RUN)
        self.api.block_delete = True
        self.executor.cleanup(REQUEST, RUN)
        self.assertIs(self.executor.status(REQUEST, RUN).cleanup, CONTRACT.CleanupState.PENDING)
        self.assertFalse(self.record()["api_absent"])

    def test_wrong_uid_event_is_ignored(self):
        self.submit()
        self.api.events = [{"metadata": {"namespace": NAMESPACE}, "involvedObject": {"uid": "unrelated"},
                            "message": "runtimeclass not found"}]
        self.assertIs(self.executor.status(REQUEST, RUN).state, CONTRACT.RunState.QUEUED)

    def test_unacknowledged_create_prevents_false_cleanup_confirmation(self):
        self.api.fail_before = ("POST", JOBS)
        self.executor.submit(self.request)
        self.executor.cancel(REQUEST, RUN)
        observation = self.executor.status(REQUEST, RUN)
        self.assertIs(observation.cleanup, CONTRACT.CleanupState.UNKNOWN)
        self.assertIsNot(observation.state, CONTRACT.RunState.CANCELLED)
        # Simulate the timed-out POST arriving after cancellation/absence checks.
        self.api.request("POST", JOBS, self.record()["job"])
        observation = self.executor.status(REQUEST, RUN)
        self.assertIs(observation.cleanup, CONTRACT.CleanupState.CONFIRMED)
        self.assertIs(observation.state, CONTRACT.RunState.CANCELLED)
        self.assertFalse(self.api.objects)

    def test_provider_callback_errors_are_sanitized_and_recoverable(self):
        self.executor = self.make_executor(resolve_dataset=mock.Mock(side_effect=ValueError("private-path")))
        self.assertIs(self.executor.submit(self.request).status, CONTRACT.ExecutorStatus.REJECTED)
        self.assertFalse(self.api.calls)
        self.executor = self.make_executor()
        self.submit()
        self.api.pod()
        self.executor.read_result(REQUEST, RUN)
        self.executor.observe_teardown = mock.Mock(side_effect=ValueError("node-credential"))
        self.assertIs(self.executor.cleanup(REQUEST, RUN).status, CONTRACT.ExecutorStatus.UNKNOWN)
        self.assertEqual("TEARDOWN_UNKNOWN", self.record()["last_error"])

    def test_terminal_job_without_pod_is_unknown_not_permanently_queued(self):
        self.submit()
        job = next(v for v in self.api.objects.values() if v["kind"] == "Job")
        job["status"] = {"conditions": [{"type": "Complete", "status": "True"}]}
        self.assertIs(self.executor.status(REQUEST, RUN).state, CONTRACT.RunState.UNKNOWN)
        self.assertEqual("RESULT_UNAVAILABLE", self.record()["last_error"])

    def test_reconcile_retries_requested_cleanup_and_never_submits(self):
        self.submit()
        self.api.pod()
        self.executor.read_result(REQUEST, RUN)
        self.teardown = None
        self.executor.cleanup(REQUEST, RUN)
        before = sum(m == "POST" for m, _, _ in self.api.calls)
        self.executor = self.make_executor()
        self.teardown = True
        self.assertIs(self.executor.reconcile()[0].cleanup, CONTRACT.CleanupState.CONFIRMED)
        self.assertEqual(before, sum(m == "POST" for m, _, _ in self.api.calls))

    def test_confirmed_cleanup_is_durable_without_reobserving_deleted_objects(self):
        self.submit()
        self.api.pod()
        self.executor.read_result(REQUEST, RUN)
        self.executor.cleanup(REQUEST, RUN)
        self.executor = self.make_executor()
        self.api.request = mock.Mock(side_effect=AssertionError("must use durable completed outcome"))
        self.assertIs(self.executor.status(REQUEST, RUN).cleanup, CONTRACT.CleanupState.CONFIRMED)
        self.assertEqual(str(RUN), self.executor.outcome(REQUEST, RUN)["run_id"])
        self.assertEqual(str(REQUEST), self.executor.outcome(REQUEST, RUN)["request_id"])


if __name__ == "__main__":
    unittest.main()
