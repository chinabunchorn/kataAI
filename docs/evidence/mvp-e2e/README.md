# Supervised native macOS MVP evidence — 2026-11-15

Subsequent React integration and actual browser acceptance are recorded in
[FRONTEND.md](FRONTEND.md), including both the retained model-code failure and
the successful browser-to-Kata result. The original backend evidence below is historical and unchanged.

**Verified:** real multipart uploads → PostgreSQL requests → actual local Qwen
`run_python` calls → real Kubernetes Jobs using `kata-qemu-runtime-rs` → pinned
Runner 0.1.1 JSON collection → Qwen sentence summaries → persisted HTTP responses.
Both negative controls produced text-only clarification, no run UUID and no Job.
All seven supervised real runs' Jobs/Pods/ConfigMaps were independently checked
absent through the dedicated application's API access after cleanup.

**Not verified:** independent node/sandbox/VM teardown. No node observer is
configured. Every executed run accurately retains `cleanup=pending` and
`guest_teardown_verified=false`, even though API resources are absent. This is
research MVP evidence, not M4/M5/M6/M8 production/isolation approval or a general
model accuracy benchmark. The approved runtime, runner release and historical M3
evidence were not modified.

## Final cases

| Case | Request UUID | Real run UUID | Actual outcome |
| --- | --- | --- | --- |
| Revenue | `266a6d1f-62c3-4e8b-a867-56f90b28f6e3` | `c597574a-7b3c-4d91-a5e3-74827f9f93a3` | `{"answer":770.0}`; “The total revenue is 770.0 THB.” |
| East units | `1a3b5b53-ceb4-4d53-b67e-98e75c93dbbd` | `6f3a2941-e747-406e-8432-4cbe1053187a` | `{"answer":6}`; “จำนวนสินค้าที่ขายในภูมิภาค East รวมทั้งหมดเป็น 6 ชิ้น” |
| Missing profit | `c35bd54f-92ef-4536-94f8-fa54138038f9` | none | `needs_clarification`: cost information is missing |
| Ambiguous total | `338c057b-dc6c-4ab3-b5c4-54d2f7eb243d` | none | `needs_clarification`: asks which measure to total |

Final revenue and East CLI upload-to-answer latencies were 42.079s and 46.122s.
Negative-control latencies were 49.071s and 40.944s. These are single supervised
samples including upload, queue polling and model/remote work; cleanup follows
terminal persistence and was checked separately. Values were not replaced or
repaired. Actual generated arithmetic/filtering and exact result bytes were
reviewed, and the independent fixture oracle is 770 THB / 6 units.

## Artifacts and correlation

- `revenue-http.txt`, `east-http.txt`, `profit-http.txt`, `ambiguous-http.txt`:
  actual CLI output from the real HTTP multipart/upload/request/poll workflow.
- `verification.json`: fresh independent GET responses checked against the
  PostgreSQL records and exact real run IDs, provider UIDs and model messages;
  explicit API absence checks for all seven execution identities.
- `postgres-requests.json`: all nine retained demo requests, including the
  trusted smoke, earlier summary trials and both negative controls. No fake run.
- `executor-journal.json`: all seven real executor records, exact staged
  synthetic CSV/source manifests, hashes, provider Job/Pod/container identities,
  actual runner outcomes/result bytes and truthful cleanup evidence.
- `ka-*-provider.json`: actual live provider Job/Pod snapshots captured while
  the supervised Jobs ran. The final two correlate with the run UUIDs above;
  earlier snapshots remain as historical supervised trial evidence. Snapshot
  phases may be Running; terminal exit/status/result evidence is in the journal.
- `actual-model-messages.json`: actual llama.cpp parsed `run_python` proposals,
  summaries and clarifications correlated by exact generated source or exact
  response text with PostgreSQL. Internal reasoning is omitted. These are
  actual model messages, not canned tool envelopes.
- `environment.json`, `metal-timings.txt`: macOS ARM64, Python 3.12.16, llama.cpp
  build 12359 (`b1b770d90`), model SHA-256, actual MTL0 Apple M2 selection,
  33/33 layers offloaded, one 4096-token slot, native POSIX support and model
  token timings. Observed generation throughput was approximately 13–15 tokens/s.
- `rbac.json`, `access-checks.json`, `token-expiry.json`: nonsecret provisioned
  rules, all 26 permission checks and actual token expiration. No token,
  private key, client certificate credential or kubeconfig is included.
- `backend-tests.txt`: 717 backend tests passed, including real PostgreSQL
  persistence/concurrency in generated schemas in `kataai_mvp_test`.
  Runner tests: 48 passed. Executor tests: 39 passed. Ruff, zsh syntax and
  `git diff --check` also passed. Infra Python source/tests and historical M3 evidence
  match `5c5a45a` unchanged.

## Hand-written smoke before generated execution

Request `eb8f2f02-a88a-44be-8ca3-8dbfce9176b4`, run
`7dc86571-1351-4b27-9e4e-19f5d5dcbbea` used the separate trusted fixture probe,
not Qwen or a fake executor. The actual Runner result was four rows and columns
`order_id`, `region`, `quantity`, `unit_price_thb`. It passed before enabling
model-generated dispatch. Its summary is intentionally unavailable; the smoke
checks the adapter path, not a natural-language model answer.

## Failures retained, not counted as acceptance

Early generation-only prompt probes were inspected as inert text and never
executed locally. The first probe guessed revenue for an unspecified “total”.
`prompt-trial-2.json` preserves a proposal that multiplied CSV strings before
numeric conversion. `prompt-trial-3.json` preserves a missing-profit tool call
that only inspected data instead of clarifying. These are failures, not passes.
The general runner/typing/schema/ambiguity instructions were refined manually;
there is no per-request repair agent, automatic retry or predefined computation.

The first two real generated runs computed correct results but exhausted the
1024-token summary budget on internal reasoning. Their original HTTP outcomes
remain in `*-summary-unavailable-http.txt`, with actual results retained and
`SUMMARY_UNAVAILABLE`, as required. The loaded template was inspected and its
supported `enable_thinking=false` parameter applied to summaries only. A follow-up
returned correct but terse numeric text (`*-numeric-summary-http.txt`); the final
summary prompt requests a concise sentence. Each supervised verification used
fresh explicit requests; old outcomes and run identities were preserved.

## Process and credential state

The isolated demo database is `kataai_mvp_demo`; the existing `kataai_dev` schema
was left unchanged. CSVs/journal are under ignored `.mvp-demo/` with private
permissions. The existing API on port 8000 was not stopped; the new strict-loopback
demo API uses port 8001. The model is on 127.0.0.1:8080, the worker is one local
process, and the existing SSH tunnel is on 127.0.0.1:16443. No backend Linux VM,
container, new image or broker was introduced.

Kubeconfig: `$HOME/.kube/kataai-mvp.yaml`, context `kataai-mvp`, mode 0600.
Dedicated identity permissions and denials were checked from the Mac, and
KubectlAPI/TLS preflight and actual dispatch succeeded. The actual token expires
2026-11-16 02:00:46 Asia/Bangkok (2026-11-15 19:00:46 UTC); see
[the runbook](../../MVP_E2E.md#dedicated-mac-identity-and-manual-token-renewal)
for manual renewal without credential output. No existing cluster identity or
infrastructure object was modified/deleted. Cleanup targeted only the executor's
own correlated run resources.

Source heads were verified against origin: backend
`49f94011b0f824d45dc1bf012473b3af978f3b77`, kata-infra
`5c5a45aef421f37539109a43ac821ccfc91e54f6`.
`integration/mvp-e2e` starts from backend and contains the resolved kata-infra
integration. It was initially prepared without commits, then committed and pushed
on the operator’s explicit follow-up request. No release or main-branch merge was made.
