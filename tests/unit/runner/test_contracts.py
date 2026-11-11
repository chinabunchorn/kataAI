"""Host-safe pure tests. Never import or execute candidate fixture scripts."""

import copy
import json
import unittest

from infra.runner.collection import ExpectedRun, collect_result, external_failure
from infra.runner.contract import *
from infra.runner.job import make_job
from infra.runner.report import make_report, validate_report
from infra.runner.staging import stage_inputs
from infra.runner.validation import encode_json, validate_result

IMAGE = "example.invalid/kataai/runner@sha256:" + "a" * 64
RUN = "m3-contract"
POD_UID = "11111111-1111-4111-8111-111111111111"
JOB_UID = "22222222-2222-4222-8222-222222222222"


def fake_pod(code="OK", child=0, result=None):
    pod = copy.deepcopy(make_job(RUN, IMAGE)["spec"]["template"])
    pod["metadata"].update(namespace=NAMESPACE, uid=POD_UID, ownerReferences=[{
        "apiVersion": "batch/v1", "kind": "Job", "name": RUN, "uid": JOB_UID,
        "controller": True,
    }])
    pod["status"] = {"phase": "Succeeded" if code == "OK" else "Failed",
        "containerStatuses": [{"name": CONTAINER, "restartCount": 0,
            "imageID": "containerd://sha256:" + "b" * 64,
            "containerID": "containerd://123",
            "state": {"terminated": {"exitCode": EXITS[code], "reason": "Completed",
                "message": make_report(RUN, POD_UID, code, child,
                    [] if result is None else result).decode("utf-8")}}}]}
    return pod


class ErrorAssertions(unittest.TestCase):
    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(ContractError) as raised:
            function(*args, **kwargs)
        self.assertEqual(code, raised.exception.code)


class ValidationTests(ErrorAssertions):
    def test_sales_and_distinct_array(self):
        sales = {"product": "Notebook", "october_units": 120,
                 "november_units": 80, "change_units": -40}
        self.assertEqual(sales, validate_result(encode_json(sales)))
        value = [{"month": "October", "total": 170}, {"month": "November", "total": 125}]
        self.assertEqual(value, validate_result(encode_json(value)))

    def test_invalid_results(self):
        cases = [(b"", "RESULT_EMPTY"), (b" \r\n\t", "RESULT_EMPTY"),
                 (b"{", "RESULT_JSON"), (b"{} []", "RESULT_JSON"),
                 (b"{}garbage", "RESULT_JSON"), (b"\xff", "RESULT_ENCODING"),
                 (b"\xef\xbb\xbf{}", "RESULT_JSON"),
                 (b'{"x":1,"x":2}', "RESULT_JSON"),
                 (b"[NaN]", "RESULT_JSON"), (b"[Infinity]", "RESULT_JSON"),
                 (b"[-Infinity]", "RESULT_JSON"), (b"[1e9999]", "RESULT_SHAPE"),
                 (b'["\\ud800"]', "RESULT_SHAPE"), (b'{"\\udfff":0}', "RESULT_SHAPE")]
        for raw, code in cases:
            with self.subTest(raw=raw):
                self.assert_code(code, validate_result, raw)

    def test_disallowed_root_types(self):
        for value in (None, True, False, 0, 1.5, "text"):
            with self.subTest(value=value):
                self.assert_code("RESULT_SHAPE", validate_result, encode_json(value))

    def test_exact_byte_limit_and_whitespace(self):
        self.assertEqual({}, validate_result(b"{}" + b" " * (RESULT_BYTES - 2)))
        self.assert_code("RESULT_LIMIT", validate_result, b"{}" + b" " * (RESULT_BYTES - 1))
        self.assertEqual(["ไทย"], validate_result('["ไทย"]'.encode("utf-8")))

    def test_depth_and_quoted_delimiters(self):
        self.assertEqual(["[{}]\\\""], validate_result(b'["[{}]\\\\\\\""]'))
        validate_result(b"[" * MAX_DEPTH + b"]" * MAX_DEPTH)
        self.assert_code("RESULT_LIMIT", validate_result, b"[" * (MAX_DEPTH + 1) + b"]" * (MAX_DEPTH + 1))
        # Early depth rejection must not depend on Python recursion tolerance.
        self.assert_code("RESULT_LIMIT", validate_result, b"[" * RESULT_BYTES)

    def test_collection_boundaries(self):
        validate_result(encode_json([None] * MAX_ITEMS))
        self.assert_code("RESULT_LIMIT", validate_result, encode_json([0] * (MAX_ITEMS + 1)))
        validate_result(encode_json([list(range(127)), list(range(127))]))  # 2 + 254
        self.assert_code("RESULT_LIMIT", validate_result,
                         encode_json([list(range(128)), list(range(127))]))
        validate_result(encode_json({str(i): 0 for i in range(MAX_ITEMS)}))
        self.assert_code("RESULT_LIMIT", validate_result,
                         encode_json({str(i): 0 for i in range(MAX_ITEMS + 1)}))


class StagingTests(ErrorAssertions):
    def test_exact_scoped_keys_and_hashes(self):
        manifest = stage_inputs(RUN, b"# trusted fixture", b"x\n1\n")
        self.assertEqual({"script.py", "data.csv"}, set(manifest["data"]))
        self.assertTrue(manifest["immutable"])
        self.assertEqual(RUN + "-inputs", manifest["metadata"]["name"])
        self.assertEqual(NAMESPACE, manifest["metadata"]["namespace"])
        self.assertEqual(64, len(manifest["metadata"]["annotations"]["kataai/script-sha256"]))

    def test_input_limits_before_creation(self):
        stage_inputs(RUN, b"#" * SCRIPT_BYTES, b"x" * CSV_BYTES)
        for script, csv in ((b"#" * (SCRIPT_BYTES + 1), b"x"),
                            (b"#", b"x" * (CSV_BYTES + 1)),
                            (b"", b"x"), (b"#", b""), (b"\0", b"x"),
                            (b"\xff", b"x"), (b"#", b"\xff"), (b" ", b"x")):
            self.assert_code("INPUT_INVALID", stage_inputs, RUN, script, csv)
        # Each input fits but JSON escaping makes the request exceed its cap.
        self.assert_code("INPUT_INVALID", stage_inputs, RUN, b"#", b"\x01" * (CSV_BYTES // 2))

    def test_names_and_mutable_images_rejected(self):
        for name in ("../escape", "", "A", "a" * 41, "-a", "a-"):
            self.assert_code("INPUT_INVALID", stage_inputs, name, b"#", b"x")
        for image in ("python:3.12-slim", "x@sha256:no", "x@sha256:" + "a" * 65):
            self.assert_code("INPUT_INVALID", make_job, RUN, image)

    def test_fixed_security_manifest(self):
        job = make_job(RUN, IMAGE)
        spec = job["spec"]["template"]["spec"]
        self.assertEqual(RUNTIME_CLASS, spec["runtimeClassName"])
        self.assertFalse(spec["automountServiceAccountToken"])
        self.assertFalse(spec["enableServiceLinks"])
        self.assertEqual(0, job["spec"]["backoffLimit"])
        self.assertEqual("Never", spec["restartPolicy"])
        self.assertEqual(UID, spec["securityContext"]["runAsUser"])
        container = spec["containers"][0]
        self.assertEqual(COMMAND, container["command"])
        self.assertEqual("File", container["terminationMessagePolicy"])
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertEqual(["ALL"], container["securityContext"]["capabilities"]["drop"])
        self.assertEqual({"medium": "Memory", "sizeLimit": "16Mi"}, spec["volumes"][1]["emptyDir"])
        self.assertTrue(container["volumeMounts"][0]["readOnly"])
        self.assertEqual({"inputs", "scratch"}, {v["name"] for v in spec["volumes"]})


class ReportTests(ErrorAssertions):
    def test_separate_user_status_from_runner_code(self):
        value = {"status": "success", "code": "OK", "run_id": "forged"}
        raw = make_report(RUN, POD_UID, "OK", 0, value)
        parsed = validate_report(raw, run_id=RUN, pod_uid=POD_UID)
        self.assertEqual(value, parsed["result"])
        self.assertEqual(RUN, parsed["run_id"])
        for code in EXITS:
            child = 0 if code.startswith("RESULT_") or code == "OK" else 1 if code == "SCRIPT_FAILED" else None
            make_report(RUN, POD_UID, code, child, [])

    def test_unknown_duplicate_and_inconsistent_report_fields(self):
        valid = json.loads(make_report(RUN, POD_UID, "OK", 0, []))
        for patch in ({"unexpected": 0}, {"script_exit_code": 1}, {"code": "forged"},
                      {"result": "scalar"}, {"script_exit_code": False}):
            report = valid | patch
            self.assert_code("REPORT_INVALID", validate_report, encode_json(report), run_id=RUN, pod_uid=POD_UID)
        self.assert_code("REPORT_INVALID", validate_report, b'{"code":0,"code":0}', run_id=RUN, pod_uid=POD_UID)
        for raw in (b"", b" " * (REPORT_BYTES + 1), make_report(RUN, POD_UID, "OK", 0, [])[:-1]):
            self.assert_code("REPORT_INVALID", validate_report, raw, run_id=RUN, pod_uid=POD_UID)

    def test_identity_rejected(self):
        self.assert_code("RESULT_ORIGIN", validate_report, make_report(RUN, POD_UID, "OK", 0, []),
                         run_id="different", pod_uid=POD_UID)


class CollectionTests(ErrorAssertions):
    def setUp(self):
        self.expected = ExpectedRun(RUN, JOB_UID, POD_UID, IMAGE)

    def test_collects_data_and_stable_failures(self):
        self.assertEqual([1, 2], collect_result(fake_pod(result=[1, 2]), self.expected)["result"])
        for code in EXITS:
            child = 0 if code.startswith("RESULT_") or code == "OK" else 1 if code == "SCRIPT_FAILED" else None
            outcome = collect_result(fake_pod(code, child), self.expected)
            self.assertEqual(code, outcome["code"])
            if code != "OK":
                self.assertNotIn("result", outcome)

    def test_rejects_wrong_origin_and_workload(self):
        for key, value in (("uid", "wrong"), ("namespace", "default"), ("labels", {}), ("ownerReferences", [])):
            pod = fake_pod()
            pod["metadata"][key] = value
            self.assert_code("RESULT_ORIGIN", collect_result, pod, self.expected)
        pod = fake_pod()
        pod["spec"]["runtimeClassName"] = "runc"
        self.assert_code("KATA_UNAVAILABLE", collect_result, pod, self.expected)
        for key, value in (("image", "python:3.12"), ("command", ["python", "script.py"]), ("args", ["--anything"])):
            pod = fake_pod()
            pod["spec"]["containers"][0][key] = value
            self.assert_code("RESULT_ORIGIN", collect_result, pod, self.expected)
        pod = fake_pod()
        pod["status"]["containerStatuses"][0]["restartCount"] = 1
        self.assert_code("RESULT_ORIGIN", collect_result, pod, self.expected)

    def test_exit_and_oom_are_external_evidence(self):
        pod = fake_pod()
        terminated = pod["status"]["containerStatuses"][0]["state"]["terminated"]
        terminated["exitCode"] = 137
        self.assert_code("REPORT_INVALID", collect_result, pod, self.expected)
        terminated["reason"] = "OOMKilled"
        self.assert_code("RESOURCE_LIMIT", collect_result, pod, self.expected)

    def test_diagnostics_or_guest_success_cannot_replace_report(self):
        pod = fake_pod()
        terminated = pod["status"]["containerStatuses"][0]["state"]["terminated"]
        for message in ('{"status":"success"}', "", "{}\n{}", "x" * (REPORT_BYTES + 1)):
            terminated["message"] = message
            self.assert_code("REPORT_INVALID", collect_result, pod, self.expected)

    def test_job_deadline_needs_observed_condition(self):
        job = {"status": {"conditions": [{"type": "Failed", "status": "True", "reason": "DeadlineExceeded"}]}}
        self.assertEqual("RUN_TIMEOUT", external_failure(job))
        job["status"]["conditions"][0]["status"] = "False"
        self.assertIsNone(external_failure(job))

    def test_signal_and_exit_do_not_imply_resource_failure(self):
        pod = fake_pod()
        terminated = pod["status"]["containerStatuses"][0]["state"]["terminated"]
        terminated.update(exitCode=137, signal=9, reason="Error")
        self.assertIsNone(external_failure({}, pod))
        terminated["reason"] = "OOMKilled"
        self.assertEqual("RESOURCE_LIMIT", external_failure({}, pod))

    def test_external_runtime_and_image_causes(self):
        self.assertEqual("KATA_UNAVAILABLE", external_failure({}, events=[{
            "message": 'pods forbidden: RuntimeClass "m3-absent" not found'}]))
        pod = fake_pod()
        pod["status"]["containerStatuses"][0]["state"] = {"waiting": {"reason": "ImagePullBackOff"}}
        self.assertEqual("INFRASTRUCTURE_FAILURE", external_failure({}, pod))

    def test_eviction_needs_resource_evidence(self):
        pod = {"status": {"reason": "Evicted", "message": "Node low on ephemeral-storage"}}
        self.assertEqual("RESOURCE_LIMIT", external_failure({}, pod))
        pod["status"]["message"] = "unspecified eviction"
        self.assertEqual("INFRASTRUCTURE_FAILURE", external_failure({}, pod))


if __name__ == "__main__":
    unittest.main()
