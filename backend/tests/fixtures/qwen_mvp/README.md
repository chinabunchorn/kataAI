# Synthetic Qwen MVP proposal fixture

Status: **provisional evaluation contract, not team-approved**. Everything here is synthetic. The offline harness runs fixed, trusted Python test code only; it never executes, imports, evaluates, compiles, or shells out to model-generated code. A valid tool envelope does not imply correct, safe, or runnable code.

## Dataset and independent expectations

`sales.csv` has four order rows. Revenue is 2×100 + 1×150 + 3×40 + 4×75 = 770 THB; East quantity is 2 + 1 + 3 = 6 units. The test reads the CSV with the standard library and recomputes both using fixed code independently of the JSON answers and any proposal. `cases.json` also has missing-profit and unspecified-total cases: both require a no-tool clarification, not an invented value or tool call.

## Offline contract

From `backend/`, run `.venv/bin/python -m pytest tests/test_qwen_mvp_fixture.py -q -p no:cacheprovider` (or use a Python environment with pytest and this backend on the import path). The test file contains the small offline harness: `classify_response` validates exactly one proposal through the existing `app.proposals.validate_proposals` boundary; `matches_expected_kind` compares its category against a fixture. Canned responses verify both positive and negative outcomes, including a proposed filesystem write which remains inert. These tests do not call Qwen or use a database.

The provisional *normalized* response shape is `{"finish_reason":"tool_calls","tool_calls":[{"name":"run_python","arguments":{"code":"..."}}],"content":null}` for proposals; a candidate no-tool clarification is `{"finish_reason":"stop","tool_calls":[],"content":"..."}`. A length finish is `truncated`; invalid envelopes are `malformed`. A nonempty no-tool message is only a **candidate** clarification: human review must distinguish real clarifications from refusals, irrelevant text, or unsupported answers. `matches_expected_kind` is a structural check, not a semantic grade. Record transport errors, timeouts, provider refusals, and parser failures separately before normalization; never relabel them as clarifications. No free-text candidate automatically passes semantic review.

The current MVP prompt targets Runner 0.1.1: Python 3.12 standard library only,
read `/inputs/data.csv` with `utf-8-sig`, and explicitly write a JSON object or
array to `/tmp/result.json` within 2048 bytes and 30 seconds. Calculation questions
prefer `{"answer": <computed value>}`; other object/array roots remain valid.
There is no pandas DataFrame or result-variable capture. See
[the native macOS runbook](../../../../docs/MVP_E2E.md) for explicit private demo
authorization and actual verification status. The fake worker still returns presets;
only a collected remote result can establish computation.

## Real-model probe strategy and observations

A local smoke probe was run with thinking enabled on 2026-11-14 (local time); see the backend
README for the observed failures. It used the production generation prompt,
not the hypothetical `result` convention above, so it cannot establish runner
contract compatibility. The proposed code was inspected as inert text only.
The raw synthetic results were saved under `/tmp` during the session, not as
persistent benchmark artifacts. The following remains the reproducibility plan:

With separate permission to contact an approved model endpoint, send only each synthetic question, the exact column names and the provisional output/tool convention. Keep input format identical across cases and repetitions. Capture raw responses and finish reasons before a documented provider-specific normalization; do not edit application code, start a worker, call an executor, or connect a database. Record model revision/quantization, server and parser versions, template, sampling settings, seed if supported, timeout, timestamp, endpoint type, counts, and latency boundaries. Respect approved data-sharing and logging controls; keep any captured proposal inert. Include a per-case table of structural category and manual semantic inspection: correct dataset/columns and aggregation/filter for positives, and genuine no-tool clarification for negatives. Report errors, refusals, timeouts and truncation separately; missing samples are not passes. Manual inspection cannot establish runtime correctness or isolation. Four cases are a smoke fixture, not a reliability benchmark.
