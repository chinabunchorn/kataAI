"""Opt-in local-model demo. Generated code is inert; execution is fake only.

Configure DATABASE_URL and KATAAI_DATASET_ROOT explicitly as for the dataset
runtime. This worker uses the shared session lock and never starts a server.
Model summaries are disabled: the preset is not an answer to the question.
"""
import argparse
import sys

from .dataset_runtime import load_dataset_runtime
from .fake_worker import run_once
from .model_adapter import LocalModelAdapter
from .phase6_processor import process_claim
from .request_queue import RequestQueue


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # Argument values can contain credentials or other sensitive data.
        self.exit(2, 'Invalid arguments; use --help for usage.\n')


class _GenerationOnly:
    def __init__(self, model):
        self._model = model

    def generate(self, question, columns):
        return self._model.generate(question, columns)

    def summarize(self, question, result):
        return result, None, 'SUMMARY_UNAVAILABLE'


def _process(connection, root, claim, model):
    result = process_claim(connection, root, claim, model=_GenerationOnly(model))
    result['warning'] = 'FAKE_PRESET_NOT_AN_ANSWER'
    return result


def main(argv=None):
    parser = _SafeParser(description='Process at most one request with a local model and fake executor only.')
    parser.add_argument('--once', action='store_true', required=True)
    parser.add_argument('--model-endpoint', required=True, help='http://127.0.0.1:PORT/v1/chat/completions')
    parser.add_argument('--model', default='local-model', help='Local model identifier')
    args = parser.parse_args(argv)
    try:
        model = LocalModelAdapter(args.model_endpoint, model=args.model)
        runtime = load_dataset_runtime()
        with runtime.connection() as connection:
            outcome = run_once(connection, RequestQueue, processor=lambda claim: _process(
                connection, runtime.root, claim, model))
        print(f'FAKE_ONLY: {outcome}; preset result is not a real answer')
        return 0
    except Exception:
        print('QWEN_FAKE_WORKER_FAILED: outcome may be uncertain; no retry', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
