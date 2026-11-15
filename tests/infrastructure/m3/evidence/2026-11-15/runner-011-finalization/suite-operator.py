"""Operator orchestration: executes only the existing trusted Kata harness."""
import concurrent.futures
import datetime
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
EV = ROOT / '.m3-runs/runner-011-finalization'
sys.path.insert(0, str(ROOT / 'tests/infrastructure/m3'))
from catalog import CASES

IMAGE = 'docker.io/kataai/runner@sha256:6a682ed00f47fc27c18eb3abd9e3448960133433265ec6442339c9484d246bf9'

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def save(name, value):
    (EV / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

def ssh(command):
    p = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', 'katavm', command], capture_output=True, text=True, timeout=30)
    return {'at': now(), 'command': command, 'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}

def observe_security(run):
    observations = []
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        snapshot = ssh(f'kubectl -n kata-lab get pods -l kataai-m3-run={run} -o json')
        observations.append(snapshot)
        pods = json.loads(snapshot['stdout']).get('items', []) if snapshot['returncode'] == 0 else []
        if pods and pods[0].get('status', {}).get('phase') == 'Running':
            pod = pods[0]
            snapshot = ssh('sudo -n ctr -n k8s.io sandboxes ls; ps -eo pid,ppid,lstart,args | grep -E "[q]emu-system|[c]ontainerd-shim-kata"')
            observations.append(snapshot)
            kata = [line.split()[0] for line in snapshot['stdout'].splitlines() if 'io.containerd.kata-qemu-runtime-rs.v2' in line]
            infos = [ssh(f'sudo -n ctr -n k8s.io sandboxes info {sid}') for sid in kata]
            observations.extend(infos)
            save('security-live.json', {'run_id': run, 'pod': pod, 'observations': observations})
            return {'pod_uid': pod['metadata']['uid'], 'sandboxes': kata, 'observations': observations}
        if pods and pods[0].get('status', {}).get('phase') in ('Succeeded', 'Failed'):
            break
        time.sleep(0.4)
    save('security-live.json', {'run_id': run, 'observations': observations, 'error': 'No live Running Pod correlation captured'})
    return None

previous = EV / 'suite-execution.json'
results = json.loads(previous.read_bytes())['cases'] if previous.exists() else []
order = ['security'] + [name for name in CASES if name != 'security']
for index, case in enumerate(order):
    if any(row['case'] == case for row in results):
        continue
    run = f'm3-011-{case}-1115a'
    args = [sys.executable, '-B', str(ROOT / 'tests/infrastructure/m3/run.py'), '--case', case, '--run-id', run, '--image', IMAGE, '--execute', '--ssh-host', 'katavm']
    start = now()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        observer = pool.submit(observe_security, run) if case == 'security' else None
        p = subprocess.run(args, capture_output=True, text=True, timeout=300, cwd=ROOT)
        correlation = observer.result() if observer else None
    (EV / f'{case}-harness.txt').write_text(p.stdout + p.stderr, encoding='utf-8')
    record = {'case': case, 'run_id': run, 'start': start, 'end': now(), 'returncode': p.returncode}
    pod_file = ROOT / '.m3-runs' / run / 'pods.json'
    pods = json.loads(pod_file.read_bytes()).get('items', []) if pod_file.exists() else []
    checks = 'date -u; sudo -n ctr -n k8s.io sandboxes ls; ps -eo pid,ppid,lstart,args | grep -E "[q]emu-system|[c]ontainerd-shim-kata" || true'
    for pod in pods:
        uid = pod['metadata']['uid']
        checks += f'; sudo -n test ! -e /var/lib/kubelet/pods/{uid}; echo kubelet_{uid}_absent=$?'
    if correlation:
        for sid in correlation['sandboxes']:
            checks += f'; sudo -n ctr -n k8s.io sandboxes info {sid}; sudo -n test ! -e /run/vc/vm/{sid}; echo kata_vm_{sid}_absent=$?; sudo -n test ! -e /run/kata-containers/{sid}; echo kata_run_{sid}_absent=$?'
    record['node_cleanup'] = ssh(checks)
    save(f'{case}-node-cleanup.json', record['node_cleanup'])
    results.append(record)
    save('suite-execution.json', {'image': IMAGE, 'cases': results})
    print(f'{index + 1}/{len(order)} {case}: exit={p.returncode}', flush=True)
    if p.returncode:
        print(p.stdout + p.stderr, flush=True)
        raise SystemExit('Stopped after failure; preserve evidence and investigate before retry')
    if '/opt/kata/bin/qemu' in record['node_cleanup']['stdout'] or '/opt/kata/runtime-rs/bin/containerd-shim-kata' in record['node_cleanup']['stdout']:
        raise SystemExit('Kata guest process remains; investigate before next case')
print('All active trusted cases completed', flush=True)
