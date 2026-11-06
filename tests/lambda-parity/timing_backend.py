#!/usr/bin/env python3
"""Direct real-backend timing controls, with explicitly simulated platform timeout."""
import argparse
import json
from pathlib import Path
import time
import uuid

from integration import Runtime, environment
from timing_integration import PlatformBound
from run import ARTIFACTS, REPO, HERE, read, write, event, digest


def run(args):
    out = args.out.resolve()
    assert out.is_relative_to(ARTIFACTS.resolve())
    out.mkdir(parents=True, exist_ok=False)
    c = read(HERE / 'timing-v1.json')
    write(out / 'declared-contract.json', c)
    rows, managed, cleanup = [], [], []
    try:
        for name, profile, modes in [
            ('denied', None, [('empty', 200)]),
            ('delay', None, [('delay-success', 400)]),
            ('delay', 'bounded-v1', [('unknown', 400), ('duplicate', 400), ('delay-success', 200),
                                     ('deadline-delay', 200), ('lambda-timeout', None)])]:
            rt = Runtime(name + '-' + str(len(managed)), out)
            env = dict(environment(), PARITY_BACKEND_IDENTITY=name)
            if profile:
                env['PARITY_BACKEND_TIMING'] = profile
            rt.start([args.binary], env, out)
            bounded = PlatformBound(rt, 4000)
            managed.append(bounded)
            for mode, expected in modes:
                raw = event({'mode': 'delay-success' if mode == 'duplicate' else mode}, 'TIMING-direct', uuid.uuid4().hex)
                if mode == 'duplicate':
                    raw['headers'] = {'X-Parity-Case': 'deadline-delay'}
                started = time.monotonic()
                result = bounded.submit(raw, 'execution-' + uuid.uuid4().hex)
                ms = round((time.monotonic() - started) * 1000)
                payload = json.loads(result['payload'])
                if expected is None:
                    assert result['kind'] == 'error' and payload['errorType'] == 'Sandbox.Timedout'
                    assert bounded.closed['reaped'] and 3500 <= ms <= 7000
                else:
                    assert result['kind'] == 'response' and payload['statusCode'] == expected
                    if expected == 400:
                        assert ms < 2000 and payload['body'] == '{"code":"PARITY_INVALID_CONTROL"}'
                    if expected == 200 and name == 'delay':
                        assert payload['body'] == '{"result":"delayed"}'
                        floor = c['fixedDelaysMs'][mode] - 50
                        assert floor <= ms <= floor + 2000
                rows.append({'identity': name, 'profile': profile, 'mode': mode, 'elapsedMs': ms,
                             'kind': result['kind'], 'payload': payload, 'passed': True})
        write(out / 'report.json', {'green': True, 'requests': len(rows), 'passes': len(rows),
              'awsCalls': 0, 'platformTimeout': 'owned simulation; actual child killed and reaped',
              'backendSha256': digest(args.binary), 'rows': rows})
        print(json.dumps({'green': True, 'passes': len(rows), 'requests': len(rows)}))
    except BaseException as error:
        write(out / 'failure.json', {'kind': type(error).__name__, 'message': str(error), 'rows': rows})
        raise
    finally:
        for backend in reversed(managed):
            cleanup.append(backend.close())
        write(out / 'cleanup.json', cleanup)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--binary', type=Path, default=REPO / 'target/x86_64-unknown-linux-musl/release/lambda-trial-backend')
    run(parser.parse_args())
