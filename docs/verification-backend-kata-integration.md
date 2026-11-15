# Backend to Kata integration review

Updated: 2026-11-15 (Asia/Bangkok). **Application integration remains M4/M5 work.**
Runner release and trusted-fixture acceptance are tracked in
[RELEASE_0.1.1.md](../RELEASE_0.1.1.md) and [M3 acceptance](infrastructure/M3_ACCEPTANCE.md).

## Inspected sources and boundary

Runner and existing adapter source were inspected at clean `kata-infra` commit
`11d5465cb95d7ff78fd74f903813a1dba40f966e`. This finalization does not wire the
backend application. Backend findings refer to the previously inspected snapshot
[`49f94011b0f824d45dc1bf012473b3af978f3b77`](https://github.com/chinabunchorn/kataAI/commit/49f94011b0f824d45dc1bf012473b3af978f3b77),
including its [handoff](https://github.com/chinabunchorn/kataAI/blob/49f94011b0f824d45dc1bf012473b3af978f3b77/docs/infrastructure/BACKEND_INTEGRATION_HANDOFF.md).
That snapshot is historical; no newer backend or deployed application was certified here.

The laptop hosts FastAPI, application state and model serving. The existing
OpenStack node hosts Kubernetes/containerd/Kata; each execution Pod receives a
Kata guest. Per-request OpenStack server creation is outside this flow.
Model-generated Python stays disabled until M6/M8 acceptance.

## Existing implementation

[`KataExecutor`](../infra/executor/adapter.py) already implements `submit`, `status`,
`read_result`, `cancel`, and `cleanup`, plus `outcome` and `reconcile`. Claims that
the adapter or Kubernetes transport is missing are obsolete. It reuses shared
runner staging, fixed Job construction and collection. Candidate bytes are
staged and never executed locally.

[`KubectlAPI`](../infra/executor/transport.py) provides bounded raw API requests
through explicit kubeconfig/context with HTTPS and CA checks.
[`SQLiteRunStore`](../infra/executor/store.py) journals intent, manifests, hashes,
provider UIDs, outcomes, cancellation and cleanup under a cross-process lock.
The adapter verifies identities, refuses blind recreation after uncertain creates,
and deletes with UID preconditions. API absence alone does not complete guest
cleanup. See the [executor README](../infra/executor/README.md) for construction,
recovery semantics and callback contracts.

The journal does not replace PostgreSQL's authoritative request queue. The caller
must persist request/run IDs before submission, coordinate both stores after
restart, enforce claim fencing/admission, and schedule reconciliation. Physical
Kubernetes execution is not exactly once; the adapter rejects multiple observed
Pod attempts and retains one logical result.

## Remaining application gaps

The inspected backend's `phase6_processor.py` calls `run_fake_flow`, which constructs
`FakeExecutor`. Adding the adapter did not change that worker. M4/M5 must explicitly
select real mode and supply:

- An authorized ACTIVE/READY dataset reader returning a stable bounded CSV snapshot,
  plus a trusted-fixture execution policy until M6/M8 pass.
- Image provenance verification against the approved release and actual runtime
  `imageID`; a digest by itself does not approve execution.
- A trusted teardown observer retaining live Pod → sandbox → shim/QEMU correlation
  and confirming stopped guests. Missing evidence stays pending.
- Durable PostgreSQL request/run association, real outcomes/status serialization,
  cancellation coordination, restart/link recovery, cleanup retries and retention.
- An approved application identity/credential lifecycle with narrowly scoped API
  permissions, verified TLS and admission controls. M3's SSH operator harness is
  test transport. No application RBAC or credentials were provisioned here.

## Contract alignment before dispatch

Runner 0.1.1 retains protocol `kataai.runner.v1`, Python 3.12 stdlib only,
namespace `kata-lab` and RuntimeClass/handler `kata-qemu-runtime-rs`.

| Boundary | Inspected backend snapshot | Runner / existing adapter requirement |
|---|---|---|
| Program interface | Prompt promises pandas `df` and a `result` variable | Use `csv`/`json`, read `/inputs/data.csv`, write `/tmp/result.json`; no pandas or variable capture |
| CSV bytes | 10,000,000 intake cap | 524,288 execution cap; reject incompatible uploads before generation/dispatch, never truncate |
| Script bytes | 16,384 | Adapter keeps 16,384; runner staging permits 32,768 |
| Script time | Interface 1–300 s, fake handoff 60 s | Adapter requires exactly 30 s; separate 120 s Job deadline |
| Result bytes | 32,768 | 2,048 raw result; 3,072 termination envelope |
| Result shape | Any JSON root | Object/array; depth 16 from root container 1; 128 entries/collection, 256 total |
| Decoder intersection | Rejects NUL and oversized integers | Adapter applies backend decoder after runner validation; preserve the stricter intersection |
| Storage environment | POSIX descriptors, no-follow and ownership checks; Python >=3.12,<3.13 | Choose an approved Linux/WSL application environment or verify separate Windows storage; never bypass checks |

The runner requires writable guest tmpfs with positive capacity/available space.
`emptyDir.sizeLimit: 16Mi` remains configured but is not a verified guest quota.
The custom runtime patch was abandoned. Historical quota failure and dependent
unrun evidence remain in the [investigation](infrastructure/M3_SCRATCH_INVESTIGATION.md).
A quota correction and legacy quota reruns are excluded from current M3 gates.

## Verification and next milestone acceptance

Current host verification passed **48 runner tests and 39 executor tests**. Executor
tests use pinned backend dataclasses/enums/decoder and fake API/processes, covering
uncertain/late creates, restart, identity mismatch, cancellation, bounded TLS
transport and interrupted cleanup. They do not certify live adapter operation,
backend pytest/PostgreSQL, model behavior or application credentials. M3 live
fixture results certify the runner/harness path only.

M4/M5 should wire the existing adapter, align contracts and verify trusted success,
script/result errors, timeout, missing runtime/image/permissions, duplicate or
mismatched identities, cancellation races, partial create/cleanup and worker/link
restart through the actual application path. Retain request/run IDs, input hashes,
immutable image/protocol, exact provider UIDs, outcome, API cleanup and independent
guest teardown. Persist results before deleting their termination-message source.
Unknown remote state must consume admission capacity until reconciled. Never
substitute fake results, a fresh UUID, local execution or runc for failed dispatch.

Same-UID report/process tampering, diagnostic bypass, broader network/credential
probes, effective resource abuse controls and admission remain M6/M8 gates.
M3 completion does not authorize model-generated execution.
