"""Host-only scratch preflight tests; no filesystem writes or candidate launches."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from infra.runner import scratch, supervisor
from infra.runner.contract import ContractError, EXITS, MOUNTINFO_BYTES

SCRATCH_BYTES = 16 * 1024 * 1024  # Historical requested size, not a capacity gate.

MOUNT = b"45 30 0:40 / /tmp rw - tmpfs tmpfs rw,size=16384k\n"


def stats(capacity=SCRATCH_BYTES, flag=0, available=4096):
    return SimpleNamespace(f_frsize=4096, f_blocks=capacity // 4096,
                           f_flag=flag, f_bavail=available)


class ScratchTests(unittest.TestCase):
    def setUp(self):
        self.readonly = patch.object(scratch.os, "ST_RDONLY", 1, create=True)
        self.readonly.start()
        self.addCleanup(self.readonly.stop)

    def test_writable_capacities_accept_used_space(self):
        for capacity in (4096, SCRATCH_BYTES, 100691968, SCRATCH_BYTES + 4096, SCRATCH_BYTES - 4096):
            with self.subTest(capacity=capacity):
                scratch.validate_scratch(stats(capacity, available=1), MOUNT)
        # The recorded unmodified runtime omits a tmpfs size option.
        scratch.validate_scratch(stats(100691968), MOUNT.replace(b",size=16384k", b""))

    def test_empty_or_invalid_filesystem_rejected(self):
        for capacity, available in ((0, 1), (-4096, 1), (SCRATCH_BYTES, 0), (SCRATCH_BYTES, -1)):
            with self.subTest(capacity=capacity), self.assertRaises(ContractError) as raised:
                scratch.validate_scratch(stats(capacity, available=available), MOUNT)
            self.assertEqual("INPUT_INVALID", raised.exception.code)

    def test_mount_identity_encoding_bounds_and_readonly_rejected(self):
        for mount in (b"", MOUNT.replace(b"/tmp", b"/tmp/other"),
                      MOUNT.replace(b"- tmpfs", b"- ext4"), MOUNT + MOUNT,
                      MOUNT.replace(b"/tmp rw", b"/tmp ro"),
                      b"45 30 0:40 / /tmp rw\n", b"\xff",
                      b"x" * (MOUNTINFO_BYTES + 1)):
            with self.subTest(mount=mount[:50]), self.assertRaises(ContractError):
                scratch.validate_scratch(stats(), mount)
        with self.assertRaises(ContractError):
            scratch.validate_scratch(stats(flag=1), MOUNT)
        for fragment in (0, -1):
            value = stats()
            value.f_frsize = fragment
            with self.assertRaises(ContractError):
                scratch.validate_scratch(value, MOUNT)

    def test_real_preflight_controls_child_launch(self):
        # Exercise main -> real preflight -> real scratch validator; mock OS only.
        for capacity, read_error, expected in (
            (0, None, "INPUT_INVALID"),
            (SCRATCH_BYTES, OSError("unavailable"), "INPUT_INVALID"),
            (100691968, None, "SCRIPT_FAILED"),
            (4096, None, "SCRIPT_FAILED"),
        ):
            def read(path, cap, **kwargs):
                if path == "/proc/self/mountinfo":
                    if read_error:
                        raise read_error
                    return MOUNT
                return b"# trusted input bytes"

            with (patch.object(supervisor.sys, "platform", "linux"),
                  patch.object(supervisor.os, "getuid", return_value=10001, create=True),
                  patch.object(supervisor.os, "getgid", return_value=10001, create=True),
                  patch.object(supervisor.os, "environ", {"KATAAI_RUN_ID": "m3-unit", "KATAAI_POD_UID": "pod-unit"}),
                  patch.object(supervisor, "Path") as path,
                  patch.object(supervisor, "_read_file", side_effect=read),
                  patch.object(supervisor, "_denied_write"),
                  patch.object(supervisor, "validate_scratch", wraps=scratch.validate_scratch) as validate,
                  patch.object(supervisor.os, "statvfs", side_effect=[stats(flag=1), stats(capacity)], create=True),
                  patch.object(supervisor, "run_child", return_value=("SCRIPT_FAILED", 1, {})) as child,
                  patch.object(supervisor, "_write_report") as report,
                  patch.object(supervisor.sys, "stdout")):
                path.return_value.exists.return_value = False
                self.assertEqual(EXITS[expected], supervisor.main())
                if expected == "INPUT_INVALID":
                    child.assert_not_called()
                else:
                    child.assert_called_once_with()
                if read_error is None:
                    validate.assert_called_once()
                else:
                    validate.assert_not_called()
                self.assertIn(('"code":"' + expected + '"').encode(), report.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
