# Fixed Python runner 0.1.1 release preparation

Date: 2026-11-15 (Asia/Bangkok). **HOLD — not released; candidate live acceptance pending.**

KataAI uses the existing unmodified Kata Containers runtime. Exact 16 MiB guest
scratch enforcement is no longer a release requirement. The abandoned custom
Rust patch, installation/correction proposals and patch review have been removed.
Original check logs/provenance were archived; the investigation, fixture bytes
and all original test evidence remain unchanged. No commit, push or tag was made.

## Artifact and source identity

| Field | Value |
|---|---|
| Runner version | `0.1.1` in contract, OCI label, builder tag validation, digest-reference construction and release metadata |
| Wire protocol | `kataai.runner.v1` |
| Source base commit | `84eb0fd07c6e7bcd9369caae153b69cebe312d21` |
| Candidate commit | None; uncommitted working tree, including preexisting preparation changes |
| Candidate image digest / archive SHA-256 | Unavailable; no 0.1.1 candidate built |
| Platform / base interpreter metadata | Linux/amd64; Python 3.12.16, Debian trixie; inherited pinned-base metadata, not a new image observation |
| Immutable base | `docker.io/library/python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b` |

Historical 0.1.0 image:
`docker.io/kataai/runner@sha256:3fe4d6049f25c44d3b126f6b9de7462dfb019d3164bada7e775921a1b13abba8`.
Its evidence does not certify 0.1.1. Historical records retain their original
versions, hashes and outcomes. The earlier preparation evidence and investigation
may reference removed proposals; those references describe abandoned work.

The builder records all runner source/context/build/inspection hashes before
building, HEAD and dirty status, verifies unchanged source afterward, and requires
BuildKit's manifest digest to match static OCI inspection. Inspection verifies
version, non-root layout and exact packaged source, including `scratch.py`.
A successful build still records `live_kata_acceptance_verified=false`.
After the user's commit, rebuild to establish committed provenance; never relabel
a dirty artifact as built from that later commit.

## Revised contract and acceptance

The [amended M3 acceptance policy](docs/infrastructure/M3_ACCEPTANCE.md) and
[design](docs/milestone-3-design.md) define the current contract.

| Boundary | Requirement |
|---|---|
| Scratch | Distinct writable guest tmpfs at `/tmp`, positive capacity and available space; bounded valid mountinfo and writable flags; actual guest writes observed by the existing trusted security fixture |
| Scratch configuration | Keep memory emptyDir `sizeLimit: 16Mi`; this is not a verified guest quota. Capacity may be smaller or larger than 16 MiB |
| Input | Script 32 KiB; CSV 512 KiB; serialized immutable ConfigMap 768 KiB; strict nonempty UTF-8, no NUL; exactly two projected keys |
| Result | `/tmp/result.json`, object/array, 2048 raw bytes; depth 16; 128 entries/collection, 256 total; strict JSON/Unicode/numeric validation |
| Report | `/tmp/runner-termination.json`, 3072 bytes; Kubernetes File termination policy; strict identity, exit and result validation; no log fallback |
| Diagnostics | 8192 retained bytes per stdout/stderr; terminate above 16384 combined observed bytes |
| Time / retry | 30 s measured child budget; 120 s Job deadline; 5 s termination grace; one completion, no retries, restart Never |
| Resources | Requests 100m CPU / 128Mi memory / 16Mi ephemeral storage; limits 1 CPU / 256Mi memory / 64Mi ephemeral storage |
| Placement | Namespace `kata-lab`; RuntimeClass and handler `kata-qemu-runtime-rs`; existing RuntimeClass overhead additional |
| Security | UID/GID/fsGroup 10001; root and inputs read-only; no escalation; ALL capabilities dropped; RuntimeDefault seccomp; no token automount or service links; existing network denial |

Exit codes remain `OK=0`, `SCRIPT_FAILED=10`, result errors 11–16,
`RUN_TIMEOUT=17`, `DIAGNOSTIC_LIMIT=18`, `INPUT_INVALID=19`, `RUNNER_INTERNAL=20`.
Scratch can consume memory beyond 16 MiB. No report is guaranteed after full
scratch or abrupt death; collection fails closed. No new effective memory bound
or untrusted-code isolation guarantee is claimed.

The original `scratch`, `scratch-failure` and proposed `scratch-multifile` probes
are preserved with their original expectations in `LEGACY_SCRATCH_CASES` and
fixture files, excluded from executable release choices. Historical acceptance
remains 30 passing checks, one failed quota check and one dependent unrun case;
the guest accepted 20 MiB on a 100,691,968-byte tmpfs. Changing release policy
does not turn that failed test into a pass.

## Current validation evidence

[Cleanup evidence](tests/infrastructure/m3/evidence/2026-11-15/scratch-policy-cleanup/README.md)
is separate from the untouched earlier preparation and live test records.

- **48 Runner host tests passed**, including capacity variation, unsuitable scratch
  rejection before launch, legacy quota exclusion, version/tag consistency and
  static OCI source/version checks. Tests execute trusted host code and mocked
  launches; no candidate fixture or model-generated Python executed.
- **39 executor host tests passed** with fake transport/processes.
- M3 harness `--help`, PowerShell build-script syntax and `git diff --check` passed.
- Docker client is available, but `docker version` failed because the existing
  Linux engine pipe is absent. No engine was started, builder installed or
  candidate built/distributed. Candidate live tests were not run because no
  inspected 0.1.1 image/digest is available.
- No installed Kata runtime, Kubernetes configuration, RBAC or network policy
  was modified. No cluster workload was submitted by this cleanup.

## Remaining release gates

On an available approved builder, build and inspect 0.1.1 without candidate
execution, then record its actual digest, archive hash and source provenance.
Distribute/import that exact artifact through the approved path. With existing
authorized operator access, run the full **30-case active trusted catalog** on
the unmodified Kata runtime: security writes, scratch-layout, results/negative
cases, timeouts, diagnostics, network and missing RuntimeClass. Recheck network
target identity/health, capture runtime/image/Pod identity, exact-UID API cleanup
and independently observed live guest correlation/teardown. Retain failures and
unrun cases. Do not execute model-generated Python or alter infrastructure.

Review the actual evidence before acceptance. Same-UID report tampering, selected
network/credential probe scope and partly host-only OOM/infrastructure mappings
remain limitations; later M6/M8 gates still apply before untrusted execution.
**Runner 0.1.1 remains unreleased. Committing and pushing are left to the user.**
