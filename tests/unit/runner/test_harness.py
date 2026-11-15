"""Checks harness configuration with fake Kubernetes transport only."""

import importlib.util
import io
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
HARNESS = ROOT / "tests/infrastructure/m3"
sys.path.insert(0, str(HARNESS))
import catalog
import kube as kube_transport
spec = importlib.util.spec_from_file_location("m3_harness", HARNESS / "run.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

from infra.runner.contract import RUNTIME_CLASS
from infra.runner.job import make_job
from infra.runner.staging import stage_inputs


@contextmanager
def temporary_workspace():
    base = ROOT / ".m3-runs"
    base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as directory:
        # Verify cleanup's resolved target stays in the intended workspace.
        assert Path(directory).resolve().is_relative_to(base.resolve())
        yield directory


class HarnessTests(unittest.TestCase):
    def test_legacy_quota_cases_are_excluded_from_release_execution(self):
        self.assertEqual({"scratch", "scratch-failure", "scratch-multifile"},
                         set(catalog.LEGACY_SCRATCH_CASES))
        self.assertTrue(set(catalog.LEGACY_SCRATCH_CASES).isdisjoint(catalog.CASES))
        self.assertIn("security", catalog.CASES)
        self.assertIn("scratch-layout", catalog.CASES)

    def test_preflight_distinguishes_namespaced_and_global_policy(self):
        class FakeKube:
            global_items = []
            calico_items = [{"metadata": {"namespace": "calico-system"}}]
            def call(self, *args):
                if args[1] == "runtimeclass":
                    return {"handler": RUNTIME_CLASS}
                if args[1] == "namespace":
                    return {"metadata": {}}
                items = self.global_items if args[1].startswith("global") else self.calico_items
                return {"items": items}
            def get(self, *args):
                return {"items": [{"metadata": {"name": "default-deny"}, "spec": {
                    "podSelector": {}, "policyTypes": ["Ingress", "Egress"]}}]}
        kube = FakeKube()
        with temporary_workspace() as directory:
            harness.check_preconditions(kube, Path(directory))
            kube.calico_items = [{"metadata": {"namespace": "kata-lab"}}]
            with self.assertRaisesRegex(RuntimeError, "applicable"):
                harness.check_preconditions(kube, Path(directory))
            kube.calico_items = []
            kube.global_items = [{"metadata": {"name": "some-global-policy"}}]
            with self.assertRaisesRegex(RuntimeError, "applicable"):
                harness.check_preconditions(kube, Path(directory))

    def test_ssh_transport_quotes_remote_arguments(self):
        argv = kube_transport.SSHKube("katavm").argv("get", "pods", "--field-selector", "a=b; touch nope")
        self.assertIn("'a=b; touch nope'", argv[-1])
        for host in ("-oProxyCommand=x", "katavm;whoami", "user@host"):
            with self.assertRaises(ValueError):
                kube_transport.SSHKube(host)

    def test_api_pipe_collection_is_bounded(self):
        class FakeProcess:
            returncode = 0
            def __init__(self, stdout, stderr):
                self.stdout = io.BytesIO(stdout)
                self.stderr = io.BytesIO(stderr)
                self.stdin = io.BytesIO()
                self.killed = False
            def wait(self, timeout):
                return 0
            def kill(self):
                self.killed = True
        process = FakeProcess(b'{"items":[]}', b"")
        with patch.object(kube_transport.subprocess, "Popen", return_value=process):
            self.assertEqual(b'{"items":[]}', kube_transport.bounded_command(["not-executed"]))
        for stdout, stderr in ((b"x" * (1024 * 1024 + 1), b""), (b"", b"x" * 16385)):
            process = FakeProcess(stdout, stderr)
            with patch.object(kube_transport.subprocess, "Popen", return_value=process):
                with self.assertRaisesRegex(RuntimeError, "limit exceeded"):
                    kube_transport.bounded_command(["not-executed"])
                self.assertTrue(process.killed)

    def test_every_catalog_case_stages_without_executing_candidate(self):
        csv = (ROOT / "tests/infrastructure/m1/data.csv").read_bytes()
        for name in catalog.CASES:
            with self.subTest(name=name):
                cm = stage_inputs("m3-" + name, catalog.case_script(name), csv)
                self.assertEqual({"script.py", "data.csv"}, set(cm["data"]))
                job = make_job("m3-" + name, "example.invalid/runner@sha256:" + "a" * 64)
                self.assertEqual(RUNTIME_CLASS, job["spec"]["template"]["spec"]["runtimeClassName"])

    def test_uid_precondition_cleanup_is_scoped(self):
        class FakeKube:
            def __init__(self):
                self.deletes = []
            def delete_uid(self, path, uid):
                self.deletes.append((path, uid))
            def call(self, *args, **kwargs):
                return {"items": []}
            def get(self, *args):
                return None
        kube = FakeKube()
        with temporary_workspace() as directory:
            harness.cleanup(kube, "m3-unit", {"job": "job-uid", "configmap": "cm-uid"}, Path(directory))
            self.assertEqual([
                ("/apis/batch/v1/namespaces/kata-lab/jobs/m3-unit", "job-uid"),
                ("/api/v1/namespaces/kata-lab/configmaps/m3-unit-inputs", "cm-uid")], kube.deletes)

    def test_render_default_does_not_contact_cluster(self):
        with temporary_workspace() as directory:
            with (patch.object(harness, "ROOT", Path(directory)),
                  patch.object(harness, "case_script", return_value=b"# trusted bytes"),
                  patch.object(harness, "stage_inputs", return_value={"kind": "ConfigMap"}),
                  patch.object(harness, "make_job", return_value={"kind": "Job"}),
                  patch.object(harness, "execute") as execute,
                  patch.object(sys, "argv", ["run.py", "--case", "sales", "--run-id", "m3-unit",
                      "--image", "example.invalid/runner@sha256:" + "a" * 64]),
                  patch.object(Path, "read_bytes", return_value=b"x\n1\n"),
                  patch("builtins.print")):
                harness.main()
                execute.assert_not_called()
                self.assertTrue((Path(directory) / ".m3-runs/m3-unit/job.json").is_file())


if __name__ == "__main__":
    unittest.main()
