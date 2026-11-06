#!/usr/bin/env python3
"""IAM/timing batch over existing packaged-app Runtime/Invoke infrastructure.

Actual gateway SDK + running backend proof. IAM and Lambda platform termination
are explicitly simulated locally, never reported as AWS qualification.
"""
import argparse
import copy
import json
from pathlib import Path
import threading
import time
import uuid

from integration import (Runtime, InvokeBridge, configure, environment, unpack,
                         JAVA_ZIP, RUST_ZIP, candidate_pins)
from run import ARTIFACTS, REPO, HERE, digest, event, read, write

CONTRACT = HERE / 'timing-v1.json'
TEMPLATE = ARTIFACTS / 'parity-received-aws-20261023T001101Z/aws-final/scope'


class PlatformBound:
    """Test-only Lambda timeout emulator; kills AND reaps actual synthetic backend.

    The returned platform error bytes are labelled simulated. Successful response
    bytes always come from the actual backend Runtime API, unchanged.
    """
    def __init__(self, runtime, timeout_ms):
        self.runtime, self.timeout_ms = runtime, timeout_ms
        self.closed = None
        self.boundaries = []

    def submit(self, payload, ident):
        box = {}
        done = threading.Event()
        def invoke():
            try:
                box['result'] = self.runtime.submit(payload, ident)
            except BaseException as error:
                box['error'] = type(error).__name__
            finally:
                done.set()
        thread = threading.Thread(target=invoke, daemon=True)
        started = time.monotonic()
        thread.start()
        if done.wait(self.timeout_ms / 1000):
            if 'error' in box:
                raise RuntimeError(box['error'])
            return box['result']
        self.closed = self.runtime.close()
        thread.join(timeout=3)
        assert not thread.is_alive() and self.closed['reaped']
        self.boundaries.append({'executionRequestId': ident, 'elapsedMs': round((time.monotonic() - started) * 1000),
                                'boundary': 'simulated-Lambda-platform-timeout', 'cleanup': self.closed})
        return {'kind': 'error', 'payload': b'{"errorType":"Sandbox.Timedout","errorMessage":"Task timed out after 4.00 seconds"}'}

    def close(self):
        if self.closed is None:
            self.closed = self.runtime.close()
        return self.closed


def check_response(side, step, response):
    contract = read(CONTRACT)
    failure = step.get('failure')
    expected = contract['expectations'][side][failure] if failure else {'status': 200}
    errors = []
    if response.get('statusCode') != expected['status']:
        errors.append({'field': 'status', 'expected': expected['status'], 'actual': response.get('statusCode')})
    body = response.get('body')
    if failure:
        try:
            code = json.loads(body)['code']
        except (ValueError, TypeError, KeyError):
            code = None
        if code != expected['code']:
            errors.append({'field': 'code', 'expected': expected['code'], 'actual': code})
        for private in ['synthetic denial', 'Sandbox.Timedout', 'Task timed out', 'private-canary']:
            if private in json.dumps(response):
                errors.append({'field': 'privacy', 'leaked': private})
    else:
        wanted = '{"result":"delayed"}' if step['target'] == 'delay' else ''
        if body != wanted:
            errors.append({'field': 'body', 'expected': wanted, 'actual': body})
    if response.get('isBase64Encoded') is not False:
        errors.append({'field': 'isBase64Encoded', 'expected': False, 'actual': response.get('isBase64Encoded')})
    headers = {k.lower(): v for k, v in (response.get('headers') or {}).items()}
    headers.update({k.lower(): values[-1] for k, values in (response.get('multiValueHeaders') or {}).items()})
    if headers.get('content-type') != 'application/json':
        errors.append({'field': 'content-type', 'actual': headers})
    return errors


def run(args):
    pins = candidate_pins(args)
    out = args.out.resolve()
    assert out.is_relative_to(ARTIFACTS.resolve())
    out.mkdir(parents=True, exist_ok=False)
    contract = read(CONTRACT)
    write(out / 'declared-contract.json', contract)
    write(out / 'pre-execution-identities.json', {'contractSha256': digest(CONTRACT),
          'backendBinarySha256': digest(args.backend_binary), 'gatewayZipSha256': pins,
          'timingDeclaredBeforeExecution': True, 'awsCalls': 0})
    runtimes, bridges, cleanups, rows, errors, all_calls, boundary_records = [], [], [], [], [], [], []
    run_id = uuid.uuid4().hex
    try:
        for side, archive in [('java', args.java_zip), ('rust', RUST_ZIP)]:
            unpack(archive, out / (side + '-package'), side, pins)
        # Reuse already preserved real-Init configuration, adapting only targets
        # and explicit profile timeout settings in a separate directory.
        fixture_path = read(TEMPLATE / 'event-plan.json')['events'][0]['expectationFixture']
        sample = read(Path(fixture_path))
        for side in ['java', 'rust']:
            side_out = out / side
            side_out.mkdir()
            backends = {}
            for name in ['echo-a', 'denied', 'delay']:
                rt = Runtime(side + '-' + name, out)
                env = dict(environment(), PARITY_BACKEND_IDENTITY=name)
                if name == 'delay':
                    env['PARITY_BACKEND_TIMING'] = 'bounded-v1'
                rt.start([args.backend_binary], env, out)
                backend = PlatformBound(rt, contract['limits']['backendLambdaTimeoutMs'])
                runtimes.append(backend)
                backends['parity-' + name] = backend
            bridge = InvokeBridge(backends, denied_targets={'parity-denied'})
            bridges.append(bridge)
            for profile in ['fast', 'patient']:
                profile_out = side_out / profile
                profile_out.mkdir()
                configured = copy.deepcopy(sample)
                configured['config']['files']['lambda-proxy']['functions'] = {
                    '/parity/a@post': 'parity-echo-a', '/parity/denied@post': 'parity-denied',
                    '/parity/delay@post': 'parity-delay'}
                timeout = contract['limits'][profile + 'ApiCallTimeoutMs']
                if side == 'rust' and profile == 'fast':
                    # Exercise the real request deadline, not an earlier SDK cap.
                    timeout = contract['limits']['rustFastSdkTimeoutMs']
                    configured['config']['values'].update({
                        'light-lambda.ingressTimeoutMs': contract['limits']['rustFastIngressTimeoutMs'],
                        'light-lambda.responseReserveMs': contract['limits']['rustResponseReserveMs'],
                        'light-lambda.postReserveMs': contract['limits']['rustPostReserveMs']})
                java_cfg, rust_cfg = configure(args, profile_out, configured,
                    f'http://127.0.0.1:{bridge.server.server_port}', out / 'rust-package/bootstrap',
                    proxy_settings={'apiCallTimeout': timeout, 'apiCallAttemptTimeout': timeout,
                                    'readTimeout': 15000, 'writeTimeout': 15000, 'connectionTimeout': 1000})
                rt = Runtime(side + '-' + profile + '-gateway', out)
                runtimes.append(rt)
                env = environment()
                env['_HANDLER'] = 'com.networknt.aws.lambda.app.LambdaApp::handleRequest'
                if side == 'java':
                    command = [out / 'java-package/lambda-native', '-Dlight-4j-config-dir=' + str(java_cfg),
                               '-Dlogback.configurationFile=' + str(java_cfg / 'logback.xml')]
                else:
                    command = [out / 'rust-package/bootstrap']
                    env.update(LIGHT_LAMBDA_CONFIG_DIR=str(rust_cfg), LIGHT_LAMBDA_ALLOW_INSECURE_TEST_ENDPOINTS='1',
                               LIGHT_LAMBDA_GATEWAY_ARN='arn:aws:lambda:us-east-1:000000000000:function:' + rt.name)
                rt.start(command, env, out)
                # Untimed priming is reported separately; it isolates cold SDK
                # setup from declared service timing, without retrying any case.
                prime = event({'mode': 'empty', 'path': '/parity/a'}, 'TIMING-prime', side + '-' + uuid.uuid4().hex, run_id)
                result = rt.submit(prime)
                prime_response = json.loads(result['payload'])
                assert result['kind'] == 'response' and not check_response(side, {'target': 'echo-a'}, prime_response)
                write(profile_out / 'prime.json', {'requestId': result['id'], 'response': prime_response})
                for case in [c for c in contract['cases'] if c['profile'] == profile]:
                    for index, step in enumerate(case['steps']):
                        attempt = side + '-' + uuid.uuid4().hex
                        path = {'echo-a': '/parity/a', 'denied': '/parity/denied', 'delay': '/parity/delay'}[step['target']]
                        raw = event({'mode': step['mode'], 'path': path}, case['id'], attempt, run_id)
                        write(profile_out / f'{case["id"]}-{index}-event.json', raw)
                        started = time.monotonic()
                        result = rt.submit(raw)
                        returned = time.monotonic()
                        response = json.loads(result['payload'])
                        failures = check_response(side, step, response)
                        if result['kind'] != 'response':
                            failures.append({'field': 'outerRuntimeOutcome', 'actual': result['kind']})
                        elapsed = round((returned - started) * 1000)
                        bounds = contract['timingMs'].get(step.get('failure', step['mode']), contract['timingMs']['success'])
                        if not bounds[0] <= elapsed <= bounds[1]:
                            failures.append({'field': 'elapsedMs', 'expected': bounds, 'actual': elapsed})
                        calls = [c for c in bridge.calls if c['event']['multiValueHeaders']['x-parity-attempt'] == [attempt]]
                        if len(calls) != 1 or calls[0]['target'] != 'parity-' + step['target']:
                            failures.append({'field': 'InvokeAttempts', 'actual': calls})
                        row = {'side': side, 'case': case['id'], 'step': index, 'profile': profile,
                               'mode': step['mode'], 'target': step['target'], 'attemptId': attempt,
                               'gatewayRequestId': result['id'], 'gatewayPid': rt.process.pid,
                               'startedMonotonic': started, 'returnedMonotonic': returned,
                               'elapsedMs': elapsed, 'timingBoundsMs': bounds, 'response': response,
                               'passed': not failures, 'errors': failures}
                        rows.append(row)
                        write(profile_out / f'{case["id"]}-{index}-result.json', row)
                # Require late backend success before moving to the platform
                # timeout profile. Never turn a missing completion into a pass.
                if profile == 'fast':
                    limit = time.monotonic() + 6
                    while any('backendResultKind' not in c and c['target'] != 'parity-denied' for c in bridge.calls):
                        assert time.monotonic() < limit, 'late backend completion missing'
                        time.sleep(0.02)
            all_calls.extend(bridge.calls)
            assert not bridge.errors, bridge.errors
            boundary_records.extend(backends['parity-delay'].boundaries)
        for wrapped in runtimes:
            rt = wrapped.runtime if isinstance(wrapped, PlatformBound) else wrapped
            rt.log.flush() if not rt.log.closed else None
        records = []
        for path in out.glob('*.log'):
            for line in path.read_text().splitlines():
                if line.startswith('{'):
                    try:
                        record = json.loads(line)
                        if record.get('schema') == 'parity-execution/v1':
                            records.append(record)
                    except ValueError:
                        pass
        entries = [r for r in records if r.get('phase') == 'entry']
        done = [r for r in records if r.get('phase') == 'completion']
        assert len(entries) == len({r['executionRequestId'] for r in entries}) == 20  # includes four priming controls
        assert len(done) == len({r['executionRequestId'] for r in done}) == 18
        for row in rows:
            actual = [r for r in entries if r['attemptId'] == row['attemptId']]
            completed = [r for r in done if r['attemptId'] == row['attemptId']]
            assert len(actual) == (0 if row['target'] == 'denied' else 1)
            assert len(completed) == (0 if row['target'] == 'denied' or row['mode'] == 'lambda-timeout' else 1)
            if row['mode'] == 'deadline-delay':
                call = next(c for c in all_calls if c['event']['multiValueHeaders']['x-parity-attempt'] == [row['attemptId']])
                late = round((call['backendFinishedMonotonic'] - call['sdkReceivedMonotonic']) * 1000)
                assert contract['timingMs']['lateCompletion'][0] <= late <= contract['timingMs']['lateCompletion'][1]
                assert call['backendFinishedMonotonic'] > row['returnedMonotonic']
                row['lateBackendCompletionMs'] = late
        assert len(boundary_records) == 2 and all(r['cleanup']['reaped'] for r in boundary_records)
        assert len(all_calls) == 22 and all(c['signed'] and c['invoke']['logType'] == 'None' for c in all_calls)
        write(out / 'invoke-transport.json', all_calls)
        write(out / 'backend-records.json', records)
        write(out / 'platform-simulation.json', boundary_records)
        green = all(r['passed'] for r in rows)
        report = {'schema': 'parity-iam-timing-local/v1', 'green': green, 'awsCalls': 0,
                  'gatewaySteps': len(rows), 'gatewayExpectationPasses': sum(r['passed'] for r in rows),
                  'primingRequests': 4, 'invokeAttemptsIncludingPriming': len(all_calls),
                  'backendEntriesIncludingPriming': len(entries), 'backendCompletionsIncludingPriming': len(done),
                  'selectedBackendEntries': 16, 'selectedBackendCompletions': 14,
                  'IAM': 'HTTP403 owned simulation; not AWS IAM proof',
                  'LambdaTimeout': 'platform termination owned simulation; not AWS platform proof',
                  'actualExecution': 'unchanged packaged Java/Rust Init/service/SDK into real synthetic backend processes',
                  'SDKWire': 'outside this batch', 'JWKS': 'outside proxy-only profile',
                  'contractSha256': digest(CONTRACT), 'backendBinarySha256': digest(args.backend_binary),
                  'gatewayZipSha256': pins, 'rows': rows}
        write(out / 'report.json', report)
        print(json.dumps({k: v for k, v in report.items() if k != 'rows'}))
        return 0 if green else 1
    except BaseException as error:
        write(out / 'failure.json', {'kind': type(error).__name__, 'message': str(error)})
        write(out / 'partial-results.json', rows)
        write(out / 'partial-invokes.json', [c for b in bridges for c in b.calls])
        raise
    finally:
        for runtime in reversed(runtimes):
            cleanups.append(runtime.close())
        for bridge in bridges:
            bridge.close()
        write(out / 'cleanup.json', cleanups)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--fabric', type=Path, default=REPO.parent / 'light-fabric-light-lambda')
    parser.add_argument('--backend-binary', type=Path, default=REPO / 'target/x86_64-unknown-linux-musl/release/lambda-trial-backend')
    parser.add_argument('--java-zip', type=Path, default=JAVA_ZIP)
    parser.add_argument('--candidate-manifest', type=Path)
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
