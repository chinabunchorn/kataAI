def test_fake_model_returns_preset_proposals_without_mutation():
    from app.fakes import FakeModel

    preset = [{'name': 'run_python', 'arguments': {'code': 'print(1)'}}]
    model = FakeModel(preset)
    result = model.generate('question', ('column',))
    result[0]['arguments']['code'] = 'changed'
    assert model.generate('another question', ()) == preset


def test_fake_executor_returns_preset_without_running_code(tmp_path):
    from app.fakes import FakeExecutor
    from app.proposals import PythonProposal

    target = tmp_path / 'should-not-exist'
    code = f"open({str(target)!r}, 'w').write('executed')"
    executor = FakeExecutor({'value': 42})
    assert executor.execute(PythonProposal(code)) == {'value': 42}
    assert not target.exists()


def test_fake_executor_unavailable_fails_closed():
    import pytest
    from app.fakes import ExecutionUnavailable, FakeExecutor
    from app.proposals import PythonProposal

    executor = FakeExecutor({'value': 42}, available=False)
    with pytest.raises(ExecutionUnavailable, match='EXECUTION_UNAVAILABLE'):
        executor.execute(PythonProposal('print(1)'))
