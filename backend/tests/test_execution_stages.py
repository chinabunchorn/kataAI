from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.execution_stages import advance_stage, close_stage, public_stages
from app.request_queue import RequestQueue
from test_postgres_live import migrated_connection as migrated_connection  # noqa: F401
from test_request_queue import ready


def test_measured_timeline_closes_once_and_never_fabricates_missing_stages():
    now = datetime.now(timezone.utc)
    stages = advance_stage([], 'generating_code', now + timedelta(seconds=2), now)
    assert stages[0]['duration_ms'] == 2000
    stages = advance_stage(stages, 'starting_execution', now + timedelta(seconds=5), now)
    assert stages[1]['duration_ms'] == 3000
    assert advance_stage(stages, 'starting_execution', now + timedelta(seconds=8), now) == stages
    assert advance_stage(stages, 'generating_code', now + timedelta(seconds=8), now) == stages
    assert 'running_in_kata' not in [s['name'] for s in stages]
    finished = close_stage(stages, now + timedelta(seconds=9), 'unknown')
    assert finished[-1]['duration_ms'] == 4000 and finished[-1]['outcome'] == 'unknown'
    assert public_stages(finished, now + timedelta(days=1))[-1]['elapsed_ms'] == 4000
    assert public_stages(stages, now + timedelta(seconds=9))[-1]['elapsed_ms'] == 4000
    assert stages[-1]['finished_at'] is None
    with pytest.raises(ValueError):
        advance_stage(stages, 'invented_vm_boot', now, now)


@pytest.mark.live_postgres
def test_timeline_is_persisted_fenced_and_closed_on_recovery(request):
    connection, _ = request.getfixturevalue('migrated_connection')
    queue = RequestQueue(connection)
    dataset = ready(connection)
    record, _ = queue.create(uuid4(), dataset, 'question')
    token = uuid4()
    queue.claim_next(token)
    assert not queue.set_stage(record.id, uuid4(), 'generating_code')
    assert queue.set_stage(record.id, token, 'generating_code')
    assert queue.set_stage(record.id, token, 'starting_execution')
    before = queue.get(record.id).execution_stages
    assert queue.set_stage(record.id, token, 'starting_execution')
    assert queue.get(record.id).execution_stages == before
    connection.commit()
    assert queue.mark_unknown_running() == 1
    connection.commit()
    result = queue.get(record.id)
    assert result.status == 'unknown'
    assert result.execution_stages[-1]['finished_at'] is not None
    assert result.execution_stages[-1]['outcome'] == 'unknown'
    assert not queue.set_stage(record.id, token, 'summarizing')


@pytest.mark.live_postgres
@pytest.mark.parametrize('status', ['completed', 'failed', 'unknown', 'needs_clarification'])
def test_terminal_outcome_closes_timing_with_same_fence(request, status):
    connection, _ = request.getfixturevalue('migrated_connection')
    queue = RequestQueue(connection)
    record, _ = queue.create(uuid4(), ready(connection), 'question')
    token = uuid4()
    queue.claim_next(token)
    queue.set_stage(record.id, token, 'generating_code')
    if status == 'completed':
        queue.bind_run(record.id, token, uuid4(), '# inert')
    result = {'answer': 2} if status == 'completed' else None
    assert not queue.finish_real(record.id, uuid4(), status, result=result)
    assert queue.get(record.id).execution_stages[-1]['finished_at'] is None
    assert queue.finish_real(record.id, token, status, result=result) == status
    connection.commit()
    persisted = queue.get(record.id)
    assert persisted.execution_stages[-1]['finished_at'] is not None
    assert persisted.execution_stages[-1]['outcome'] == status
