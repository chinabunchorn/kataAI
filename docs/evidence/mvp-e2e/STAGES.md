# Persisted stage latency verification — 2026-11-15

New request `628de9e2-8cfc-4c60-9045-ed86b4a5ac5f`, run
`6529365d-5691-4df1-a784-c782ce3ff38c`, passed the real browser → PostgreSQL → Qwen
→ Kata → browser test and returned 770 THB. No API/model/executor mocks were used.
The existing idle demo worker and loopback API were restarted after applying the
additive `0007_execution_stages` migration to the demo database. No runtime, image,
identity, permissions or credentials were changed.

| Observed stage | Recorded latency |
| --- | ---: |
| Queue wait | 615 ms |
| Preparing dataset | 3 ms |
| LLM processing | 23,716 ms |
| Code validation | 5 ms |
| Dispatch / starting execution | 1,596 ms |
| Kata container/VM startup and wait | 9,041 ms |
| Observed running Kata container | 3,442 ms |
| Result collection | 3 ms |
| LLM summarization | 2,581 ms |

These are backend/provider observation spans, not isolated Python CPU time or
exact VM boot measurements. Short Running states may be missed between polls;
the UI omits unobserved stages. Unknown/failure ends observation tracking, not a
claim of execution termination. Existing independent cleanup semantics remain.

[Selected live evidence](frontend-stage-verification.json) contains the GET
response and persisted timeline, matched independently against PostgreSQL, plus
correlated executor provider IDs/image and cleanup state. Named Job/ConfigMap
reads and scoped Pod listing confirmed API resources absent after this run.
Guest teardown remains unverified; journal cleanup remains pending.
[The screenshot](frontend-stage-timings.png) shows the actual restored timeline.

Checks: 727 backend tests with disposable PostgreSQL; 44 frontend tests; TypeScript/
Vite build; backend Ruff; Prettier; four deterministic desktop/mobile browser tests;
one real browser/Qwen/Kata timing test (41.7 s). Recovery, claim fencing, terminal
timing closure, skipped unobserved stages and historical records are covered.
The API extension is additive on GET detail/history; existing status values and
POST/cancellation contracts are preserved. Historical terminal records receive no
invented timing. The runbook and frontend README document upgrading and timing limits.
