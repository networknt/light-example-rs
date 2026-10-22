#!/usr/bin/env python3
"""Bounded Runtime API contract check of the real parity backend, A and B."""
import argparse
import http.server
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from run import digest, write

MODES = ['echo', 'created', 'no-content', 'application-error', 'function-error',
         'empty', 'binary', 'cookies', 'wrong-type', 'missing-status',
         'invalid-base64', 'malformed-json', 'echo', 'unknown', 'duplicate', 'oversize']


def check(binary, identity, out):
    run_id = uuid.uuid4().hex
    results = []
    done = threading.Event()
    stopping = threading.Event()
    failures = []

    class Runtime(http.server.BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_GET(self):
            index = len(results)
            if index == len(MODES):
                done.set()
                stopping.wait(20)
                self.send_response(503)
                self.end_headers()
                return
            mode = MODES[index]
            headers = {'x-parity-case': ['echo' if mode in ['duplicate', 'oversize'] else mode],
                       'x-parity-run': [run_id], 'x-parity-id': [f'case-{index}'],
                       'x-parity-attempt': [f'{identity}-{uuid.uuid4().hex}'],
                       'authorization': ['private-canary'], 'cookie': ['private-canary'],
                       'x-private': ['private-canary']}
            event = {'httpMethod': 'POST', 'path': '/parity/a',
                     'multiValueHeaders': headers, 'body': '雪 synthetic', 'isBase64Encoded': False,
                     'queryStringParameters': {'q': 'a+b', 'token': 'private-canary'},
                     'requestContext': {'authorizer': {'token': 'private-canary'}}}
            if mode == 'duplicate':
                event['headers'] = {'X-Parity-Case': 'created'}
            if mode == 'oversize':
                event['body'] = 'x' * 4097
            data = json.dumps(event).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Lambda-Runtime-Aws-Request-Id', f'execution-{index}')
            self.send_header('Lambda-Runtime-Deadline-Ms', str(int(time.time() * 1000) + 10000))
            self.send_header('Lambda-Runtime-Invoked-Function-Arn',
                             'arn:aws:lambda:us-east-1:000000000000:function:local-parity:1')
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            try:
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                index = len(results)
                assert self.path in [f'/2018-06-01/runtime/invocation/execution-{index}/response',
                                     f'/2018-06-01/runtime/invocation/execution-{index}/error']
                results.append({'mode': MODES[index], 'path': self.path, 'result': value})
            except Exception as error:
                failures.append(str(error))
                done.set()
            self.send_response(202)
            self.send_header('Content-Length', '0')
            self.end_headers()

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = dict(os.environ, AWS_LAMBDA_RUNTIME_API=f'127.0.0.1:{server.server_port}',
               AWS_LAMBDA_FUNCTION_NAME='local-parity', AWS_LAMBDA_FUNCTION_VERSION='1',
               AWS_LAMBDA_FUNCTION_MEMORY_SIZE='128', PARITY_BACKEND_IDENTITY=identity)
    # Files avoid pipe-buffer deadlock and preserve failed evidence.
    with (out / f'{identity}.log').open('x') as log:
        process = subprocess.Popen([str(binary.resolve())], env=env, stdout=log, stderr=log)
        try:
            assert done.wait(20), 'backend runtime timed out'
            assert not failures, failures
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            stopping.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
    write(out / f'{identity}-results.json', results)
    text = (out / f'{identity}.log').read_text()
    assert 'private-canary' not in text + json.dumps(results)
    assert len(results) == len(MODES)
    for index in [0, 12]:
        result = results[index]['result']
        echoed = json.loads(result['body'])
        assert result['statusCode'] == 200
        assert echoed['backendIdentity'] == identity and echoed['backendVersion'] == '1'
        assert echoed['body'] == '雪 synthetic' and echoed['queryStringParameters'] == {'q': 'a+b'}
        assert 'requestContext' not in echoed
    assert results[1]['result']['statusCode'] == 201
    assert results[2]['result']['statusCode'] == 204
    assert results[3]['result']['statusCode'] == 500 and results[3]['path'].endswith('/response')
    assert results[4]['path'].endswith('/error')
    assert results[4]['result']['errorMessage'] == 'synthetic parity function error'
    assert results[5]['result']['body'] == ''
    assert results[6]['result']['body'] == 'AP9B' and results[6]['result']['isBase64Encoded'] is True
    assert results[7]['result']['multiValueHeaders']['set-cookie'] == ['synthetic=a; Secure', 'synthetic=b; Secure']
    assert results[8]['result']['statusCode'] == 'two hundred'
    assert 'statusCode' not in results[9]['result']
    assert results[10]['result']['body'] == '%%%'
    assert results[11]['result']['body'] == '{broken'
    assert all(r['result']['statusCode'] == 400 for r in results[13:])
    records = [json.loads(line) for line in text.splitlines() if line.startswith('{')]
    entries = [r for r in records if r.get('phase') == 'entry']
    completed = [r for r in records if r.get('phase') == 'completion']
    assert len(entries) == 16 and len(completed) == 15
    assert len({r['executionRequestId'] for r in entries}) == 16
    assert not any(r['executionRequestId'] == 'execution-4' for r in completed)
    return {'identity': identity, 'requests': len(results), 'entryRecords': len(entries),
            'completionRecords': len(completed), 'processReaped': process.poll() is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    rows = [check(args.binary, identity, args.out) for identity in ['echo-a', 'echo-b']]
    report = {'schema': 'lambda-parity-backend-contract/v1', 'binarySha256': digest(args.binary),
              'modeTable': 'parity-modes/v1', 'scope': 'actual executable/owned Runtime API; not RIE or AWS',
              'rows': rows, 'passed': True}
    write(args.out / 'report.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
