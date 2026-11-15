def test_fake_backed_flow_returns_preset_result():
    from app.fakes import FakeExecutor, FakeModel
    from app.slice import run_fake_slice

    model = FakeModel([{'name': 'run_python', 'arguments': {'code': 'print(1)'}}])
    assert run_fake_slice(model, FakeExecutor({'answer': 1}), 'question', ('a',)) == {'answer': 1}


def test_fake_slice_passes_question_columns_and_validated_code_to_adapters():
    from app.fakes import FakeExecutor, FakeModel
    from app.proposals import PythonProposal
    from app.slice import run_fake_slice

    seen = {}

    class RecordingModel(FakeModel):
        def generate(self, question, columns):
            seen['generation'] = (question, columns)
            return super().generate(question, columns)

    class RecordingExecutor(FakeExecutor):
        def execute(self, proposal):
            seen['proposal'] = proposal
            return super().execute(proposal)

    model = RecordingModel([{'name': 'run_python', 'arguments': {'code': 'print(1)'}}])
    result = run_fake_slice(model, RecordingExecutor({'answer': 1}), 'ยอดรวม?', ('ราคา', 'a'))
    assert result == {'answer': 1}
    assert seen == {'generation': ('ยอดรวม?', ('ราคา', 'a')), 'proposal': PythonProposal('print(1)')}


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
