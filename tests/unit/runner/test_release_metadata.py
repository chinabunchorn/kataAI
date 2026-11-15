"""Cross-file release contracts, without invoking a builder or candidate code."""

from pathlib import Path
import re
import unittest

from infra.runner.contract import VERSION, PROTOCOL

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "infra/runner"


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_version_consistent(self):
        self.assertEqual("0.1.1", VERSION)
        self.assertEqual("kataai.runner.v1", PROTOCOL)
        dockerfile = (SOURCE / "Dockerfile").read_text()
        self.assertEqual(VERSION, re.search(r'image.version="([^"]+)"', dockerfile)[1])
        build = (SOURCE / "build.ps1").read_text()
        self.assertEqual(VERSION, re.search(r"runner_version='([^']+)'", build)[1])
        tag_pattern = re.search(r"\$Repository -notmatch '([^']+)'", build)[1]
        self.assertIsNotNone(re.fullmatch(tag_pattern, "example.invalid/runner:" + VERSION))
        self.assertIsNone(re.fullmatch(tag_pattern, "example.invalid/runner:0.1.0"))
        self.assertIn(":0\\.1\\.1$", build)
        self.assertIn("--tag <repository>:" + VERSION, build)
        readme = (SOURCE / "README.md").read_text()
        self.assertTrue(readme.startswith("# Fixed Python runner " + VERSION))
        self.assertIn("kataai-runner:" + VERSION, readme)

    def test_build_provenance_covers_image_and_host_runner_files(self):
        build = (SOURCE / "build.ps1").read_text()
        recorded = set(re.findall(r"'([^']+)'", re.search(r'\$sourceFiles = @\(([^\n]+)\)', build)[1]))
        required = {path.name for path in SOURCE.glob("*.py")}
        required.update({"Dockerfile", ".dockerignore", "requirements.txt", "build.ps1"})
        self.assertEqual(required, recorded)
        self.assertLess(build.index("$hashes ="), build.index("& docker buildx build"))
        self.assertIn("$inspection.manifest_digest -ne $digest", build)
        self.assertIn("source_worktree_status=$sourceStatus", build)
        self.assertIn("artifact_inspection=$inspection", build)
        self.assertIn("Source changed during build", build)
        self.assertIn("live_kata_acceptance_verified=$false", build)


if __name__ == "__main__":
    unittest.main()
