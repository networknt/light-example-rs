#!/usr/bin/env python3
"""Real gateway SDK -> owned Invoke HTTP -> running backend Runtime API.

Reuses run.py cases/fixtures and the existing packaged-app Runtime API pattern.
The Invoke bridge passes actual backend bytes; it never constructs replies.
"""
import argparse
import base64
import copy
import http.server
import importlib.util
import json
import os
from pathlib import Path
import queue
import signal
import shutil
import subprocess
import threading
import time
import uuid
from urllib.parse import unquote
import zipfile

from run import ARTIFACTS, HERE, REPO, digest, event, execute, inventory, prepare, read, write
from received_observations import compare as compare_received

RUST_ZIP = ARTIFACTS / 'WP13-D08e-release-20261021T155728Z/release-package/bootstrap.zip'
JAVA_ZIP = ARTIFACTS / 'WP17-java-netty-20261022T204215Z/java-native-netty-query-candidate.zip'
JAVA_CONFIG = ARTIFACTS / 'WP17-java-dev-trust-20261022T195603Z/java-dev-trust-config.zip'
JAVA_CONFIG_SHA = 'd681bfb2540c7c9b28688399f79014479c7e1ab41c10f62f0e36b6deac5d5129'
PINNED = {'rust': 'd095e89c07f6079823d6d07395b8716f280add5e7e09f7a75b1d03e121af756a',
          'java': '35122e39cb39fa9d0ddc433517d560cac014421a158c37c13fac8148d3f277e7'}
LIMIT = 128 * 1024


def environment():
    # Never inherit real credentials, profiles or proxy routes into owned tests.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AWS_', 'LIGHT_LAMBDA_'))
           and k.lower() not in ['http_proxy', 'https_proxy', 'all_proxy']
           and k not in ['PARITY_BACKEND_OBSERVATIONS', 'PARITY_BACKEND_TIMING']}
    env.update(AWS_REGION='us-east-1', AWS_DEFAULT_REGION='us-east-1',
               AWS_ACCESS_KEY_ID='synthetic', AWS_SECRET_ACCESS_KEY='synthetic',
               AWS_EC2_METADATA_DISABLED='true', AWS_LAMBDA_FUNCTION_MEMORY_SIZE='128')
    return env


def candidate_pins(args):
    """Explicit opt-in candidate; accepted default pins are never replaced."""
    path = getattr(args, 'candidate_manifest', None)
    if path is None:
        return dict(PINNED)
    candidate = read(path)
    if (candidate.get('schema') != 'parity-local-candidate/v1'
            or candidate.get('acceptedZipSha256') != PINNED['java']
            or candidate.get('approvedPatchSha256') not in {
                'f9f14577063c94b5784daee4d7252897fc6baf1d71148bf48aed0e872a4a37fa',
                '0e1483723185d6210712c0d121e545ed7d7ae1f2a95090c34a412aeae60b5d96'}
            or Path(candidate['zip']).resolve() != args.java_zip.resolve()
            or digest(args.java_zip) != candidate['zipSha256']):
        raise ValueError('candidate manifest or approved artifact drift')
    if candidate.get('approvedPatchSha256') == '0e1483723185d6210712c0d121e545ed7d7ae1f2a95090c34a412aeae60b5d96':
        if (candidate.get('baseCandidateZipSha256') != '923ea10b515c85a904336345a1b71d5138a6f0a1612b2785ca32ecfa89a7728d'
                or candidate.get('approvedPatchChain') != [
                    'f9f14577063c94b5784daee4d7252897fc6baf1d71148bf48aed0e872a4a37fa',
                    '0e1483723185d6210712c0d121e545ed7d7ae1f2a95090c34a412aeae60b5d96']):
            raise ValueError('candidate patch provenance drift')
    if digest(JAVA_ZIP) != PINNED['java']:
        raise ValueError('accepted Java artifact drift')
    with zipfile.ZipFile(JAVA_ZIP) as accepted, zipfile.ZipFile(args.java_zip) as proposed:
        if proposed.read('bootstrap') != accepted.read('bootstrap'):
            raise ValueError('candidate bootstrap changed')
        import hashlib
        if hashlib.sha256(proposed.read('lambda-native')).hexdigest() != candidate['binarySha256']:
            raise ValueError('candidate native binary drift')
    return dict(PINNED, java=candidate['zipSha256'])


def unpack(archive, directory, side, pins=None):
    if digest(archive) != (pins or PINNED)[side]:
        raise ValueError('pinned gateway ZIP drift: ' + side)
    directory.mkdir()
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if set(names) != ({'bootstrap'} if side == 'rust' else {'bootstrap', 'lambda-native'}):
            raise ValueError('unexpected package layout')
        for name in names:
            path = directory / name
            path.write_bytes(z.read(name))
            path.chmod(0o755)


class Runtime:
    """Owned serial Runtime API; actual executable returns response/error bytes."""
    def __init__(self, name, out):
        self.name, self.out = name, out
        self.jobs = queue.Queue()
        self.pending = {}
        self.stopping = threading.Event()
        self.results = []
        self.fatal = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *unused):
                pass

            def do_GET(self):
                if self.path != '/2018-06-01/runtime/invocation/next':
                    self.send_error(404)
                    return
                while not owner.stopping.is_set():
                    try:
                        job = owner.jobs.get(timeout=0.1)
                        break
                    except queue.Empty:
                        continue
                else:
                    self.close_connection = True
                    return
                data = json.dumps(job['event'], ensure_ascii=False, separators=(',', ':')).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Lambda-Runtime-Aws-Request-Id', job['id'])
                self.send_header('Lambda-Runtime-Deadline-Ms', str(int(time.time() * 1000) + 15000))
                self.send_header('Lambda-Runtime-Invoked-Function-Arn',
                                 f'arn:aws:lambda:us-east-1:000000000000:function:{owner.name}:1')
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 <= size <= LIMIT:
                    self.send_error(413)
                    return
                body = self.rfile.read(size)
                parts = self.path.split('/')
                if self.path == '/2018-06-01/runtime/init/error':
                    owner.fatal.append(body.decode())
                elif len(parts) == 6 and parts[3] == 'invocation' and parts[5] in ['response', 'error']:
                    job = owner.pending.get(parts[4])
                    if job is None or job['done'].is_set():
                        self.send_error(409)
                        return
                    job.update(payload=body, kind=parts[5])
                    owner.results.append({'requestId': job['id'], 'kind': job['kind'],
                                          'payloadBase64': base64.b64encode(body).decode()})
                    job['done'].set()
                else:
                    self.send_error(404)
                    return
                self.send_response(202)
                self.send_header('Content-Length', '0')
                self.end_headers()

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.process = None

    def start(self, command, env, cwd):
        env = dict(env, AWS_LAMBDA_RUNTIME_API=f'127.0.0.1:{self.server.server_port}',
                   AWS_LAMBDA_FUNCTION_NAME=self.name, AWS_LAMBDA_FUNCTION_VERSION='1')
        self.log = (self.out / (self.name + '.log')).open('x')
        self.process = subprocess.Popen(list(map(str, command)), cwd=cwd, env=env,
                                        stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        self.command = list(map(str, command))

    def submit(self, value, request_id=None):
        ident = request_id or 'execution-' + uuid.uuid4().hex
        if ident in self.pending:
            raise ValueError('duplicate execution identity')
        job = {'id': ident, 'event': copy.deepcopy(value), 'done': threading.Event()}
        self.pending[ident] = job
        self.jobs.put(job)
        deadline = time.monotonic() + 20
        while not job['done'].wait(0.1):
            if self.fatal or self.process.poll() is not None:
                raise RuntimeError('runtime failed; inspect ' + self.name + '.log')
            if time.monotonic() > deadline:
                raise TimeoutError('runtime execution timed out; no retry: ' + self.name)
        return job

    def close(self):
        if self.process:
            if self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=3)
            self.log.close()
        self.stopping.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        write(self.out / (self.name + '-runtime-results.json'), {'responses': self.results, 'initErrors': self.fatal})
        return {'name': self.name, 'pid': self.process.pid if self.process else None,
                'exitCode': self.process.returncode if self.process else None,
                'reaped': self.process is not None and self.process.returncode is not None,
                'command': getattr(self, 'command', []), 'runtimeResponses': len(self.results)}


class InvokeBridge:
    def __init__(self, backends, denied_targets=()):
        self.calls = []
        self.errors = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *unused):
                pass

            def do_POST(self):
                try:
                    parts = self.path.split('/')
                    if len(parts) != 5 or parts[:3] != ['', '2015-03-31', 'functions'] or parts[4] != 'invocations':
                        raise ValueError('unexpected Invoke route')
                    target = unquote(parts[3])
                    if target not in backends:
                        raise ValueError('unconfigured target')
                    size = int(self.headers['Content-Length'])
                    if not 0 <= size <= LIMIT:
                        raise ValueError('Invoke body bound')
                    raw = self.rfile.read(size)
                    payload = json.loads(raw)
                    api_id, execution_id = 'api-' + uuid.uuid4().hex, 'execution-' + uuid.uuid4().hex
                    row = {'target': target, 'event': payload, 'requestBytesBase64': base64.b64encode(raw).decode(),
                           'invoke': {'logType': self.headers.get('X-Amz-Log-Type'),
                                      'invocationType': self.headers.get('X-Amz-Invocation-Type')},
                           'signed': self.headers.get('Authorization', '').startswith('AWS4-HMAC-SHA256 '),
                           'invokeApiRequestId': api_id, 'backendExecutionRequestId': execution_id,
                           'sdkReceivedMonotonic': time.monotonic()}
                    owner.calls.append(row)
                    if target in denied_targets:
                        # Explicit owned IAM simulation, never backend execution.
                        row['backendExecutionRequestId'] = None
                        row['simulatedBoundary'] = 'IAM-AccessDeniedException'
                        data = b'{"Type":"User","message":"synthetic denial"}'
                        self.send_response(403)
                        self.send_header('Content-Length', str(len(data)))
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('X-Amzn-ErrorType', 'AccessDeniedException')
                        self.send_header('X-Amzn-RequestId', api_id)
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    result = backends[target].submit(payload, execution_id)
                    row.update(backendResultKind=result['kind'], backendPayloadBase64=base64.b64encode(result['payload']).decode(),
                               backendFinishedMonotonic=time.monotonic())
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(result['payload'])))
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('X-Amzn-RequestId', api_id)
                    self.send_header('X-Amz-Executed-Version', '1')
                    if result['kind'] == 'error':
                        self.send_header('X-Amz-Function-Error', 'Unhandled')
                    self.end_headers()
                    try:
                        self.wfile.write(result['payload'])
                        row['responseDelivery'] = 'written'
                    except (BrokenPipeError, ConnectionResetError):
                        # A gateway timeout does not cancel backend execution.
                        row['responseDelivery'] = 'client-disconnected'
                except Exception as error:
                    owner.errors.append(str(error))
                    self.send_error(500)

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def observation(response, calls):
    headers = [[k, v] for k, v in sorted((response.get('headers') or {}).items())]
    headers += [[k, v] for k, values in sorted((response.get('multiValueHeaders') or {}).items()) for v in values]
    return {'outcome': 'response', 'status': response['statusCode'], 'headers': headers,
            'headersAbsent': [], 'body': response.get('body'), 'bodyBase64': response.get('isBase64Encoded'),
            'jwksFetches': 0, 'backendCalls': [{k: c[k] for k in ['target', 'event', 'invoke']} for c in calls],
            'responseMaps': {'headers': response.get('headers'), 'multiValueHeaders': response.get('multiValueHeaders')}}


def configure(args, out, sample, endpoint, rust, proxy_settings=None):
    source = out / 'configuration-source'
    source.mkdir()
    files = copy.deepcopy(sample['config']['files'])
    files['values'] = dict(files.get('values', {}), **sample['config']['values'])
    files['values'].update({'security.enabled': False, 'unified-security.enabled': False, 'logger.enabled': False})
    files['lambda-proxy']['endpointOverride'] = endpoint
    files['lambda-proxy']['logType'] = 'None'
    # Injected clients bypass native SDK construction. Real transport needs the
    # same explicit positive settings as the already qualified native profile.
    files['lambda-proxy'].update(connectionTimeout=10000, readTimeout=60000,
                                 writeTimeout=60000, apiCallTimeout=60000,
                                 apiCallAttemptTimeout=20000, metricsName='lambda-proxy')
    files['lambda-proxy'].update(proxy_settings or {})
    for name, data in files.items():
        write(source / (name + '.yml'), data)
    (source / 'logback.xml').write_text('<configuration><appender name="out" class="ch.qos.logback.core.ConsoleAppender"><encoder><pattern>%level %logger %msg%n</pattern></encoder></appender><root level="WARN"><appender-ref ref="out"/></root></configuration>\n')
    spec = importlib.util.spec_from_file_location('parity_pack', args.fabric / 'apps/light-lambda/scripts/package_baseline.py')
    pack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pack)
    from unittest.mock import patch
    with patch.dict(os.environ, {'LIGHT_LAMBDA_ALLOW_INSECURE_TEST_ENDPOINTS': '1'}):
        info = pack.layer(source, out / 'local-config-layer.zip', rust)
    pack.extract_layer(out / 'local-config-layer.zip', out / 'opt')
    write(out / 'local-layer-report.json', info)
    java_source = out / 'java-configuration-source'
    shutil.copytree(source, java_source)
    if digest(JAVA_CONFIG) != JAVA_CONFIG_SHA:
        raise ValueError('pinned native status catalogue layer drift')
    with zipfile.ZipFile(JAVA_CONFIG) as z:
        for name in ['config.yml', 'status.yml']:
            (java_source / name).write_bytes(z.read(name))
    return java_source, out / 'opt'


def run_integration(args):
    pins = candidate_pins(args)
    out, manifest = prepare(args)
    managed, bridge, cleanup = [], None, []
    command_history = []
    try:
        for side, archive in [('java', args.java_zip), ('rust', args.rust_zip)]:
            unpack(archive, out / (side + '-package'), side, pins)
        selected = [c for c in inventory() if c['id'] in {r['id'] for r in manifest['rows'] if r['selected'] and r.get('fixture')}]
        if not selected:
            write(out / 'integration-report.json', {'green': False, 'reason': 'no runnable selected cases', 'rows': manifest['rows']})
            return 1
        for identity in ['echo-a', 'echo-b']:
            runtime = Runtime('parity-' + identity, out)
            managed.append(runtime)
            backend_env = dict(environment(), PARITY_BACKEND_IDENTITY=identity)
            if args.backend_observations:
                backend_env['PARITY_BACKEND_OBSERVATIONS'] = 'synthetic-v1'
            runtime.start([args.backend_binary], backend_env, out)
        backends = {r.name: r for r in managed}
        bridge = InvokeBridge(backends)
        sample = read(out / 'fixtures' / (selected[0]['id'] + '.json'))
        java_config, rust_config = configure(args, out, sample, f'http://127.0.0.1:{bridge.server.server_port}', out / 'rust-package/bootstrap')
        raw_results = []
        digests = {}
        for f in (out / 'fixtures').glob('*.json'):
            # Existing canonical fixture contract: all generated values are JSON
            # integers/strings, and keys sorted recursively; no float conversion.
            digests[f.stem] = __import__('hashlib').sha256(json.dumps(read(f), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        for side in ['java', 'rust']:
            runtime = Runtime('parity-local-' + side + '-gateway', out)
            managed.append(runtime)
            env = environment()
            env['_HANDLER'] = 'com.networknt.aws.lambda.app.LambdaApp::handleRequest'
            if side == 'java':
                command = [out / 'java-package/lambda-native', '-Dlight-4j-config-dir=' + str(java_config),
                           '-Dlogback.configurationFile=' + str(java_config / 'logback.xml')]
            else:
                command = [out / 'rust-package/bootstrap']
                env.update(LIGHT_LAMBDA_CONFIG_DIR=str(rust_config), LIGHT_LAMBDA_ALLOW_INSECURE_TEST_ENDPOINTS='1',
                           LIGHT_LAMBDA_GATEWAY_ARN='arn:aws:lambda:us-east-1:000000000000:function:' + runtime.name,
                           RUST_LOG='info')
            runtime.start(command, env, out)
            for case in selected:
                case_start = time.monotonic()
                observations = []
                for index, logical in enumerate(case['requests']):
                    raw = event(logical, case['id'], side + '-' + uuid.uuid4().hex, manifest['runId'])
                    write(out / 'wire-events' / side / f'{case["id"]}-{index}.json', raw)
                    before = len(bridge.calls)
                    result = runtime.submit(raw)
                    if result['kind'] != 'response':
                        raise AssertionError('gateway Runtime API error: ' + side + '/' + case['id'])
                    response = json.loads(result['payload'])
                    calls = copy.deepcopy(bridge.calls[before:])
                    observations.append(observation(response, calls))
                    raw_results.append({'side': side, 'id': case['id'], 'step': index,
                                        'runId': manifest['runId'],
                                        'attemptId': raw['multiValueHeaders']['x-parity-attempt'][0],
                                        'gatewayRuntimeRequestId': result['id'], 'gatewayPid': runtime.process.pid,
                                        'responseBytesBase64': base64.b64encode(result['payload']).decode(),
                                        'response': response, 'backendCalls': calls})
                write(out / side / (case['id'] + '.json'), {
                    'schema': 'light-lambda-conformance/result/v1', 'id': case['id'], 'runner': side,
                    'runnerRevision': manifest['sourceRevisions'][side], 'fixtureDigest': digests[case['id']],
                    # Comparator independently checks all expectations. This is
                    # collector completion, never a manufactured expectation pass.
                    'execution': 'passed', 'durationMs': round((time.monotonic() - case_start) * 1000),
                    'observations': observations, 'assertionErrors': []})
        write(out / 'raw-integration-results.json', raw_results)
        write(out / 'invoke-transport.json', bridge.calls)
        if bridge.errors:
            raise AssertionError(bridge.errors)
        for action, extras in [('validate', [out / 'fixtures', '--results', out / 'java']),
                               ('validate', [out / 'fixtures', '--results', out / 'rust']),
                               ('compare', ['--fixtures', out / 'fixtures', '--out', out / 'compare',
                                            '--java', out / 'java', '--rust', out / 'rust',
                                            '--expectations', 'original', '--declarations', 'original'])]:
            result = execute([args.rust_runner, action, *extras], args.fabric,
                             out / f'integration-command-{len(command_history)}.log', 120)
            command_history.append(result)
        write(out / 'integration-commands.json', command_history)
        compared = read(out / 'compare/coverage.json')
        green = all(c['exitCode'] == 0 for c in command_history) and all(r['outcome'] == 'pass' for r in compared['rows'])
        # Backend IDs come from the real runtime context/log, not Invoke API IDs.
        for r in managed[:2]:
            r.log.flush()
        records = [json.loads(line) for r in managed[:2] for line in (out / (r.name + '.log')).read_text().splitlines() if line.startswith('{')]
        entries = [r for r in records if r.get('phase') == 'entry']
        completions = [r for r in records if r.get('phase') == 'completion']
        actual = {r['executionRequestId']: r for r in entries}
        assert len(actual) == len(entries) == len(bridge.calls) == len(completions)
        assert {r['executionRequestId'] for r in completions} == set(actual)
        for call in bridge.calls:
            r = actual[call['backendExecutionRequestId']]
            assert r['backendIdentity'] == call['target'].removeprefix('parity-') and r['backendVersion'] == '1'
            assert call['signed'] and call['invoke']['logType'] == 'None'
            assert r['attemptId'] == call['event']['multiValueHeaders']['x-parity-attempt'][0]
            assert call['invokeApiRequestId'] != call['backendExecutionRequestId']
        write(out / 'backend-execution-records.json', records)
        if args.backend_observations:
            requests = []
            for row in raw_results:
                calls = row['backendCalls']
                requests.append({k: row[k] for k in ['side', 'id', 'step', 'runId', 'attemptId']} |
                                {'backendExecutionRequestId': calls[0]['backendExecutionRequestId'] if calls else None})
            received = compare_received(records, requests)
            write(out / 'backend-received-comparison.json', received)
            green = green and received['passed']
        write(out / 'integration-report.json', {'schema': 'lambda-parity-integration/v1',
              'topology': 'gateway-sdk-http-invoke-to-running-backend-runtime', 'green': green,
              'selected': manifest['selected'], 'total': manifest['total'],
              'comparison': compared, 'gatewaySteps': len(raw_results), 'invokeApiCalls': len(bridge.calls),
              'backendExecutions': len(entries), 'backendCompletions': len(completions),
              'backendBinarySha256': digest(args.backend_binary),
              'gatewayZipSha256': {s: digest(getattr(args, s + '_zip')) for s in ['java', 'rust']},
              'gatewayProcessReuse': 'one actual process per gateway across all selected steps',
              'adaptations': ['owned endpointOverride', 'proxy-only configuration layer',
                              'per-side opaque control attempt IDs; logical requests and expectations unchanged'],
              'awsCalls': 0, 'awsQualification': False, 'injectedClient': False})
        print(json.dumps({'out': str(out), 'green': green, 'gatewaySteps': len(raw_results), 'backendExecutions': len(entries)}))
        return 0 if green else 1
    except BaseException as error:
        write(out / 'integration-error.json', {'kind': type(error).__name__, 'reason': str(error)})
        if bridge:
            write(out / 'failed-invoke-transport.json', bridge.calls)
        raise
    finally:
        for runtime in reversed(managed):
            cleanup.append(runtime.close())
        if bridge:
            bridge.close()
        write(out / 'integration-cleanup.json', cleanup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--case', action='append')
    parser.add_argument('--fabric', type=Path, default=REPO.parent / 'light-fabric-light-lambda')
    parser.add_argument('--java', type=Path, default=REPO.parent / 'light-lambda-native-conformance')
    parser.add_argument('--backend-binary', type=Path, default=REPO / 'target/x86_64-unknown-linux-musl/release/lambda-trial-backend')
    parser.add_argument('--java-zip', type=Path, default=JAVA_ZIP)
    parser.add_argument('--rust-zip', type=Path, default=RUST_ZIP)
    parser.add_argument('--candidate-manifest', type=Path,
                        help='explicit approved local Java candidate; accepted default pins unchanged')
    parser.add_argument('--backend-observations', action='store_true',
                        help='opt in backend-only synthetic received-event records and independent assertions')
    args = parser.parse_args()
    for key in ['fabric', 'java', 'backend_binary', 'java_zip', 'rust_zip', 'out']:
        setattr(args, key, getattr(args, key).resolve())
    args.rust_runner = args.fabric / 'target/debug/serverless-conformance'
    return run_integration(args)


if __name__ == '__main__':
    raise SystemExit(main())
