"""Phase 6 entry point must explicitly run the fake-only processor."""
from contextlib import contextmanager
from types import SimpleNamespace


def test_explicit_demo_invokes_fake_worker_with_fixed_processor(monkeypatch, tmp_path, capsys):
    from app import phase6_worker
    captured = {}
    connection = object()

    @contextmanager
    def open_connection():
        yield connection

    runtime = SimpleNamespace(root=tmp_path, connection=open_connection)
    monkeypatch.setattr(phase6_worker, 'load_dataset_runtime', lambda: runtime)
    def fake_run(conn, factory, *, processor):
        captured.update(connection=conn, factory=factory, processor=processor)
        return 'idle'
    monkeypatch.setattr(phase6_worker, 'run_once', fake_run)
    assert phase6_worker.main(['--once']) == 0
    assert captured['connection'] is connection
    assert callable(captured['processor'])
    assert capsys.readouterr().out.strip() == 'idle'


def test_worker_failure_is_sanitized(monkeypatch, capsys):
    from app import phase6_worker
    def fail():
        raise RuntimeError('sensitive question /secret')
    monkeypatch.setattr(phase6_worker, 'load_dataset_runtime', fail)
    assert phase6_worker.main(['--once']) == 1
    stderr = capsys.readouterr().err
    assert 'sensitive' not in stderr and '/secret' not in stderr
    assert 'uncertain' in stderr
