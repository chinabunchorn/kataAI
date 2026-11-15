"""Private, opt-in single-process Qwen → remote Kata demo. Never executes code locally."""
import argparse
import os
import stat
import sys
import time
from uuid import uuid4

import sqlalchemy as sa

from .dataset_columns import read_dataset_columns
from .dataset_runtime import load_dataset_runtime
from .dataset_store import PostgresDatasetStore
from .executor_contract import ExecutorRequest, ExecutorStatus, RunState
from .executor_results import decode_execution_result
from .fake_worker import _LOCK_PARAMS, _require_ownership, OwnershipLost
from .model_adapter import LocalModelAdapter, ModelTextOnlyOutcome
from .proposals import validate_proposals
from .request_queue import RequestQueue

RUNNER_IMAGE = 'docker.io/kataai/runner@sha256:6a682ed00f47fc27c18eb3abd9e3448960133433265ec6442339c9484d246bf9'
# Independently recorded in Runner 0.1.1 build-metadata.json; containerd may
# report either the manifest identity or the released linux/amd64 config ID.
RUNNER_CONFIG = 'sha256:19e8bd4750d918f4c21daaea258434eeec3f080a61ae3821181cc1925245af12'


def verify_image(image, container_status):
    if image != RUNNER_IMAGE:
        return False
    observed = container_status.get('imageID', '')
    approved = {RUNNER_IMAGE, RUNNER_IMAGE.removeprefix('docker.io/'),
                RUNNER_CONFIG, RUNNER_IMAGE.split('@')[1]}
    for prefix in ('docker-pullable://', 'docker://', 'containerd://'):
        observed = observed.removeprefix(prefix)
    return observed in approved


def _dataset(connection, dataset_id):
    dataset = PostgresDatasetStore(connection).get(dataset_id)
    if dataset.lifecycle != 'active' or dataset.publication_state != 'ready':
        raise ValueError('DATASET_UNAVAILABLE')
    return dataset


def resolve_dataset(connection, root, request, cap):
    """Resolve only a server-owned UUID key, preserving POSIX ownership guards."""
    dataset = _dataset(connection, request.dataset_id)
    directory = os.open(os.path.normpath(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or info.st_mode & 0o7077:
            raise ValueError('INVALID_ROOT')
        fd = os.open(str(dataset.storage_key), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o7077 or info.st_nlink != 1 or info.st_size > cap):
                raise ValueError('DATASET_UNAVAILABLE')
            data = stream.read(cap + 1)
            if len(data) > cap:
                raise ValueError('DATASET_TOO_LARGE')
        connection.commit()
        return data
    finally:
        os.close(directory)


def build_executor(connection, root, *, kubeconfig, context, journal):
    from infra.executor import KataExecutor, KubectlAPI, SQLiteRunStore
    # Keep journal files private even when the caller's shell has a permissive umask.
    directory = os.path.dirname(os.path.abspath(journal))
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or info.st_mode & 0o7077:
            raise ValueError('INVALID_JOURNAL_ROOT')
    finally:
        os.close(fd)
    for path in (journal, journal + '.lock'):
        if os.path.lexists(path):
            info = os.lstat(path)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o7077 or info.st_nlink != 1):
                raise ValueError('INVALID_JOURNAL_FILE')
    old_umask = os.umask(0o077)
    try:
        store = SQLiteRunStore(journal)
    finally:
        os.umask(old_umask)
    return KataExecutor(KubectlAPI(kubeconfig, context), store, image=RUNNER_IMAGE,
        resolve_dataset=lambda request, cap: resolve_dataset(connection, root, request, cap),
        authorize=lambda request: os.environ.get('KATAAI_PRIVATE_EXPERIMENTAL_DEMO') == '1',
        verify_image=verify_image, observe_teardown=lambda record: None)


def _correlate(value, claim, run_id):
    if value.request_id != claim.id or value.run_id != run_id:
        raise ValueError('EXECUTOR_IDENTITY_MISMATCH')
    return value


def process_claim(connection, root, claim, *, model, executor, queue=None,
                  wait_seconds=180, poll_seconds=1, clock=time.monotonic, sleep=time.sleep):
    queue = queue or RequestQueue(connection)
    token = claim.claim_token
    run_id = None
    submitted = False
    cancel = False
    status, result, answer, error = 'failed', None, None, 'DATASET_UNAVAILABLE'
    def stage(name):
        _require_ownership(connection)
        if not queue.set_stage(claim.id, token, name):
            raise OwnershipLost('CLAIM_LOST')
        connection.commit()  # Browser GETs can observe progress while model/provider calls block.

    try:
        stage('preparing_input')
        dataset = _dataset(connection, claim.dataset_id)
        columns = read_dataset_columns(root, dataset.storage_key)
        connection.commit()
        error = 'MODEL_GENERATION_FAILED'
        try:
            stage('generating_code')
            proposals = model.generate(claim.question, columns)
        except ModelTextOnlyOutcome as outcome:
            status, answer, error = 'needs_clarification', outcome.text, None
        else:
            stage('validating_code')
            error = 'INVALID_TOOL_PROPOSAL'
            proposal = validate_proposals(proposals)
            _require_ownership(connection)
            run_id = uuid4()
            request = ExecutorRequest(claim.id, run_id, claim.dataset_id, proposal, 30)
            if not queue.bind_run(claim.id, token, run_id, proposal.code):
                raise OwnershipLost('CLAIM_LOST')
            connection.commit()  # Real UUID and code precede ANY Kubernetes side effect.
            error = 'EXECUTION_FAILED'
            stage('starting_execution')
            submitted = True  # Submit can have an uncertain response.
            ack = _correlate(executor.submit(request), claim, run_id)
            if ack.status != ExecutorStatus.ACCEPTED:
                status = 'unknown' if ack.status == ExecutorStatus.UNKNOWN else 'failed'
                error = 'SUBMISSION_UNKNOWN' if status == 'unknown' else 'EXECUTION_REJECTED'
                store = getattr(executor, 'store', None)
                record = store.get(str(run_id)) if store is not None else None
                if record and record.get('last_error'):
                    error = record['last_error']
                cancel = True
            else:
                stage('waiting_for_container')
                deadline = clock() + wait_seconds
                while True:
                    _require_ownership(connection)
                    current = queue.get(claim.id)
                    connection.commit()
                    if current is None or current.status == 'cancel_requested':
                        status, error, cancel = 'unknown', 'CANCEL_REQUESTED', True
                        break
                    observation = _correlate(executor.status(claim.id, run_id), claim, run_id)
                    if observation.state == RunState.UNKNOWN:
                        stage('checking_execution')
                    if observation.state == RunState.RUNNING:
                        stage('running_in_kata')
                    if observation.state == RunState.COMPLETED:
                        stage('collecting_result')
                        raw = executor.read_result(claim.id, run_id)
                        if type(raw) is not bytes or len(raw) > 2048:
                            raise ValueError('INVALID_RUNNER_RESULT')
                        result = decode_execution_result(raw)
                        if type(result) not in (dict, list):
                            raise ValueError('INVALID_RUNNER_RESULT')
                        stage('summarizing')
                        # summarize() preserves computed data; never replace it with model data.
                        try:
                            _, answer, error = model.summarize(claim.question, result)
                        except Exception:
                            answer, error = None, 'SUMMARY_UNAVAILABLE'
                        status = 'completed'
                        break
                    if observation.state in {RunState.FAILED, RunState.CANCELLED}:
                        outcome = executor.outcome(claim.id, run_id)
                        error = outcome.get('code', 'EXECUTION_FAILED') if outcome else 'EXECUTION_FAILED'
                        status = 'failed'
                        break
                    if clock() >= deadline:
                        status, error, cancel = 'unknown', 'EXECUTION_TIMEOUT', True
                        break
                    sleep(poll_seconds)
    except OwnershipLost:
        raise  # Never publish/clean up under lost database ownership.
    except Exception:
        connection.rollback()
        if submitted:
            status, error, cancel = 'unknown', 'EXECUTION_UNCERTAIN', True
    _require_ownership(connection)
    persisted = queue.finish_real(claim.id, token, status, result=result, answer=answer, error_code=error)
    if not persisted:
        raise OwnershipLost('CLAIM_LOST')
    connection.commit()  # Preserve outcome before cleanup, including on summary failure.
    if submitted:
        try:
            if cancel:
                executor.cancel(claim.id, run_id)
            executor.cleanup(claim.id, run_id)
            observation = executor.status(claim.id, run_id)
            print(f'cleanup={observation.cleanup.value}; guest teardown requires independent observer')
        except Exception:
            print('CLEANUP_PENDING: retain journal and run UUID', file=sys.stderr)
    return persisted


def run_once(connection, root, *, model, executor, queue_factory=RequestQueue):
    acquired = connection.execute(sa.text(
        'SELECT pg_try_advisory_lock(:namespace, :worker)'), _LOCK_PARAMS).scalar_one()
    connection.commit()
    if not acquired:
        return 'busy'
    try:
        _require_ownership(connection)
        queue = queue_factory(connection)
        queue.mark_unknown_running()
        connection.commit()
        _require_ownership(connection)
        claim = queue.claim_next(uuid4())
        connection.commit()
        if claim is None:
            return 'idle'
        return process_claim(connection, root, claim, model=model, executor=executor, queue=queue)
    finally:
        connection.rollback()
        connection.execute(sa.text('SELECT pg_advisory_unlock(:namespace, :worker)'), _LOCK_PARAMS)
        connection.commit()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true')
    mode.add_argument('--loop', action='store_true')
    parser.add_argument('--model-endpoint', default='http://127.0.0.1:8080/v1/chat/completions')
    parser.add_argument('--model', default='Qwen3.5-9B-Q4_K_M')
    parser.add_argument('--kubeconfig', required=True)
    parser.add_argument('--context', required=True)
    parser.add_argument('--journal', required=True)
    args = parser.parse_args(argv)
    if os.environ.get('KATAAI_PRIVATE_EXPERIMENTAL_DEMO') != '1':
        print('EXECUTION_NOT_APPROVED: set KATAAI_PRIVATE_EXPERIMENTAL_DEMO=1 for the private research demo', file=sys.stderr)
        return 1
    try:
        runtime = load_dataset_runtime()
        model = LocalModelAdapter(args.model_endpoint, model=args.model)
        while True:
            with runtime.connection() as connection:
                executor = build_executor(connection, runtime.root, kubeconfig=args.kubeconfig,
                                          context=args.context, journal=args.journal)
                outcome = run_once(connection, runtime.root, model=model, executor=executor)
                if args.once or outcome not in {'idle', 'busy'}:
                    print(outcome, flush=True)
            if args.once:
                return 0
            time.sleep(1)
    except KeyboardInterrupt:
        return 130
    except Exception:
        print('KATA_WORKER_FAILED: outcome may be uncertain; retain journal; no automatic retry', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
