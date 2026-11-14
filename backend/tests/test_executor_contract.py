from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from app.proposals import PythonProposal


def test_request_preserves_run_bound_inert_values():
    from app.executor_contract import ExecutorRequest

    request_id, run_id, dataset_id = uuid4(), uuid4(), uuid4()
    from app.proposals import PythonProposal

    proposal = PythonProposal('print(1)')
    request = ExecutorRequest(request_id, run_id, dataset_id, proposal, 30)
    assert (request.request_id, request.run_id, request.dataset_id) == (request_id, run_id, dataset_id)
    assert request.proposal == proposal
    assert request.timeout_seconds == 30


@pytest.mark.parametrize('field,bad', [
    ('request_id', 'not-a-uuid'), ('request_id', None),
    ('run_id', str(uuid4())), ('dataset_id', 4),
    ('proposal', 'print(1)'), ('proposal', PythonProposal(' ')),
    ('proposal', PythonProposal('x' * 16385)), ('proposal', PythonProposal('\ud800')),
    ('proposal', PythonProposal('print(1)\x00')),
    ('timeout_seconds', 0), ('timeout_seconds', 301),
    ('timeout_seconds', True), ('timeout_seconds', 1.5),
])
def test_request_rejects_invalid_inputs(field, bad):
    from app.executor_contract import ExecutorRequest

    values = dict(request_id=uuid4(), run_id=uuid4(), dataset_id=uuid4(),
                  proposal=PythonProposal('print(1)'), timeout_seconds=30)
    values[field] = bad
    with pytest.raises(ValueError):
        ExecutorRequest(**values)


def test_result_is_run_bound_and_rejects_unrecognized_status():
    from app.executor_contract import ExecutorResult, ExecutorStatus

    request_id, run_id = uuid4(), uuid4()
    for status in (ExecutorStatus.ACCEPTED, ExecutorStatus.REJECTED, ExecutorStatus.UNKNOWN):
        result = ExecutorResult(request_id, run_id, status)
        assert (result.request_id, result.run_id, result.status) == (request_id, run_id, status)
    with pytest.raises(ValueError):
        ExecutorResult(request_id, run_id, 'accepted')
    with pytest.raises(ValueError):
        ExecutorResult('bad', run_id, ExecutorStatus.UNKNOWN)


def test_observation_distinguishes_run_state_from_submission_ack():
    from app.executor_contract import ExecutorObservation, RunState, CleanupState
    request_id, run_id = uuid4(), uuid4()
    observation = ExecutorObservation(request_id, run_id, RunState.RUNNING, CleanupState.NOT_STARTED)
    assert observation.state is RunState.RUNNING
    assert observation.cleanup is CleanupState.NOT_STARTED
    with pytest.raises(ValueError):
        ExecutorObservation(request_id, run_id, 'running', CleanupState.NOT_STARTED)
    with pytest.raises(ValueError):
        ExecutorObservation(request_id, run_id, RunState.RUNNING, 'confirmed')


def test_future_executor_interface_has_explicit_lifecycle_operations():
    from app.executor_contract import FutureExecutor

    assert all(callable(getattr(FutureExecutor, name)) for name in ('submit', 'status', 'read_result', 'cancel', 'cleanup'))


@pytest.mark.parametrize('timeout', [1, 300])
def test_request_timeout_boundaries_and_no_infrastructure_fields(timeout):
    from app.executor_contract import ExecutorRequest

    request = ExecutorRequest(uuid4(), uuid4(), uuid4(), PythonProposal('print(1)'), timeout)
    assert request.timeout_seconds == timeout
    assert 'print(1)' not in repr(request)
    with pytest.raises(FrozenInstanceError):
        request.timeout_seconds = 5
    with pytest.raises(TypeError):
        ExecutorRequest(uuid4(), uuid4(), uuid4(), PythonProposal('x'), timeout, path='/tmp')


def test_result_is_immutable():
    from app.executor_contract import ExecutorResult, ExecutorStatus

    result = ExecutorResult(uuid4(), uuid4(), ExecutorStatus.UNKNOWN)
    with pytest.raises(FrozenInstanceError):
        result.status = ExecutorStatus.ACCEPTED
