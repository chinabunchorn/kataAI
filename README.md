# kataAI

Kata-based Python execution for a split local application / OpenStack lab.

- [Master roadmap](Sandboxed_AI_Inference_Master_Roadmap_v0.3.md)
- [Verified M1 infrastructure records](docs/infrastructure/INFRASTRUCTURE.md)
- [Approved M3 runner design](docs/milestone-3-design.md)
- [Fixed runner and M4 interface](infra/runner/README.md)
- [M3 tests and lab runbook](tests/infrastructure/m3/README.md)
- [M3 acceptance status and blockers](docs/infrastructure/M3_ACCEPTANCE.md)
- [Backend Kubernetes executor adapter](infra/executor/README.md)

Host-only runner tests (no candidate script execution or cluster access):

```powershell
python -B -m unittest discover -s tests/unit/runner -v
python -B -m unittest discover -s tests/unit/executor -v
```

Only team-controlled trusted fixtures may execute in Kata until M6/M8 pass.
