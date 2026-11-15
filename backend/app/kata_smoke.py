"""Explicit trusted fixture smoke, before enabling Qwen-generated dispatch.

This is a separate hand-written acceptance probe, never a model-code fallback.
Requires a pre-uploaded synthetic sales.csv UUID and an otherwise idle queue.
"""
import argparse
import os
import sys
from uuid import UUID, uuid4

import sqlalchemy as sa

from .dataset_runtime import load_dataset_runtime
from .fake_worker import _LOCK_PARAMS, _require_ownership
from .kata_demo_worker import build_executor, process_claim
from .request_queue import RequestQueue

SMOKE_CODE = '''import csv, json
with open('/inputs/data.csv', encoding='utf-8-sig', newline='') as f:
    rows = list(csv.DictReader(f))
with open('/tmp/result.json', 'w', encoding='utf-8') as f:
    json.dump({'rows': len(rows), 'columns': list(rows[0]) if rows else []}, f)
'''


class TrustedFixtureModel:
    def generate(self, question, columns):
        return [{'name': 'run_python', 'arguments': {'code': SMOKE_CODE}}]
    def summarize(self, question, result):
        return result, None, 'SUMMARY_UNAVAILABLE'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-id', type=UUID, required=True)
    parser.add_argument('--kubeconfig', required=True)
    parser.add_argument('--context', required=True)
    parser.add_argument('--journal', required=True)
    args = parser.parse_args(argv)
    if os.environ.get('KATAAI_PRIVATE_EXPERIMENTAL_DEMO') != '1':
        print('EXECUTION_NOT_APPROVED', file=sys.stderr)
        return 1
    try:
        runtime = load_dataset_runtime()
        with runtime.connection() as connection:
            acquired = connection.execute(sa.text(
                'SELECT pg_try_advisory_lock(:namespace, :worker)'), _LOCK_PARAMS).scalar_one()
            connection.commit()
            if not acquired:
                raise ValueError('WORKER_BUSY')
            try:
                _require_ownership(connection)
                busy = connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM request_intents "
                    "WHERE status IN ('queued','running','cancel_requested'))")).scalar_one()
                if busy:
                    raise ValueError('QUEUE_NOT_IDLE')
                queue = RequestQueue(connection)
                record, _ = queue.create(uuid4(), args.dataset_id, 'Trusted hand-written synthetic CSV smoke')
                token = uuid4()
                claim = queue.claim_next(token)
                if claim is None or claim.id != record.id:
                    connection.rollback()
                    raise ValueError('QUEUE_NOT_IDLE')
                connection.commit()
                executor = build_executor(connection, runtime.root, kubeconfig=args.kubeconfig,
                                          context=args.context, journal=args.journal)
                print(f'request_id={record.id}; trusted hand-written probe; no Qwen generation', flush=True)
                status = process_claim(connection, runtime.root, claim, model=TrustedFixtureModel(), executor=executor)
                print(status)
                return 0 if status == 'completed' else 1
            finally:
                connection.rollback()
                connection.execute(sa.text('SELECT pg_advisory_unlock(:namespace, :worker)'), _LOCK_PARAMS)
                connection.commit()
    except Exception:
        print('KATA_SMOKE_FAILED: inspect persisted request/journal; no automatic retry', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
