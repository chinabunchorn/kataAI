"""Fake-only orchestration: generated Python is inert and results are presets."""
from copy import deepcopy
from uuid import UUID, uuid4

from app.executor_contract import ExecutorRequest
from app.fakes import FakeExecutor
from app.executor_results import decode_execution_result
from app.model_adapter import MAX_RESULT_BYTES, MAX_SUMMARY_BYTES, _json_value, _text
from app.proposals import validate_proposals


def run_fake_flow(model, fake_result, question, columns, *, request_id=None, dataset_id=None):
    if request_id is not None or dataset_id is not None:
        if not isinstance(request_id, UUID) or not isinstance(dataset_id, UUID):
            raise ValueError('INVALID_EXECUTOR_REQUEST')
    proposal = validate_proposals(model.generate(question, columns))
    if isinstance(request_id, UUID) and isinstance(dataset_id, UUID):
        # This run ID exists only for the fake invocation. Real external runs
        # must first persist their identity and reconcile uncertain submissions.
        handoff = ExecutorRequest(request_id, uuid4(), dataset_id, proposal, 60)
        proposal = handoff.proposal
    # Validate before FakeExecutor's deepcopy, which must never invoke methods
    # on arbitrary result objects; validate again at the executor boundary.
    _json_value(fake_result, MAX_RESULT_BYTES)
    result = FakeExecutor(fake_result).execute(proposal)
    # Fake values also pass the provisional bounded wire-result decoder; this
    # does not establish a provider origin or turn a preset into computation.
    result = decode_execution_result(_json_value(result, MAX_RESULT_BYTES))
    summary = None
    warning = 'SUMMARY_UNAVAILABLE'
    try:
        _, text, summary_warning = model.summarize(question, deepcopy(result))
        if summary_warning is None:
            summary = _text(text, MAX_SUMMARY_BYTES)
            warning = None
    except Exception:
        pass
    return {'fake': True, 'code': proposal.code, 'result': result,
            'summary': summary, 'warning': warning, 'metrics': None}
