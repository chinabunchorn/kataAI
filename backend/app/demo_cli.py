"""Upload a CSV, ask a question and poll the existing private HTTP API."""
import argparse
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

import httpx


def demo(csv, question, *, base_url='http://127.0.0.1:8000', wait_seconds=360):
    from .local_security import SecurityPolicy
    policy = SecurityPolicy(host=base_url.removeprefix('http://'), origin=base_url)
    headers = {'Host': policy.host, 'Origin': policy.origin, 'X-KataAI-Request': '1'}
    with httpx.Client(base_url=base_url, headers=headers, timeout=65, trust_env=False,
                      follow_redirects=False) as client:
        def checked(response):
            if response.is_error:
                try:
                    code = response.json().get('error', {}).get('code', 'HTTP_ERROR')
                except ValueError:
                    code = 'INVALID_HTTP_RESPONSE'
                raise RuntimeError(f'{response.status_code}: {code}')
            return response.json()
        with Path(csv).open('rb') as stream:
            dataset = checked(client.post('/v1/datasets', files={'file': (Path(csv).name, stream, 'text/csv')}))
        request = checked(client.post('/v1/requests', json={
            'schema_version': '1.0', 'client_request_id': str(uuid4()), 'dataset_id': dataset['dataset_id'], 'question': question}))
        print(f"dataset_id={dataset['dataset_id']} request_id={request['id']}", flush=True)
        deadline = time.monotonic() + wait_seconds
        while True:
            record = checked(client.get('/v1/requests/' + request['id']))
            if record['status'] not in {'queued', 'running', 'cancel_requested'}:
                print(json.dumps(record, ensure_ascii=False, indent=2))
                return 0 if record['status'] in {'completed', 'needs_clarification'} else 1
            if time.monotonic() >= deadline:
                raise RuntimeError(f"POLL_TIMEOUT: retain request UUID {request['id']}; no automatic retry")
            time.sleep(1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv')
    parser.add_argument('question')
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    args = parser.parse_args(argv)
    try:
        return demo(args.csv, args.question, base_url=args.base_url)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
    except (OSError, ValueError, httpx.HTTPError):
        print('DEMO_FAILED: check local API, file and configuration; no automatic retry', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
