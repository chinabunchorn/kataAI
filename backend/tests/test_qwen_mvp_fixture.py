"""Offline synthetic Qwen proposal checks; generated code is inert text."""
from pathlib import Path

FIXTURES = Path(__file__).parent / 'fixtures' / 'qwen_mvp'


def fixed_oracles(rows):
    return {
        'total_revenue_en': {'answer': sum(int(row['quantity']) * int(row['unit_price_thb']) for row in rows)},
        'east_units_th': {'answer': sum(int(row['quantity']) for row in rows if row['region'] == 'East')},
    }


def test_expected_values_are_independently_recomputed_from_csv():
    import csv
    import json

    with (FIXTURES / 'sales.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    cases = json.loads((FIXTURES / 'cases.json').read_text(encoding='utf-8'))
    assert len(rows) == 4
    assert list(rows[0]) == ['order_id', 'region', 'quantity', 'unit_price_thb']
    expected = {case['id']: case['expected_result'] for case in cases if case['expected_kind'] == 'proposal'}
    assert expected == fixed_oracles(rows) == {
        'total_revenue_en': {'answer': 770}, 'east_units_th': {'answer': 6}}


def classify_response(response):
    from app.proposals import InvalidToolProposal, validate_proposals

    if not isinstance(response, dict):
        return 'malformed'
    if response.get('finish_reason') == 'length':
        return 'truncated'
    calls = response.get('tool_calls')
    content = response.get('content')
    if response.get('finish_reason') == 'stop' and calls == [] and isinstance(content, str) and content.strip():
        return 'clarification'  # A human must check that the text really asks for clarification.
    if response.get('finish_reason') != 'tool_calls' or content not in (None, ''):
        return 'malformed'
    try:
        validate_proposals(calls)
    except InvalidToolProposal:
        return 'malformed'
    return 'proposal'


def test_offline_response_classification_never_executes_proposed_code(tmp_path):
    marker = tmp_path / 'not-created'
    code = f"open({str(marker)!r}, 'w').write('unsafe')"
    proposal = {'name': 'run_python', 'arguments': {'code': code}}
    assert classify_response({'finish_reason': 'tool_calls', 'tool_calls': [proposal], 'content': None}) == 'proposal'
    assert not marker.exists()
    assert classify_response({'finish_reason': 'stop', 'tool_calls': [], 'content': 'Which metric?'}) == 'clarification'
    assert classify_response({'finish_reason': 'stop', 'tool_calls': [], 'content': ''}) == 'malformed'
    assert classify_response({'finish_reason': 'length', 'tool_calls': [], 'content': 'truncated'}) == 'truncated'
    assert classify_response({'finish_reason': 'tool_calls', 'tool_calls': [proposal, proposal], 'content': None}) == 'malformed'
    assert classify_response({'finish_reason': 'tool_calls', 'tool_calls': [{'name': 'shell', 'arguments': {'code': 'x'}}], 'content': None}) == 'malformed'


def matches_expected_kind(case, response):
    return classify_response(response) == case['expected_kind']


def test_synthetic_cases_check_expected_response_category():
    import json
    cases = {case['id']: case for case in json.loads((FIXTURES / 'cases.json').read_text(encoding='utf-8'))}
    assert set(cases) == {'total_revenue_en', 'east_units_th', 'missing_profit', 'ambiguous_total'}
    proposal = {'finish_reason': 'tool_calls', 'tool_calls': [{'name': 'run_python', 'arguments': {'code': 'inert'}}], 'content': None}
    question = {'finish_reason': 'stop', 'tool_calls': [], 'content': 'Please clarify.'}
    for name in ('total_revenue_en', 'east_units_th'):
        assert matches_expected_kind(cases[name], proposal)
        assert not matches_expected_kind(cases[name], question)
    for name in ('missing_profit', 'ambiguous_total'):
        assert matches_expected_kind(cases[name], question)
        assert not matches_expected_kind(cases[name], proposal)
        assert cases[name]['reason']


def test_fixture_files_exist():
    assert (FIXTURES / 'sales.csv').is_file()
    assert (FIXTURES / 'cases.json').is_file()
