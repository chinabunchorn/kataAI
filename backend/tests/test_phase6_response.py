"""Phase 6 response contract: synthetic records, no code execution."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.request_api import public_record


def test_completed_fake_detail_exposes_inert_result_and_unavailable_metrics():
    output = {'fake': True, 'code': 'raise RuntimeError("never executed")',
              'result': {'points': [1, 2]}, 'summary': None,
              'warning': 'SUMMARY_UNAVAILABLE', 'metrics': None}
    record = SimpleNamespace(id=uuid4(), dataset_id=uuid4(), status='fake_completed',
                             question='Synthetic question', created_at=datetime.now(timezone.utc),
                             fake_result=output)
    response = public_record(record, include_detail=True)
    assert response['fake'] is True
    assert response['fake_result'] == output
    assert response['fake_result']['metrics'] is None


def test_invalid_stored_envelope_is_not_returned():
    import pytest
    record = SimpleNamespace(id=uuid4(), dataset_id=uuid4(), status='fake_completed',
                             question='Synthetic question', created_at=datetime.now(timezone.utc),
                             fake_result={'fake': False, 'code': 'x', 'result': None})
    with pytest.raises(ValueError):
        public_record(record, include_detail=True)


def test_legacy_fake_completion_without_output_is_honest():
    record = SimpleNamespace(id=uuid4(), dataset_id=uuid4(), status='fake_completed',
                             question='Synthetic question', created_at=datetime.now(timezone.utc))
    response = public_record(record, include_detail=True)
    assert response['fake'] is True
    assert response.get('fake_result') is None
