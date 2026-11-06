#!/usr/bin/env python3
"""Native candidate Init/service/SDK checks against an owned envelope stub.

This is distinct from gateway-to-running-backend evidence and never claims
backend execution IDs or AWS FunctionError/platform qualification.
"""
import argparse
import json
from pathlib import Path
import uuid

from integration import (Runtime, InvokeBridge, environment, configure, unpack,
                         candidate_pins)
from run import ARTIFACTS, REPO, event, read, write


def run(args):
    pins = candidate_pins(args)
    out = args.out.resolve()
    assert out.is_relative_to(ARTIFACTS.resolve())
    out.mkdir(parents=True, exist_ok=False)
    shapes = {
        'missing': ('response', {'body': 'private-canary'}),
        'null-status': ('response', {'statusCode': None, 'body': 'private-canary'}),
        'timeout-error': ('error', {'errorType': 'Sandbox.Timedout', 'errorMessage': 'private-canary', 'stackTrace': ['private-stack']}),
        'function-error': ('error', {'errorType': 'SyntheticFailure', 'errorMessage': 'private-canary', 'stackTrace': ['private-stack']})}
    class Stub:
        def submit(self, payload, ident):
            mode = payload['multiValueHeaders']['x-parity-case'][0]
            if mode in shapes:
                kind, value = shapes[mode]
            else:
                kind = 'response'
                value = {'statusCode': int(mode.removeprefix('valid-')), 'headers': {'content-type': 'application/json', 'x-synthetic': 'kept'},
                         'body': 'opaque', 'isBase64Encoded': False}
            return {'kind': kind, 'payload': json.dumps(value, separators=(',', ':')).encode()}
    bridge = InvokeBridge({'parity-echo-a': Stub()})
    runtime = None
    try:
        unpack(args.java_zip, out / 'java-package', 'java', pins)
        # Offline layer validation still uses the unchanged accepted Rust bootstrap.
        from integration import RUST_ZIP
        unpack(RUST_ZIP, out / 'rust-package', 'rust', pins)
        plan = read(ARTIFACTS / 'parity-received-aws-20261023T001101Z/aws-final/scope/event-plan.json')
        sample = read(Path(plan['events'][0]['expectationFixture']))
        sample['config']['files']['lambda-proxy']['functions'] = {'/parity/a@post': 'parity-echo-a'}
        java, _ = configure(args, out, sample, f'http://127.0.0.1:{bridge.server.server_port}', out / 'rust-package/bootstrap')
        runtime = Runtime('candidate-shapes-java', out)
        runtime.start([out / 'java-package/lambda-native', '-Dlight-4j-config-dir=' + str(java),
                       '-Dlogback.configurationFile=' + str(java / 'logback.xml')],
                      dict(environment(), _HANDLER='com.networknt.aws.lambda.app.LambdaApp::handleRequest'), out)
        sequence = [mode for failed in shapes for mode in [failed, 'valid-200']] + ['valid-200', 'valid-201', 'valid-204', 'valid-500']
        rows = []
        for index, mode in enumerate(sequence):
            result = runtime.submit(event({'mode': mode, 'path': '/parity/a'}, 'PROXY-native-shapes', uuid.uuid4().hex))
            assert result['kind'] == 'response', result
            value = json.loads(result['payload'])
            before_error = mode in shapes
            assert value['statusCode'] == (500 if before_error else int(mode.removeprefix('valid-')))
            if before_error:
                assert json.loads(value['body']) == {'statusCode': 500, 'code': 'ERR14004', 'message': 'MIDDLEWARE_UNHANDLED_EXCEPTION',
                    'description': 'Middleware thread unhandled runtime exception.', 'severity': 'ERROR'}
                assert all(s not in json.dumps(value) for s in ['private-canary', 'private-stack', 'Sandbox.Timedout', 'SyntheticFailure'])
            else:
                assert value['body'] == 'opaque' and value['headers']['x-synthetic'] == 'kept'
            assert value['isBase64Encoded'] is False
            assert len(bridge.calls) == index + 1
            rows.append({'mode': mode, 'response': value, 'gatewayRequestId': result['id'], 'passed': True})
        assert not bridge.errors
        write(out / 'report.json', {'green': True, 'requests': len(rows), 'HTTPInvokeReceipts': len(bridge.calls),
              'source': 'owned envelope stub, not running backend or AWS platform proof',
              'gatewayZipSha256': pins['java'], 'gatewayPid': runtime.process.pid, 'rows': rows})
        write(out / 'http-receipts.json', bridge.calls)
        print(json.dumps({'green': True, 'requests': len(rows), 'HTTPInvokeReceipts': len(bridge.calls)}))
    finally:
        cleanup = runtime.close() if runtime else None
        bridge.close()
        write(out / 'cleanup.json', cleanup)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--java-zip', required=True, type=Path)
    parser.add_argument('--candidate-manifest', required=True, type=Path)
    parser.add_argument('--fabric', type=Path, default=REPO.parent / 'light-fabric-light-lambda')
    run(parser.parse_args())
