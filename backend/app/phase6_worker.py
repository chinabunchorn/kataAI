"""Explicit synthetic demo worker; no real executor or model is started."""
import argparse
import sys

from .dataset_runtime import load_dataset_runtime
from .fake_worker import run_once
from .phase6_processor import process_claim
from .request_queue import RequestQueue


def main(argv=None):
    parser = argparse.ArgumentParser(description='Process at most one request using fake preset data.')
    parser.add_argument('--once', action='store_true', required=True)
    parser.parse_args(argv)
    try:
        runtime = load_dataset_runtime()
        with runtime.connection() as connection:
            outcome = run_once(connection, RequestQueue,
                               processor=lambda claim: process_claim(connection, runtime.root, claim))
        print(outcome)
        return 0
    except Exception:
        print('FAKE_WORKER_FAILED: outcome may be uncertain; no retry', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
