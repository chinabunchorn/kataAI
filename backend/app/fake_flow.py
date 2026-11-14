"""Fake-only orchestration: generated Python is inert and results are presets."""
from copy import deepcopy

from app.fakes import FakeExecutor
from app.model_adapter import MAX_RESULT_BYTES, MAX_SUMMARY_BYTES, _json_value, _text
from app.proposals import validate_proposals


def run_fake_flow(model, fake_result, question, columns):
    proposal = validate_proposals(model.generate(question, columns))
    # Validate before FakeExecutor's deepcopy, which must never invoke methods
    # on arbitrary result objects; validate again at the executor boundary.
    _json_value(fake_result, MAX_RESULT_BYTES)
    result = FakeExecutor(fake_result).execute(proposal)
    _json_value(result, MAX_RESULT_BYTES)
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
