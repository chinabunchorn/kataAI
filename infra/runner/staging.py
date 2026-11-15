"""Pre-create checks and run-scoped input staging, independent of transport."""

import hashlib
import re

from .contract import CONFIGMAP_BYTES, CSV_BYTES, NAMESPACE, RUN_LABEL, SCRIPT_BYTES, ContractError
from .validation import encode_json


def check_run_id(run_id: str) -> None:
    # Job name suffixes and ConfigMap suffix fit Kubernetes DNS-label limits.
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?", run_id):
        raise ContractError("INPUT_INVALID", "run ID must be a DNS label of 1..40 characters")


def input_text(raw: bytes, cap: int) -> str:
    if not isinstance(raw, bytes) or not raw or len(raw) > cap or b"\0" in raw:
        raise ContractError("INPUT_INVALID", "empty, NUL or oversized input")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ContractError("INPUT_INVALID", "input must be UTF-8") from None
    if not text.strip():
        raise ContractError("INPUT_INVALID", "blank input")
    return text


def stage_inputs(run_id: str, script: bytes, csv: bytes) -> dict:
    check_run_id(run_id)
    script_text = input_text(script, SCRIPT_BYTES)
    csv_text = input_text(csv, CSV_BYTES)
    manifest = {
        "apiVersion": "v1", "kind": "ConfigMap", "immutable": True,
        "metadata": {
            "name": f"{run_id}-inputs", "namespace": NAMESPACE,
            "labels": {RUN_LABEL: run_id},
            "annotations": {
                "kataai/script-sha256": hashlib.sha256(script).hexdigest(),
                "kataai/csv-sha256": hashlib.sha256(csv).hexdigest(),
            },
        },
        "data": {"script.py": script_text, "data.csv": csv_text},
    }
    if len(encode_json(manifest)) > CONFIGMAP_BYTES:
        raise ContractError("INPUT_INVALID", "serialized ConfigMap cap")
    return manifest
