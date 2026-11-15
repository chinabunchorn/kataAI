"""Inspect an OCI archive without extracting or executing anything in it."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile

if __package__:
    from .contract import VERSION
else:
    from contract import VERSION


def _json(archive, name):
    member = archive.getmember(name)
    if not member.isfile() or member.size > 256 * 1024:
        raise ValueError("unexpected OCI metadata size/type")
    return json.load(archive.extractfile(member))


def inspect_oci(path: Path, source: Path) -> dict:
    expected = {"opt/kataai/runnerlib/" + name: name for name in (
        "__init__.py", "contract.py", "validation.py", "staging.py", "report.py", "scratch.py", "supervisor.py")}
    expected["opt/kataai/runner.py"] = "entrypoint.py"
    found = {}
    with tarfile.open(path) as archive:
        index = _json(archive, "index.json")
        if len(index["manifests"]) != 1:
            raise ValueError("expected single-platform manifest")
        digest = index["manifests"][0]["digest"]
        manifest = _json(archive, "blobs/sha256/" + digest.split(":")[1])
        config = _json(archive, "blobs/sha256/" + manifest["config"]["digest"].split(":")[1])
        # Verify the referenced content, including the actual manifest digest.
        for descriptor in [index["manifests"][0], manifest["config"], *manifest["layers"]]:
            algorithm, value = descriptor["digest"].split(":")
            if algorithm != "sha256":
                raise ValueError("unexpected digest algorithm")
            member = archive.getmember("blobs/sha256/" + value)
            if not member.isfile() or member.size != descriptor["size"]:
                raise ValueError("OCI blob size/type mismatch")
            hasher = hashlib.sha256()
            with archive.extractfile(member) as stream:
                while chunk := stream.read(65536):
                    hasher.update(chunk)
            if hasher.hexdigest() != value:
                raise ValueError("OCI blob digest mismatch")
        cfg = config["config"]
        if (config["os"] != "linux" or config["architecture"] != "amd64"
                or cfg["User"] != "10001:10001"
                or cfg["Entrypoint"] != ["python3", "-I", "-B", "/opt/kataai/runner.py"]
                or cfg["WorkingDir"] != "/tmp"
                or cfg.get("Labels", {}).get("org.opencontainers.image.version") != VERSION
                or "PYTHON_VERSION=3.12.16" not in cfg["Env"]):
            raise ValueError("fixed image configuration mismatch")
        for descriptor in manifest["layers"]:
            with tarfile.open(fileobj=archive.extractfile("blobs/sha256/" + descriptor["digest"].split(":")[1]), mode="r|*") as layer:
                for member in layer:
                    name = member.name.removeprefix("./").rstrip("/")
                    if name == "opt" or name.startswith("opt/kataai"):
                        if member.uid != 0 or member.gid != 0 or member.mode & 0o022:
                            raise ValueError("trusted path ownership/write permission mismatch")
                        if member.isdir():
                            if member.mode & 0o005 != 0o005:
                                raise ValueError("non-root cannot traverse trusted directory")
                        elif name in expected and member.isfile():
                            if member.mode & 0o004 != 0o004 or member.size > 64 * 1024:
                                raise ValueError("trusted file unreadable/oversized")
                            raw = layer.extractfile(member).read(64 * 1024 + 1)
                            actual = hashlib.sha256(raw).hexdigest()
                            wanted = hashlib.sha256((source / expected[name]).read_bytes()).hexdigest()
                            if actual != wanted:
                                raise ValueError("packaged source mismatch")
                            found[name] = actual
                        else:
                            raise ValueError("unexpected trusted path type/content")
        if set(found) != set(expected):
            raise ValueError("missing trusted source in image")
    return {"runner_version": VERSION, "manifest_digest": digest, "platform": "linux/amd64", "user": "10001:10001",
            "python": "3.12.16", "source_sha256": found, "candidate_execution_performed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_oci(args.archive, Path(__file__).parent), indent=2))
