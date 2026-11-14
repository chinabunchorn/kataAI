"""Fake flow request integration; synthetic records only."""
from types import SimpleNamespace
from uuid import uuid4


def test_processor_passes_question_and_only_columns_to_model(monkeypatch, tmp_path):
    from app import phase6_processor
    dataset_id, key = uuid4(), uuid4()
    dataset = SimpleNamespace(id=dataset_id, storage_key=key, lifecycle='active', publication_state='ready')
    seen = []

    class Store:
        def __init__(self, connection):
            pass
        def get(self, value):
            assert value == dataset_id
            return dataset

    class Connection:
        committed = False
        def commit(self):
            self.committed = True

    connection = Connection()
    class Model:
        def generate(self, question, columns):
            assert connection.committed
            seen.append((question, columns))
            return [{'name': 'run_python', 'arguments': {'code': 'raise RuntimeError("not executed")'}}]
        def summarize(self, question, result):
            return result, 'Synthetic summary', None

    monkeypatch.setattr(phase6_processor, 'PostgresDatasetStore', Store)
    monkeypatch.setattr(phase6_processor, 'read_dataset_columns', lambda root, file_key: ('item', 'count'))
    claim = SimpleNamespace(dataset_id=dataset_id, question='How many?')
    result = phase6_processor.process_claim(connection, tmp_path, claim, model=Model())
    assert seen == [('How many?', ('item', 'count'))]
    assert result['fake'] is True and result['metrics'] is None
    assert result['code'] == 'raise RuntimeError("not executed")'
    assert result['result'] == {'example': [1, 2]}


def test_processor_refuses_incomplete_dataset_before_open_or_model(monkeypatch, tmp_path):
    import pytest
    from app import phase6_processor
    from app.ready_dataset import DatasetUnavailable
    dataset_id = uuid4()

    class Store:
        def __init__(self, connection):
            pass
        def get(self, value):
            return SimpleNamespace(id=dataset_id, lifecycle='active', publication_state='unknown')

    monkeypatch.setattr(phase6_processor, 'PostgresDatasetStore', Store)
    monkeypatch.setattr(phase6_processor, 'read_dataset_columns', lambda *_: pytest.fail('must not open'))
    with pytest.raises(DatasetUnavailable):
        phase6_processor.process_claim(object(), tmp_path, SimpleNamespace(dataset_id=dataset_id, question='q'))
