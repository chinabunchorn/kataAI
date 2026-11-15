"""Server-owned Job construction. Caller cannot select runtime or privileges."""

import re

from .contract import COMMAND, CONTAINER, GID, JOB_SECONDS, NAMESPACE, REPORT_PATH, RUN_LABEL, RUNTIME_CLASS, UID, ContractError
from .staging import check_run_id


def check_image(image: str) -> None:
    if not isinstance(image, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9./:_-]*@sha256:[0-9a-f]{64}", image):
        raise ContractError("INPUT_INVALID", "immutable image reference required")


def make_job(run_id: str, image: str) -> dict:
    check_run_id(run_id)
    check_image(image)
    labels = {RUN_LABEL: run_id}
    return {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": run_id, "namespace": NAMESPACE, "labels": labels.copy()},
        "spec": {
            "completions": 1, "parallelism": 1, "backoffLimit": 0,
            "activeDeadlineSeconds": JOB_SECONDS,
            "template": {"metadata": {"labels": labels.copy()}, "spec": {
                "runtimeClassName": RUNTIME_CLASS, "restartPolicy": "Never",
                "automountServiceAccountToken": False, "enableServiceLinks": False,
                "terminationGracePeriodSeconds": 5,
                "securityContext": {
                    "runAsNonRoot": True, "runAsUser": UID, "runAsGroup": GID,
                    "fsGroup": GID, "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [{
                    "name": CONTAINER, "image": image, "imagePullPolicy": "IfNotPresent",
                    "command": COMMAND.copy(),
                    "env": [
                        {"name": "KATAAI_RUN_ID", "value": run_id},
                        {"name": "KATAAI_POD_UID", "valueFrom": {"fieldRef": {"fieldPath": "metadata.uid"}}},
                    ],
                    "terminationMessagePath": REPORT_PATH, "terminationMessagePolicy": "File",
                    "securityContext": {
                        "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "resources": {
                        "requests": {"cpu": "100m", "memory": "128Mi", "ephemeral-storage": "16Mi"},
                        "limits": {"cpu": "1", "memory": "256Mi", "ephemeral-storage": "64Mi"},
                    },
                    "volumeMounts": [
                        {"name": "inputs", "mountPath": "/inputs", "readOnly": True},
                        {"name": "scratch", "mountPath": "/tmp"},
                    ],
                }],
                "volumes": [
                    {"name": "inputs", "configMap": {
                        "name": f"{run_id}-inputs", "defaultMode": 0o444,
                        "items": [{"key": key, "path": key} for key in ("script.py", "data.csv")],
                    }},
                    {"name": "scratch", "emptyDir": {"medium": "Memory", "sizeLimit": "16Mi"}},
                ],
            }},
        },
    }
