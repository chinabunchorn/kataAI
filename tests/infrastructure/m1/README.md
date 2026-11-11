# M1 trusted infrastructure feasibility test

Status: **Verified for the trusted M1 runs on 2026-11-11**. Captured identities and
observations are recorded in infrastructure documentation section 16.5. These
files alone are instructions, not proof that a future execution succeeds.

Read the authoritative M1 tasks/acceptance criteria in
`Sandboxed_AI_Inference_Master_Roadmap_v0.3.md` and the audit/run instructions in
  `docs/infrastructure/INFRASTRUCTURE.md`, sections 16.1–16.5.

- `inspect.sh`: read-only host, runtime, Kubernetes, Calico and resource inventory.
  Run on katavm using `bash inspect.sh`. Commands requiring host inspection use
  `sudo -n` and fail rather than prompting for a password. A missing command or
  denied inspection must be recorded; the script deliberately continues inventory.
- `data.csv`: exact canonical roadmap fixture.
- `trusted_csv.py`: trusted fixture, **execute only through the Kata Job**.
  Reports JSON plus UID/kernel diagnostics, verifies UID 10001, token absence and
  denied input writes, then holds for 60 seconds to permit live correlation.
- `job.template.yaml`: replace `RUN_NAME` and `PYTHON_IMAGE_DIGEST` only after
  inspecting the cluster and selecting an available, digest-pinned Python image.
  Create the corresponding run-scoped ConfigMap first.

Do not apply or weaken network/security policy as part of this test. Inspect all
applicable policies; a default-deny object does not override other allow policies.
Do not grant an application arbitrary Job creation permissions. Temporary Windows
test RBAC requires review and approval before application.

For each run record: timestamps, image digest, effective policy, exact Job UID,
Pod UID/owner reference, RuntimeClass, CRI sandbox ID/Pod metadata, linked shim and
QEMU PID/start time/command, guest kernel and UID, parsed canonical result,
terminated exit code and completion condition. Capture VM evidence while running;
the guest may terminate at completion before explicit Job deletion.

Cleanup inventory is limited to this run's Job, its dependent Pods, input ConfigMap
and explicitly staged files. Inspect exact identities before deletion. Record
cleanup latency, API absence, sandbox state and exact VM termination. Do not delete
historical resources or manually remove containerd/kubelet state. Capture residue
and failures honestly. Do not commit tokens, credentials or raw kubeconfigs.

`network-probes.py` performs the recorded bounded network probes inside Kata.
Recheck its endpoint addresses before reuse. It records observations; it does not
assert that all possible destinations or protocols are blocked.

`windows-test-rbac.yaml` is a reviewable temporary operator identity proposal.
Its actual application and deletion were explicitly approved for this run.
`windows-test.ps1 -Approved` executes the fixed Windows workflow using that
identity, holding a ten-minute token in memory and using verified HTTPS through
the SSH tunnel. Create the identity only after approval, and remove its binding,
Role and ServiceAccount after the script, including if the script fails. The
script removes only its own Job/ConfigMap and any tunnel process it starts.
Before future reruns, update run/identity names consistently, confirm no existing
objects use those names, and reapprove the temporary permissions.

Verification: PowerShell parser and diff checks passed; both trusted fixture
executions returned exit code zero inside Kata; the clean network-probe run
returned exit code zero inside Kata; the Windows script passed. Python was not
executed on Windows or the Kubernetes host. Initial CRLF transmission errors are
documented separately; transmit shell scripts without CR characters, for example
by base64-encoding normalized UTF-8 text and decoding into `bash` remotely.
