"""Supervisor control-flow tests with every process launch mocked.

No candidate source is compiled/imported/executed by this host suite.
"""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from infra.runner import supervisor
from infra.runner.contract import DIAGNOSTIC_BYTES, EXITS, ContractError

RUN = "m3-unit"
POD = "pod-unit"


class MainTests(unittest.TestCase):
    def run_main(self, raw=None, child_code="OK", child_exit=0, read_error=None):
        with (patch.object(supervisor, "preflight", return_value=(RUN, POD)),
              patch.object(supervisor, "run_child", return_value=(child_code, child_exit, {})) as child,
              patch.object(supervisor.os.path, "lexists", return_value=False),
              patch.object(supervisor, "_read_file", return_value=raw, side_effect=read_error),
              patch.object(supervisor, "_write_report") as write,
              patch.object(supervisor.sys, "stdout")):
            exit_code = supervisor.main()
            child.assert_called_once()
            report = json.loads(write.call_args.args[0])
            return exit_code, report

    def test_success_and_missing_invalid_output(self):
        code, report = self.run_main(b'[1,{"status":"success"}]')
        self.assertEqual(0, code)
        self.assertEqual([1, {"status": "success"}], report["result"])
        for raw, error in ((b"", "RESULT_EMPTY"), (b"not JSON", "RESULT_JSON"),
                           (b"\xff", "RESULT_ENCODING"), (b"0", "RESULT_SHAPE"),
                           (b"[" * 17, "RESULT_LIMIT")):
            with self.subTest(error=error):
                code, report = self.run_main(raw)
                self.assertEqual(EXITS[error], code)
                self.assertEqual(error, report["code"])
                self.assertNotIn("result", report)
        code, report = self.run_main(read_error=FileNotFoundError())
        self.assertEqual(EXITS["RESULT_MISSING"], code)

    def test_failure_cannot_publish_existing_valid_result(self):
        code, report = self.run_main(b'{"status":"success"}', "SCRIPT_FAILED", 1)
        self.assertEqual(EXITS["SCRIPT_FAILED"], code)
        self.assertNotIn("result", report)
        self.assertEqual(1, report["script_exit_code"])

    def test_timeout_and_log_flood_keep_distinct_mapping(self):
        for error in ("RUN_TIMEOUT", "DIAGNOSTIC_LIMIT"):
            code, report = self.run_main(b"[]", error, -9)
            self.assertEqual(EXITS[error], code)
            self.assertEqual(-9, report["script_exit_code"])

    def test_unsafe_preflight_never_launches_child(self):
        with (patch.object(supervisor, "preflight", side_effect=ContractError("INPUT_INVALID")),
              patch.object(supervisor, "run_child") as child,
              patch.object(supervisor.os, "environ", {"KATAAI_RUN_ID": RUN, "KATAAI_POD_UID": POD}),
              patch.object(supervisor, "_write_report") as write,
              patch.object(supervisor.sys, "stdout")):
            self.assertEqual(EXITS["INPUT_INVALID"], supervisor.main())
            child.assert_not_called()
            self.assertEqual("INPUT_INVALID", json.loads(write.call_args.args[0])["code"])

    def test_report_channel_failure_never_returns_success(self):
        with (patch.object(supervisor, "preflight", return_value=(RUN, POD)),
              patch.object(supervisor, "run_child", return_value=("OK", 0, {})),
              patch.object(supervisor.os.path, "lexists", return_value=False),
              patch.object(supervisor, "_read_file", return_value=b"[]"),
              patch.object(supervisor, "_write_report", side_effect=OSError("full")),
              patch.object(supervisor.sys, "stdout")):
            self.assertEqual(EXITS["RUNNER_INTERNAL"], supervisor.main())


class ChildControlTests(unittest.TestCase):
    def child_and_selector(self):
        child = MagicMock()
        child.pid = 123456
        child.returncode = 0
        child.poll.return_value = None
        selector = MagicMock()
        key = SimpleNamespace(fileobj=child.stdout, data="stdout")
        selector.select.return_value = [(key, 1)]
        selector.get_map.return_value = {1: key}
        return child, selector

    def test_log_flood_is_bounded_without_executing_process(self):
        child, selector = self.child_and_selector()
        child.returncode = -9
        with (patch.object(supervisor.subprocess, "Popen", return_value=child) as popen,
              patch.object(supervisor.selectors, "DefaultSelector", return_value=selector),
              patch.object(supervisor.os, "set_blocking"),
              patch.object(supervisor.os, "read", return_value=b"x" * 4096),
              patch.object(supervisor, "_kill_group") as kill,
              patch.object(supervisor.time, "monotonic", return_value=0)):
            code, exit_code, diagnostics = supervisor.run_child()
            self.assertEqual("DIAGNOSTIC_LIMIT", code)
            self.assertEqual(-9, exit_code)
            self.assertEqual(DIAGNOSTIC_BYTES, len(diagnostics["stdout"]))
            self.assertEqual(b"", diagnostics["stderr"])
            kill.assert_called()
            self.assertEqual([supervisor.sys.executable, "-I", "-B", "/inputs/script.py"], popen.call_args.args[0])
            self.assertNotIn("shell", popen.call_args.kwargs)
            self.assertNotIn("KATAAI_RUN_ID", popen.call_args.kwargs["env"])
            self.assertTrue(popen.call_args.kwargs["start_new_session"])
            child.wait.assert_called_once_with(timeout=1)

    def test_measured_timeout_is_not_generic_nonzero_exit(self):
        child, selector = self.child_and_selector()
        child.returncode = -9
        with (patch.object(supervisor.subprocess, "Popen", return_value=child),
              patch.object(supervisor.selectors, "DefaultSelector", return_value=selector),
              patch.object(supervisor.os, "set_blocking"),
              patch.object(supervisor, "_kill_group"),
              patch.object(supervisor.time, "monotonic", side_effect=[0, 31])):
            self.assertEqual("RUN_TIMEOUT", supervisor.run_child()[0])
            selector.select.assert_not_called()

    def test_inherited_pipe_wait_is_bounded_after_exit(self):
        child, selector = self.child_and_selector()
        child.poll.return_value = 1
        child.returncode = 1
        selector.select.return_value = []  # Descendant keeps pipe open.
        with (patch.object(supervisor.subprocess, "Popen", return_value=child),
              patch.object(supervisor.selectors, "DefaultSelector", return_value=selector),
              patch.object(supervisor.os, "set_blocking"),
              patch.object(supervisor, "_kill_group"),
              patch.object(supervisor.time, "monotonic", side_effect=[0, 0.1, 1.2])):
            self.assertEqual("SCRIPT_FAILED", supervisor.run_child()[0])
            selector.select.assert_called_once()
            child.wait.assert_called_once_with(timeout=1)


if __name__ == "__main__":
    unittest.main()
