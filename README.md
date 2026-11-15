# kataAI

Kata-based Python execution for a split local application / OpenStack lab.

- [Native macOS MVP setup, execution and verification](docs/MVP_E2E.md)
- [Backend API and historical milestones](backend/README.md)
- [Master roadmap](Sandboxed_AI_Inference_Master_Roadmap_v0.3.md)
- [Verified M1 infrastructure records](docs/infrastructure/INFRASTRUCTURE.md)
- [Approved M3 runner design](docs/milestone-3-design.md)
- [Fixed runner and M4 interface](infra/runner/README.md)
- [M3 tests and lab runbook](tests/infrastructure/m3/README.md)
- [M3 acceptance status and blockers](docs/infrastructure/M3_ACCEPTANCE.md)
- [Runner 0.1.1 verified artifact and release review](RELEASE_0.1.1.md)
- [Backend Kubernetes executor adapter](infra/executor/README.md)

Host-only runner tests (no candidate script execution or cluster access):

```zsh
python -B -m unittest discover -s tests/unit/runner -v
python -B -m unittest discover -s tests/unit/executor -v
```

Default execution remains disabled. The explicitly opted-in private research MVP
is described in the runbook; it does not constitute M4/M5/M6/M8 acceptance.

The integrated React UI is served by FastAPI at its configured loopback origin.
Build it with `cd frontend && npm ci && npm run build`, then launch the API,
model and approved worker following the [full runbook](docs/MVP_E2E.md).
See [frontend operation and browser tests](frontend/README.md) and
[browser integration evidence](docs/evidence/mvp-e2e/FRONTEND.md).
