import pytest


def test_accepts_one_run_python_proposal():
    from app.proposals import validate_proposals

    assert validate_proposals([{'name': 'run_python', 'arguments': {'code': 'print(1)'}}]).code == 'print(1)'


def test_accepts_code_at_provisional_utf8_byte_limit():
    from app.proposals import validate_proposals

    code = 'é' * 8192
    assert validate_proposals([{'name': 'run_python', 'arguments': {'code': code}}]).code == code


@pytest.mark.parametrize('payload', [
    None, {}, [], 'bad',
    [{'name': 'run_python', 'arguments': {'code': 'x'}}, {'name': 'run_python', 'arguments': {'code': 'x'}}],
    [None], [{}], [{'name': 'shell', 'arguments': {'code': 'x'}}],
    [{'name': 'run_python', 'arguments': 'bad'}],
    [{'name': 'run_python', 'arguments': {}}],
    [{'name': 'run_python', 'arguments': {'code': ''}}],
    [{'name': 'run_python', 'arguments': {'code': '  \n'}}],
    [{'name': 'run_python', 'arguments': {'code': 3}}],
    [{'name': 'run_python', 'arguments': {'code': 'x', 'path': '/tmp'}}],
    [{'name': 'run_python', 'arguments': {'code': 'x'}, 'runtime': 'host'}],
    [{'name': 'run_python', 'arguments': {'code': 'x' * 16385}}],
    [{'name': 'run_python', 'arguments': {'code': 'é' * 8193}}],
    [{'name': 'run_python', 'arguments': {'code': '\ud800'}}],
])
def test_rejects_invalid_proposals(payload):
    from app.proposals import InvalidToolProposal, validate_proposals

    with pytest.raises(InvalidToolProposal, match='INVALID_TOOL_CALL'):
        validate_proposals(payload)
