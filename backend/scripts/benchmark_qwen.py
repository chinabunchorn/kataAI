"""Probe actual local Qwen. Code is captured as text and NEVER locally executed."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import time

from app.model_adapter import LocalModelAdapter, ModelTextOnlyOutcome, RUNNER_CONTRACT


class RecordingModel(LocalModelAdapter):
    def _http(self, payload):
        response = super()._http(payload)
        self.response = response
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--endpoint', default='http://127.0.0.1:8080/v1/chat/completions')
    parser.add_argument('--model', default='Qwen3.5-9B-Q4_K_M')
    args = parser.parse_args()
    fixture = Path(__file__).resolve().parents[1] / 'tests/fixtures/qwen_mvp'
    with (fixture / 'sales.csv').open(encoding='utf-8-sig', newline='') as stream:
        columns = next(csv.reader(stream))
    cases = json.loads((fixture / 'cases.json').read_text())
    model = RecordingModel(args.endpoint, model=args.model)
    results = {'prompt': RUNNER_CONTRACT, 'prompt_sha256': hashlib.sha256(RUNNER_CONTRACT.encode()).hexdigest(),
               'model': args.model, 'generated_code_executed': False, 'cases': []}
    for case in cases:
        model.response = None
        start = time.monotonic()
        record = {'id': case['id'], 'question': case['question'], 'expected_kind': case['expected_kind']}
        try:
            record['proposal'] = model.generate(case['question'], columns)
            record['kind'] = 'proposal'
        except ModelTextOnlyOutcome as outcome:
            record.update(kind='clarification', text=outcome.text)
        except Exception:
            record.update(kind='error', error='MODEL_ADAPTER_FAILED')
        record.update(seconds=round(time.monotonic()-start, 3), raw_response=model.response)
        results['cases'].append(record)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
        print(f"{case['id']}: {record['kind']} in {record['seconds']}s; computation unverified", flush=True)


if __name__ == '__main__':
    main()
