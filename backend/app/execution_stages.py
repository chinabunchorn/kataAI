"""Trusted worker observations, never model-selected progress or estimated stages."""
from copy import deepcopy
from datetime import datetime

STAGES = {'queued', 'preparing_input', 'generating_code', 'validating_code',
          'starting_execution', 'waiting_for_container', 'running_in_kata',
          'collecting_result', 'summarizing', 'checking_execution'}


def close_stage(stages, now, outcome='finished'):
    stages = deepcopy(stages)
    if stages and stages[-1]['finished_at'] is None:
        last = stages[-1]
        last.update(finished_at=now.isoformat(),
                    duration_ms=max(0, round((now - datetime.fromisoformat(last['started_at'])).total_seconds() * 1000)),
                    outcome=outcome)
    return stages


def advance_stage(stages, name, now, created_at):
    if name not in STAGES:
        raise ValueError('INVALID_EXECUTION_STAGE')
    if not stages:
        stages = [{'name': 'queued', 'started_at': created_at.isoformat(),
                   'finished_at': None, 'duration_ms': None}]
    if stages[-1]['name'] == name:
        return stages
    # Provider observations can regress to Pending or Unknown. Never rewind a
    # measured stage, and never invent a duration for an unobserved Running Pod.
    if any(stage['name'] == name for stage in stages):
        return stages
    stages = close_stage(stages, now)
    stages.append({'name': name, 'started_at': now.isoformat(), 'finished_at': None, 'duration_ms': None})
    return stages


def public_stages(stages, now):
    result = deepcopy(stages)
    for stage in result:
        stage['elapsed_ms'] = (stage['duration_ms'] if stage['finished_at'] else
                               max(0, round((now - datetime.fromisoformat(stage['started_at'])).total_seconds() * 1000)))
    return result
