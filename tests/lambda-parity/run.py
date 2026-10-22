#!/usr/bin/env python3
"""Offline-first parity orchestration over the existing fixture/result-v1 runners."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import uuid
from urllib.parse import unquote
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ARTIFACTS = REPO.parent / 'artifacts/implementation/light-lambda'
OUTCOMES = ['equivalent-pass', 'intentional-difference-pass', 'fail', 'blocked',
            'unavailable', 'deferred', 'not-selected', 'inconclusive-evidence']


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command, cwd, log, timeout=60):
    """Bounded process group, no retries; preserve even failed logs."""
    start = time.monotonic()
    with log.open('x') as stream:
        child = subprocess.Popen(['rtk', 'proxy', *map(str, command)], cwd=cwd,
                                 stdout=stream, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            code = 124
    return {'command': list(map(str, command)), 'cwd': str(cwd), 'exitCode': code,
            'durationMs': round((time.monotonic() - start) * 1000), 'log': str(log)}


def inventory():
    cases = read(HERE / 'cases.json')
    Draft202012Validator(read(HERE / 'schemas/cases-v1.schema.json')).validate(cases)
    ids = set()
    for case in cases:
        if case['id'] in ids:
            raise ValueError('duplicate case ID')
        ids.add(case['id'])
        if case['availability'] not in ['local', 'unavailable', 'deferred']:
            raise ValueError('invalid availability')
        if not case.get('reason') or not case.get('requiredCapabilities'):
            raise ValueError('capabilities and reason required')
    return cases


def event(logical, case_id, attempt, run_id='unit-contract'):
    headers = copy.deepcopy(logical.get('headers', {}))
    headers.update({'x-parity-case': [logical['mode']], 'x-parity-run': [run_id],
                    'x-parity-id': [case_id], 'x-parity-attempt': [attempt]})
    result = {'requestContext': {'elb': {'targetGroupArn':
        'arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/parity/0'}},
        'httpMethod': logical.get('method', 'POST'), 'path': logical.get('path', '/parity/a'),
        'multiValueHeaders': headers,
        'multiValueQueryStringParameters': copy.deepcopy(logical.get('query', {})),
        'isBase64Encoded': logical.get('base64', False)}
    if 'body' in logical:
        result['body'] = logical['body']
    return result


def fixture(case, template, run_id='unit-contract'):
    f = copy.deepcopy(template)
    f['id'] = case['id']
    f['title'] = case['reason']
    f['ledger'] = ['E-03', 'E-04', 'E-10', 'E-12', 'E-13']
    f['differences'] = ['backendCalls']
    f['config']['files']['lambda-proxy']['functions'] = {
        '/parity/a@post': 'parity-echo-a', '/parity/b@post': 'parity-echo-b'}
    f['config']['files']['lambda-proxy']['logType'] = 'None'
    # Keep all optional keys and contracts of the existing fixture schema.
    steps = []
    for index, logical in enumerate(case['requests']):
        raw = event(logical, case['id'], f'paired-{uuid.uuid4().hex}', run_id)
        target = 'parity-echo-b' if raw['path'] == '/parity/b' else 'parity-echo-a'
        mode = logical['mode']
        response = {'statusCode': 200, 'body': '', 'isBase64Encoded': False}
        if mode == 'created':
            response.update(statusCode=201, body='{"result":"created"}')
        elif mode == 'no-content':
            response['statusCode'] = 204
        elif mode == 'application-error':
            response.update(statusCode=500, body='{"code":"PARITY_APPLICATION_ERROR"}')
        else:
            if mode != 'empty':
                raise ValueError('mode requires an explicitly declared fixture adapter: ' + mode)
        response['headers'] = {'content-type': 'application/json'}
        expected = {'outcome': 'response', 'status': response['statusCode'],
                    'headers': [['content-type', 'application/json']],
                    'headersAbsent': [], 'body': response['body'], 'bodyBase64': False,
                    'jwksFetches': 0}
        forwarded = {'path': raw['path'], 'httpMethod': raw['httpMethod'],
                     'isBase64Encoded': False}
        # Assert only this profile's named fields. Actual full calls remain in result-v1.
        if logical.get('body') is not None:
            forwarded['body'] = logical['body']
        if logical.get('headers'):
            forwarded['multiValueHeaders'] = logical['headers']
        if logical.get('query'):
            forwarded['multiValueQueryStringParameters'] = logical['query']
        expected['backendCalls'] = [{'target': target, 'event': forwarded,
                                    'invoke': {'logType': 'None'}}]
        java = copy.deepcopy(expected)
        # E-04: Java preserves encoded query values; Rust decodes percent once,
        # preserving literal plus and value order. Do not use unquote_plus.
        if logical.get('query'):
            expected['backendCalls'][0]['event']['multiValueQueryStringParameters'] = {
                unquote(k): [unquote(v) for v in values] for k, values in logical['query'].items()}
        # Native SDK leaves the default RequestResponse enum unset on the request.
        java['backendCalls'][0]['invoke']['invocationType'] = None
        java['backendCalls'][0]['event']['requestContext'] = {}
        expected['backendCalls'][0]['event']['requestContext'] = {'stage': 'test-only'}
        if logical.get('body') is None:
            java['backendCalls'][0]['eventAbsent'] = ['/body']
            expected['backendCalls'][0]['event']['body'] = None
        steps.append({'rawEvent': raw, 'headerMode': 'multi',
                      'backend': [{'match': {'target': target}, 'respond': {
                          'functionError': None, 'payload': response}}],
                      'expect': expected, 'expectJava': java})
    for key in ['rawEvent', 'backend', 'expect', 'expectJava']:
        f.pop(key, None)
    if len(steps) == 1:
        f.update(steps[0])
    else:
        f['steps'] = steps
    return f


def prepare(args):
    cases = inventory()
    selected = set(args.case or [c['id'] for c in cases if c['availability'] == 'local'])
    unknown = selected - {c['id'] for c in cases}
    if unknown:
        raise ValueError('unknown selection: ' + ','.join(sorted(unknown)))
    out = args.out.resolve()
    if not out.is_relative_to(ARTIFACTS.resolve()):
        raise ValueError('evidence must be below ' + str(ARTIFACTS))
    out.mkdir(parents=True, exist_ok=False)
    template_path = args.fabric / 'tests/serverless-conformance/fixtures/v1/e/E-03-response-off-0-multi-v1.json'
    template = read(template_path)
    rows = []
    run_id = uuid.uuid4().hex
    for case in cases:
        row = {'id': case['id'], 'family': case['family'], 'selected': case['id'] in selected,
               'inventoryAvailability': case['availability'],
               'reason': case['reason'], 'requiredCapabilities': case['requiredCapabilities'],
               'outcome': 'not-selected'}
        if row['selected']:
            if case['availability'] != 'local':
                row['outcome'] = case['availability']
            else:
                f = fixture(case, template, run_id)
                path = out / 'fixtures' / (case['id'] + '.json')
                write(path, f)
                row.update(outcome='blocked', reason='prepared; not executed', fixture=path.name,
                           fixtureSha256=digest(path), steps=len(case['requests']))
                # Paired input equality is deliberate for multi-value ALB direct Invoke.
                for side in ['java', 'rust']:
                    for index, step in enumerate(f.get('steps', [f])):
                        write(out / 'events' / side / f'{case["id"]}-{index}.json', step['rawEvent'])
        rows.append(row)
    revisions = {}
    for side, repo in [('java', args.java), ('rust', args.fabric), ('suite', REPO)]:
        revisions[side] = subprocess.check_output(['rtk', 'git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    manifest = {'schema': 'lambda-parity-run/v1', 'topology': 'local-conformance-owned-dependencies',
                'runId': run_id, 'sideAttemptIds': {side: uuid.uuid4().hex for side in ['java', 'rust']},
                'selected': len(selected), 'total': len(cases), 'rows': rows,
                'sourceRevisions': revisions, 'template': str(template_path),
                'templateSha256': digest(template_path), 'sdkRetries': 'not applicable: injected local clients',
                'environmentReuse': 'sequential recovery; environment reuse unconfirmed',
                'backendEvidence': 'local runner dependency calls; not AWS backend execution IDs',
                'profile': 'proxy-only-application-authentication-disabled-v1',
                'differenceLedger': 'profiles/proxy-only-v1.json',
                'caseInventorySha256': digest(HERE / 'cases.json')}
    write(out / 'manifest.json', manifest)
    return out, manifest


def summarize(out):
    manifest = read(out / 'manifest.json')
    coverage_path = out / 'compare/coverage.json'
    coverage = read(coverage_path) if coverage_path.exists() else None
    compared = {row['id']: row for row in coverage['rows']} if coverage else {}
    rows = []
    for row in manifest['rows']:
        row = copy.deepcopy(row)
        if row.get('fixture'):
            path = out / 'fixtures' / row['fixture']
            if digest(path) != row['fixtureSha256']:
                row.update(outcome='fail', reason='fixture changed after preparation')
            elif row['id'] in compared:
                actual = compared[row['id']]
                row['comparison'] = actual
                # Existing comparison enforces independent expectations and exact
                # observed-versus-declared differences (including stale declarations).
                row.update(outcome='intentional-difference-pass' if actual.get('outcome') == 'pass' else 'fail',
                           reason='existing result-v1 comparator; see comparison')
        rows.append(row)
    counts = {outcome: sum(r['outcome'] == outcome for r in rows) for outcome in OUTCOMES}
    green = all(r['outcome'] in ['equivalent-pass', 'intentional-difference-pass'] for r in rows if r['selected'])
    backend = out / 'backend/report.json'
    if not backend.exists() or read(backend).get('passed') is not True:
        green = False
    if (out / 'runner-error.json').exists():
        green = False
    files = {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob('*'))
             if p.is_file() and p.relative_to(out).as_posix() not in ['report.json', 'report.md']}
    report = {'schema': 'lambda-parity-report/v1', 'selected': manifest['selected'],
              'total': manifest['total'], 'green': green, 'fullParity': False,
              'counts': counts, 'rows': rows, 'evidenceSha256': files}
    Draft202012Validator(read(HERE / 'schemas/report-v1.schema.json')).validate(report)
    return report


def run(args):
    out, manifest = prepare(args)
    history = []
    def call(command, cwd, name, timeout=90):
        result = execute(command, cwd, out / (name + '.log'), timeout)
        history.append(result)
        write(out / 'commands' / f'{len(history):03d}.json', result)
        return result['exitCode']
    rust = args.rust_runner.resolve()
    backend = args.backend_binary.resolve()
    if not backend.is_file():
        raise ValueError('build lambda-trial-backend first')
    call(['python3', '-B', HERE / 'test_backend_runtime.py', '--binary', backend,
          '--out', out / 'backend'], REPO, 'backend-contract', 60)
    write(out / 'backend-identity.json', {'binarySha256': digest(backend),
          'sourceSha256': digest(REPO / 'apps/lambda-trial-backend/src/parity.rs'),
          'modeTable': 'parity-modes/v1', 'reportSha256': digest(out / 'backend/report.json')
          if (out / 'backend/report.json').exists() else None})
    if not rust.is_file():
        raise ValueError('build serverless-conformance first: cargo build --locked -p serverless-conformance')
    java_classes = {}
    for directory in ['target/classes', 'target/test-classes']:
        for path in sorted((args.java / directory).rglob('*.class')):
            java_classes[str(path.relative_to(args.java))] = digest(path)
    write(out / 'runner-identities.json', {'rustBinarySha256': digest(rust),
          'javaClassSha256': java_classes,
          'javaClasspathSha256': digest(args.java / 'target/conformance-cp.txt'),
          'suiteSourceSha256': digest(Path(__file__)),
          'profileSha256': digest(HERE / 'profiles/proxy-only-v1.json')})
    # This local profile uses existing injected clients. Bind each configured
    # reply to the independently tested real backend artifact, not a second model.
    if (out / 'backend/report.json').exists():
        contracts = {identity: {r['mode']: r['result'] for r in read(out / 'backend' / f'{identity}-results.json')}
                     for identity in ['echo-a', 'echo-b']}
        for path in (out / 'fixtures').glob('*.json'):
            f = read(path)
            for step in f.get('steps', [f]):
                mode = step['rawEvent']['multiValueHeaders']['x-parity-case'][0]
                target = step['backend'][0]['match']['target'].removeprefix('parity-')
                if step['backend'][0]['respond']['payload'] != contracts[target][mode]:
                    raise ValueError('local reply differs from tested backend contract: ' + f['id'])
    call([rust, 'digest', out / 'fixtures'], args.fabric, 'digest')
    valid = call([rust, 'validate', out / 'fixtures'], args.fabric, 'validate') == 0
    if valid:
        cpfile = args.java / 'target/conformance-cp.txt'
        if not cpfile.exists():
            raise ValueError('build Java test classes and target/conformance-cp.txt first')
        cp = os.pathsep.join([str(args.java / 'target/test-classes'), str(args.java / 'target/classes'), cpfile.read_text().strip()])
        (out / 'java').mkdir()
        for path in sorted((out / 'fixtures').glob('*.json')):
            with tempfile.TemporaryDirectory(prefix='test-only-parity-') as config:
                call(['java', '-Dlight-4j-config-dir=' + config,
                      '-Dlogback.configurationFile=' + str(args.java / 'src/test/resources/conformance-logback.xml'),
                      '-Dconformance.runnerRevision=' + manifest['sourceRevisions']['java'],
                      '-cp', cp, 'com.networknt.aws.lambda.conformance.ConformanceRunnerMain',
                      path, out / 'java' / path.name], args.java, 'java-' + path.stem)
        call([rust, 'run', '--fixtures', out / 'fixtures', '--out', out / 'rust', '--expectations', 'original', '--declarations', 'original'], args.fabric, 'rust', 180)
        call([rust, 'compare', '--fixtures', out / 'fixtures', '--out', out / 'compare',
              '--java', out / 'java', '--rust', out / 'rust',
              '--expectations', 'original', '--declarations', 'original'], args.fabric, 'compare', 180)
    write(out / 'commands.json', history)
    report = summarize(out)
    write(out / 'report.json', report)
    with (out / 'report.md').open('x') as stream:
        stream.write(f"Selected {report['selected']}/{report['total']}; green={report['green']}; full parity=false.\n\n")
        stream.write('| Case | Outcome |\n| --- | --- |\n')
        for row in report['rows']:
            stream.write(f"| {row['id']} | {row['outcome']} |\n")
    print(json.dumps({'out': str(out), 'green': report['green'], 'counts': report['counts']}))
    return 0 if report['green'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inventory', 'prepare', 'run', 'compare'])
    parser.add_argument('--fabric', type=Path, default=REPO.parent / 'light-fabric-light-lambda')
    parser.add_argument('--java', type=Path, default=REPO.parent / 'light-lambda-native-conformance')
    parser.add_argument('--rust-runner', type=Path)
    parser.add_argument('--backend-binary', type=Path, default=REPO / 'target/debug/lambda-trial-backend')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--case', action='append')
    args = parser.parse_args()
    args.fabric = args.fabric.resolve()
    args.java = args.java.resolve()
    if args.action == 'inventory':
        print(json.dumps(inventory(), indent=2))
        return 0
    if not args.out:
        parser.error('--out required')
    if args.action == 'compare':
        saved = read(args.out / 'report.json')
        for name, sha in saved['evidenceSha256'].items():
            if digest(args.out / name) != sha:
                raise ValueError('saved evidence changed: ' + name)
        report = summarize(args.out.resolve())
        # Read-only comparison of saved evidence; never overwrite a historical report.
        print(json.dumps(report, indent=2))
        return 0 if report['green'] else 1
    if args.action == 'prepare':
        out, _ = prepare(args)
        print(out)
        return 0
    args.rust_runner = args.rust_runner or args.fabric / 'target/debug/serverless-conformance'
    out_existed = args.out.exists()
    try:
        return run(args)
    except Exception as error:
        # A selected execution that cannot start still leaves an inspectable,
        # non-green report. Never replace evidence from an existing directory.
        if not out_existed and (args.out / 'manifest.json').exists() and not (args.out / 'report.json').exists():
            write(args.out / 'runner-error.json', {'reason': str(error), 'kind': type(error).__name__})
            write(args.out / 'report.json', summarize(args.out.resolve()))
        raise


if __name__ == '__main__':
    raise SystemExit(main())
