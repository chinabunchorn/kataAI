"""Explicit fake-only worker: ``python -m app.fake_worker --once``.

Every cooperating worker must hold this session-level advisory lock on one
non-pooled connection throughout recovery, claim and finish. On takeover,
previous running claims become unknown and are never automatically retried.
``running`` is last-observed state, not a liveness guarantee. The claim token
fences database writes only, not external side effects (there are none here).
Commit acknowledgement loss is uncertain; the worker stops without retrying.
"""
import argparse
import sys
from uuid import uuid4

import sqlalchemy as sa

# Shared by every cooperating worker, stable across processes and restarts.
LOCK_NAMESPACE = 0x4B415441
LOCK_WORKER = 0x46414B45
_LOCK_PARAMS = {'namespace': LOCK_NAMESPACE, 'worker': LOCK_WORKER}
_OWNED = sa.text('''
    SELECT EXISTS (
        SELECT 1 FROM pg_locks
        WHERE locktype = 'advisory' AND pid = pg_backend_pid()
          AND classid = CAST(:namespace AS oid) AND objid = CAST(:worker AS oid)
          AND objsubid = 2 AND granted
    )
''')


class OwnershipLost(RuntimeError):
    """Session ownership no longer verifiable; do not continue."""


def _require_ownership(connection):
    if not connection.execute(_OWNED, _LOCK_PARAMS).scalar_one():
        raise OwnershipLost('WORKER_OWNERSHIP_LOST')


def run_once(connection, queue_factory):
    """Run at most one fake claim on a dedicated session; caller closes it.

    Return busy, idle, fake_completed, or stale. Exceptions mean outcome may
    be uncertain, including when a COMMIT was sent but not acknowledged.
    """
    acquired = False
    failed = False
    try:
        acquired = connection.execute(
            sa.text('SELECT pg_try_advisory_lock(:namespace, :worker)'), _LOCK_PARAMS
        ).scalar_one()
        if not acquired:
            connection.rollback()
            return 'busy'
        # Close the lock acquisition transaction; session lock survives commits.
        connection.commit()
        _require_ownership(connection)
        queue = queue_factory(connection)
        queue.mark_unknown_running()
        connection.commit()
        _require_ownership(connection)
        token = uuid4()
        claim = queue.claim_next(token)
        connection.commit()
        if claim is None:
            return 'idle'
        # Fake work is deliberately just a fixed status transition: no question,
        # dataset access, generated code, model, or external execution.
        _require_ownership(connection)
        completed = queue.complete_fake(claim.id, token)
        connection.commit()
        return 'fake_completed' if completed else 'stale'
    except BaseException:
        failed = True
        raise
    finally:
        if acquired:
            try:
                # Cleanup is not a statement about the outcome of any commit.
                connection.rollback()
                unlocked = connection.execute(
                    sa.text('SELECT pg_advisory_unlock(:namespace, :worker)'), _LOCK_PARAMS
                ).scalar_one()
                if not unlocked:
                    raise OwnershipLost('WORKER_OWNERSHIP_LOST')
                connection.commit()
            except Exception:
                if not failed:
                    raise


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run one explicitly requested fake-only queue cycle.')
    parser.add_argument('--once', action='store_true', required=True)
    parser.parse_args(argv)
    try:
        from .dataset_runtime import load_dataset_runtime
        from .request_queue import RequestQueue
        runtime = load_dataset_runtime()
        with runtime.connection() as connection:
            outcome = run_once(connection, RequestQueue)
        print(outcome)
        return 0
    except Exception:
        # Database exceptions can contain URLs, SQL parameters or questions.
        print('FAKE_WORKER_FAILED: outcome may be uncertain; no retry', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
