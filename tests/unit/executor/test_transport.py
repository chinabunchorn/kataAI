"""Transport tests use mocked processes only; never invoke kubectl or candidates."""

import io
import json
import subprocess
import unittest
from unittest import mock

from infra.executor.transport import ApiError, KubectlAPI, MAX_RESPONSE_BYTES, bounded_command


class Process:
    def __init__(self, stdout=b"{}", stderr=b"", code=0):
        self.stdout, self.stderr, self.stdin = io.BytesIO(stdout), io.BytesIO(stderr), io.BytesIO()
        self.returncode = code
        self.killed = False

    def wait(self, timeout):
        return self.returncode

    def kill(self):
        self.killed = True


class TransportTests(unittest.TestCase):
    def test_output_cap_is_enforced_while_draining(self):
        process = Process(stdout=b"x" * (MAX_RESPONSE_BYTES + 1))
        with mock.patch("infra.executor.transport.subprocess.Popen", return_value=process):
            with self.assertRaises(ApiError):
                bounded_command(["trusted-kubectl"])
        self.assertTrue(process.killed)

    def test_stderr_cap_is_enforced_without_echoing_diagnostics(self):
        process = Process(stderr=b"secret" * 4000)
        with mock.patch("infra.executor.transport.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(ApiError, "^KUBERNETES_API_UNAVAILABLE$"):
                bounded_command(["trusted-kubectl"])

    def test_timeout_kills_process_and_is_sanitized(self):
        process = Process()
        process.wait = mock.Mock(side_effect=[subprocess.TimeoutExpired("private-command", 25), 0])
        with mock.patch("infra.executor.transport.subprocess.Popen", return_value=process):
            with self.assertRaises(ApiError):
                bounded_command(["trusted-kubectl"])
        self.assertTrue(process.killed)

    def test_errors_classify_not_found_without_exposing_input(self):
        process = Process(code=1, stderr=b"Error from server (NotFound): private script contents")
        with mock.patch("infra.executor.transport.subprocess.Popen", return_value=process):
            with self.assertRaises(ApiError) as error:
                bounded_command(["trusted-kubectl"])
        self.assertEqual(404, error.exception.status)
        self.assertNotIn("private", str(error.exception))

    def config(self, **changes):
        return json.dumps({"clusters": [{"cluster": {
            "server": "https://127.0.0.1:16443", "certificate-authority": "/private/ca.crt", **changes}}]}).encode()

    def test_explicit_context_tls_and_raw_create_body(self):
        api = KubectlAPI("/private/config", "kata-client")
        with mock.patch("infra.executor.transport.bounded_command", side_effect=[self.config(), b'{"kind":"Job"}']) as command:
            result = api.request("POST", "/apis/batch/v1/namespaces/kata-lab/jobs", {"kind": "Job"})
        self.assertEqual("Job", result["kind"])
        argv, payload = command.call_args.args
        self.assertIn("kata-client", argv)
        self.assertIn("--request-timeout=20s", argv)
        self.assertIn("--raw", argv)
        self.assertEqual(b'{"kind":"Job"}', payload)
        self.assertNotIn("--insecure-skip-tls-verify", argv)

    def test_insecure_or_non_tls_configuration_is_rejected_before_request(self):
        for changes in ({"insecure-skip-tls-verify": True}, {"server": "http://127.0.0.1:8001"},
                        {"certificate-authority": ""}):
            with self.subTest(changes=changes), mock.patch(
                    "infra.executor.transport.bounded_command", return_value=self.config(**changes)) as command:
                with self.assertRaises(ApiError):
                    KubectlAPI("config", "context").request("GET", "/api/v1/pods")
                self.assertEqual(1, command.call_count)

    def test_get_missing_resource_returns_none_but_create_is_uncertain(self):
        for method in ("GET", "POST"):
            with self.subTest(method=method), mock.patch("infra.executor.transport.bounded_command",
                    side_effect=[self.config(), ApiError(404)]):
                api = KubectlAPI("config", "context")
                if method == "GET":
                    self.assertIsNone(api.request(method, "/api/v1/namespaces/kata-lab/configmaps/missing"))
                else:
                    with self.assertRaises(ApiError):
                        api.request(method, "/api/v1/namespaces/kata-lab/configmaps", {})

    def test_malformed_response_is_sanitized(self):
        with mock.patch("infra.executor.transport.bounded_command", side_effect=[self.config(), b"private non-json response"]):
            with self.assertRaisesRegex(ApiError, "^KUBERNETES_API_UNAVAILABLE$"):
                KubectlAPI("config", "context").request("GET", "/api/v1/pods")


if __name__ == "__main__":
    unittest.main()
