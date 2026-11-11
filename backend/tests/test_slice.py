def test_fake_backed_flow_returns_preset_result():
    from app.fakes import FakeExecutor, FakeModel
    from app.slice import run_fake_slice

    model = FakeModel([{'name': 'run_python', 'arguments': {'code': 'print(1)'}}])
    assert run_fake_slice(model, FakeExecutor({'answer': 1}), 'question', ('a',)) == {'answer': 1}


def test_invalid_proposal_never_reaches_executor():
    import pytest
    from app.fakes import FakeModel
    from app.proposals import InvalidToolProposal
    from app.slice import run_fake_slice

    class MustNotRun:
        def execute(self, proposal):
            raise AssertionError('executor must not be called')

    model = FakeModel([{'name': 'shell', 'arguments': {'code': 'x'}}])
    with pytest.raises(InvalidToolProposal):
        run_fake_slice(model, MustNotRun(), 'question', ())


def test_unavailable_executor_propagates_through_slice():
    import pytest
    from app.fakes import ExecutionUnavailable, FakeExecutor, FakeModel
    from app.slice import run_fake_slice

    model = FakeModel([{'name': 'run_python', 'arguments': {'code': 'x'}}])
    with pytest.raises(ExecutionUnavailable):
        run_fake_slice(model, FakeExecutor({}, available=False), 'question', ())
