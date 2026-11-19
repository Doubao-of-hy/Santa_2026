"""Deterministic parallel arithmetic synthesis with independent replay validation.
SPDX-License-Identifier: Apache-2.0
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import time


def replay(row, program):
    assert isinstance(program, list) and len(program) <= 4096
    assert len(json.dumps(program, separators=(',', ':')).encode()) <= 131072
    bank = [None] * int(row['registers'])
    starts = json.loads(row['starting_values'])
    bank[:len(starts)] = starts
    missing = set(json.loads(row['targets'])) - set(starts)
    for instruction in program:
        assert isinstance(instruction, list) and len(instruction) == 4
        op, i, j, k = instruction
        assert all(type(x) is int and 0 <= x < len(bank) for x in (i, j, k))
        a, b = bank[i], bank[j]
        assert a is not None and b is not None
        if op == '+':
            v = a + b
        elif op == '-':
            v = a - b
        elif op == '*':
            v = a * b
        else:
            assert op == '/' and a % b == 0
            v = a // b
        assert 0 < v <= int(row['value_limit'])
        bank[k] = v
        missing.discard(v)
    assert not missing
    return len(program)


def work(args):
    row, binary, config, trace = args
    starts, targets = json.loads(row['starting_values']), json.loads(row['targets'])
    payload = ' '.join(map(str, [row['id'], row['value_limit'], len(starts), len(targets), *starts, *targets]))
    if trace is not None:
        program = json.loads(trace)
        payload += ' ' + str(len(program)) + ' ' + ' '.join(str(x) for ins in program for x in ins)
    result = subprocess.run([binary, *config], input=payload, capture_output=True, text=True, check=True)
    pid, raw = result.stdout.strip().split(' ', 1)
    assert pid == row['id']
    n = replay(row, json.loads(raw))
    return pid, raw, n


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--puzzles', default='/task/data/puzzles.csv')
    p.add_argument('--output', required=True)
    p.add_argument('--config', nargs='+', default=['4', '72', '0.18', '0', '0'])
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--count', type=int, default=0)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--source', default='recovered/solver.cpp')
    p.add_argument('--trace', help='Own previously validated programs for graph postprocessing')
    a = p.parse_args()
    root = Path(__file__).resolve().parent
    source = (root / a.source).resolve()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    dependencies = {str(source.relative_to(root)): source_hash}
    for name in ['recovered/solver.cpp', 'solver_v3.cpp', 'solver_fast.cpp']:
        dep = root / name
        if dep.exists(): dependencies[name] = hashlib.sha256(dep.read_bytes()).hexdigest()
    build_hash = hashlib.sha256(json.dumps(dependencies, sort_keys=True).encode()).hexdigest()
    binary = root / ('solver_' + build_hash[:12])
    # Compile to a process-specific temporary path, then atomically replace.
    # Parallel experiment launches must never execute a half-written binary.
    import os
    temporary_binary = root / (binary.name + '.tmp.' + str(os.getpid()))
    subprocess.run(['g++', '-std=c++17', '-O3', str(source), '-o', str(temporary_binary)], check=True)
    temporary_binary.replace(binary)
    rows = list(csv.DictReader(open(a.puzzles)))
    if a.count:
        rows = rows[:a.count]
    start = time.time()
    restored = {}
    if a.resume and Path(a.output).exists():
        for r in csv.DictReader(open(a.output)):
            restored[r['id']] = r['program']
    remaining = [r for r in rows if r['id'] not in restored]
    traces = {r['id']: r['program'] for r in csv.DictReader(open(a.trace))} if a.trace else {}
    report = {'config': a.config, 'puzzles': len(rows), 'instructions': 0, 'by_family': {},
              'source_sha256': source_hash, 'source': a.source,
              'build_dependencies': dependencies,
              'base_source_sha256': hashlib.sha256((root / 'recovered/solver.cpp').read_bytes()).hexdigest(),
              'trace_sha256': hashlib.sha256(Path(a.trace).read_bytes()).hexdigest() if a.trace else None}
    with open(a.output, 'w') as f, ProcessPoolExecutor(a.workers) as pool:
        writer = csv.writer(f)
        writer.writerow(['id', 'program'])
        results = pool.map(work, [(r, str(binary), a.config, traces.get(r['id'])) for r in remaining])
        for i, row in enumerate(rows):
            if row['id'] in restored:
                pid, raw = row['id'], restored[row['id']]
                n = replay(row, json.loads(raw))
            else:
                pid, raw, n = next(results)
            writer.writerow([pid, raw]); f.flush()
            report['instructions'] += n
            family = rows[i].get('family', 'scored')
            report['by_family'][family] = report['by_family'].get(family, 0) + n
            if (i + 1) % 20 == 0:
                print(i + 1, report['instructions'], round(time.time() - start, 1), flush=True)
    report['seconds'] = time.time() - start
    Path(a.output).with_suffix('.report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
