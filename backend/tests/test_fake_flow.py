from app.fakes import FakeModel
import pytest


def test_fake_flow_returns_labeled_preset_json_without_running_proposed_code(tmp_path):
    from app.fake_flow import run_fake_flow

    marker = tmp_path / 'must-not-exist'
    model = FakeModel([{'name': 'run_python', 'arguments': {'code': f"open({str(marker)!r}, 'w').write('bad')"}}])
    output = run_fake_flow(model, {'answer': 17}, 'What?', ('price',))
    assert output == {'fake': True, 'code': model.generate('What?', ('price',))[0]['arguments']['code'],
                      'result': {'answer': 17}, 'summary': None,
                      'warning': 'SUMMARY_UNAVAILABLE', 'metrics': None}
    assert not marker.exists()


@pytest.mark.parametrize('request_id,dataset_id', [(None, 'bad'), ('bad', None)])
def test_invalid_fake_handoff_identifiers_fail_before_model_call(request_id, dataset_id):
    from app.fake_flow import run_fake_flow
    class Model:
        def generate(self, *_):
            pytest.fail('invalid handoff must not call model')
    with pytest.raises(ValueError, match='^INVALID_EXECUTOR_REQUEST$'):
        run_fake_flow(Model(), {}, 'q', ('column',), request_id=request_id, dataset_id=dataset_id)


def test_fake_executor_receives_complete_bound_handoff(monkeypatch, tmp_path):
    from uuid import UUID, uuid4
    from app.fake_flow import run_fake_flow
    from app.fakes import FakeExecutor

    request_id, dataset_id = uuid4(), uuid4()
    marker = tmp_path / 'must-not-exist'
    code = f"open({str(marker)!r}, 'w').write('unsafe')"
    model = FakeModel([{'name': 'run_python', 'arguments': {'code': code}}])
    seen = []
    def capture(self, handoff):
        seen.append(handoff)
        return {'answer': 17}
    monkeypatch.setattr(FakeExecutor, 'execute_handoff', capture, raising=False)
    output = run_fake_flow(model, {'answer': 17}, 'q', ('column',),
                           request_id=request_id, dataset_id=dataset_id)
    assert len(seen) == 1
    assert seen[0].request_id == request_id and seen[0].dataset_id == dataset_id
    assert isinstance(seen[0].run_id, UUID) and seen[0].proposal.code == code
    assert output['fake'] is True and not marker.exists()


def test_fake_flow_preserves_large_valid_object_at_existing_item_limit():
    from app.fake_flow import run_fake_flow
    model = FakeModel([{'name': 'run_python', 'arguments': {'code': 'inert'}}])
    data = {str(i): 0 for i in range(2048)}
    output = run_fake_flow(model, data, 'q', ('column',))
    assert output['fake'] is True and output['result'] == data


def test_fake_preset_passes_bounded_result_decoder(monkeypatch):
    from app import fake_flow
    from app.executor_results import decode_execution_result

    seen = []
    def decoder(raw):
        seen.append(raw)
        return decode_execution_result(raw)

    monkeypatch.setattr(fake_flow, 'decode_execution_result', decoder, raising=False)
    model = FakeModel([{'name': 'run_python', 'arguments': {'code': 'inert'}}])
    output = fake_flow.run_fake_flow(model, {'answer': 17}, 'q', ('column',))
    assert output['fake'] is True and output['result'] == {'answer': 17}
    assert len(seen) == 1 and seen[0] == b'{"answer":17}'


def test_summary_receives_real_inputs_and_cannot_replace_result():
    from app.fake_flow import run_fake_flow

    class Model(FakeModel):
        def generate(self, question, columns):
            assert (question, columns) == ('ยอดรวม?', ('ราคา', 'count'))
            return super().generate(question, columns)

        def summarize(self, question, result):
            assert question == 'ยอดรวม?'
            assert result == {'rows': [1, 2]}
            result['rows'].append(999)
            return result, 'Synthetic summary', None

    model = Model([{'name': 'run_python', 'arguments': {'code': 'x'}}])
    output = run_fake_flow(model, {'rows': [1, 2]}, 'ยอดรวม?', ('ราคา', 'count'))
    assert output['result'] == {'rows': [1, 2]}
    assert output['summary'] == 'Synthetic summary'
    assert output['warning'] is None


@pytest.mark.parametrize('result', [float('nan'), {'bad': object()}, {'large': 'x' * 32769}])
def test_rejects_unbounded_or_non_json_fake_results(result):
    from app.fake_flow import run_fake_flow
    from app.model_adapter import ModelAdapterError

    model = FakeModel([{'name': 'run_python', 'arguments': {'code': 'x'}}])
    with pytest.raises(ModelAdapterError):
        run_fake_flow(model, result, 'question', ('a',))


@pytest.mark.parametrize('result', [None, [], [1, {'x': None}], 3, True, 'text', {'empty': []}])
def test_accepts_generic_json_result_shapes(result):
    from app.fake_flow import run_fake_flow
    model = FakeModel([{'name': 'run_python', 'arguments': {'code': 'x'}}])
    assert run_fake_flow(model, result, 'q', ('c',))['result'] == result


@pytest.mark.parametrize('proposals', [[], [{'name': 'shell', 'arguments': {'code': 'x'}}],
                                      [{'name': 'run_python', 'arguments': {'code': 'x'}}] * 2])
def test_invalid_proposals_fail_without_summary_or_retry(proposals):
    from app.fake_flow import run_fake_flow
    from app.proposals import InvalidToolProposal

    class Model(FakeModel):
        calls = 0
        def generate(self, question, columns):
            self.calls += 1
            return super().generate(question, columns)
        def summarize(self, question, result):
            pytest.fail('invalid proposal must not be summarized')

    model = Model(proposals)
    with pytest.raises(InvalidToolProposal):
        run_fake_flow(model, {}, 'q', ('a',))
    assert model.calls == 1


@pytest.mark.parametrize('response', ['exception', (None, None, 'SUMMARY_UNAVAILABLE'),
                                      (None, '', None), (None, 'x' * 8193, None)])
def test_summary_failure_preserves_result_without_retry(response):
    from app.fake_flow import run_fake_flow
    class Model(FakeModel):
        calls = 0
        def summarize(self, question, result):
            self.calls += 1
            result.append('mutation')
            if response == 'exception':
                raise RuntimeError('private error')
            return response
    model = Model([{'name': 'run_python', 'arguments': {'code': 'x'}}])
    output = run_fake_flow(model, [1], 'q', ('a',))
    assert output['result'] == [1]
    assert output['summary'] is None
    assert output['warning'] == 'SUMMARY_UNAVAILABLE'
    assert model.calls == 1


def test_result_validation_rejects_cycles_and_excessive_depth():
    from app.fake_flow import run_fake_flow
    from app.model_adapter import ModelAdapterError
    cyclic = []
    cyclic.append(cyclic)
    deep = 1
    for _ in range(18):
        deep = [deep]
    model = FakeModel([{'name': 'run_python', 'arguments': {'code': 'x'}}])
    for result in (cyclic, deep):
        with pytest.raises(ModelAdapterError):
            run_fake_flow(model, result, 'q', ('a',))
