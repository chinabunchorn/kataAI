"""Static OCI artifact checks with tiny trusted synthetic archives; no execution."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from infra.runner.verify_artifact import inspect_oci

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "infra/runner"


def synthetic_archive(path, *, directory_mode=0o555, user="10001:10001", bad_hash=False):
    layer_stream = io.BytesIO()
    with tarfile.open(fileobj=layer_stream, mode="w") as layer:
        for name, mode in (("opt", 0o755), ("opt/kataai", directory_mode), ("opt/kataai/runnerlib", 0o555)):
            member = tarfile.TarInfo(name)
            member.type = tarfile.DIRTYPE
            member.mode = mode
            layer.addfile(member)
        for source in ("__init__.py", "contract.py", "validation.py", "staging.py", "report.py", "scratch.py", "supervisor.py", "entrypoint.py"):
            name = "opt/kataai/runner.py" if source == "entrypoint.py" else "opt/kataai/runnerlib/" + source
            raw = (SOURCE / source).read_bytes()
            member = tarfile.TarInfo(name)
            member.mode, member.size = 0o555, len(raw)
            layer.addfile(member, io.BytesIO(raw))
    blobs = {}
    def blob(raw, media):
        digest = hashlib.sha256(raw).hexdigest()
        blobs["blobs/sha256/" + digest] = raw
        return {"digest": "sha256:" + digest, "size": len(raw), "mediaType": media}
    layer = blob(layer_stream.getvalue(), "application/vnd.oci.image.layer.v1.tar")
    config = blob(json.dumps({"os": "linux", "architecture": "amd64", "config": {
        "User": user, "Entrypoint": ["python3", "-I", "-B", "/opt/kataai/runner.py"],
        "WorkingDir": "/tmp", "Env": ["PYTHON_VERSION=3.12.16"],
        "Labels": {"org.opencontainers.image.version": "0.1.1"}}}).encode(),
        "application/vnd.oci.image.config.v1+json")
    manifest = blob(json.dumps({"schemaVersion": 2, "config": config, "layers": [layer]}).encode(),
                    "application/vnd.oci.image.manifest.v1+json")
    index = json.dumps({"schemaVersion": 2, "manifests": [manifest]}).encode()
    if bad_hash:
        blobs["blobs/sha256/" + config["digest"].split(":")[1]] = b" " + blobs["blobs/sha256/" + config["digest"].split(":")[1]][1:]
    with tarfile.open(path, "w") as archive:
        for name, raw in {"index.json": index, **blobs}.items():
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))


class ArtifactTests(unittest.TestCase):
    def check(self, **kwargs):
        base = ROOT / ".m3-runs"
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as directory:
            assert Path(directory).resolve().is_relative_to(base.resolve())
            path = Path(directory) / "tiny.oci.tar"
            synthetic_archive(path, **kwargs)
            return inspect_oci(path, SOURCE)

    def test_static_nonroot_artifact_acceptance(self):
        self.assertEqual("10001:10001", self.check()["user"])

    def test_nontraversable_directories_rejected(self):
        with self.assertRaisesRegex(ValueError, "traverse"):
            self.check(directory_mode=0o444)

    def test_wrong_identity_and_writable_paths_rejected(self):
        with self.assertRaisesRegex(ValueError, "configuration"):
            self.check(user="0")
        with self.assertRaisesRegex(ValueError, "permission"):
            self.check(directory_mode=0o777)

    def test_blob_tampering_rejected(self):
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            self.check(bad_hash=True)


if __name__ == "__main__":
    unittest.main()
