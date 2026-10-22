#!/usr/bin/env python3
"""Run the actual compiled backend against an owned loopback Lambda Runtime API."""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import subprocess
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    modes = ['success', 'application-error', 'function-error', 'success', 'invalid-command']
    results = []
    complete = threading.Event()

    class Runtime(http.server.BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_GET(self):
            assert self.path == '/2018-06-01/runtime/invocation/next', self.path
            index = len(results)
            if index == len(modes):
                complete.set()
                # Hold the long poll until the owner terminates and reaps the process.
                self.server.stopping.wait(20)
                self.send_response(503)
                self.end_headers()
                return
            mode = modes[index]
            body = json.dumps({'mode': mode, 'trialId': f'local-{index}'})
            event = {'body': body, 'isBase64Encoded': False,
                     'headers': {'authorization': 'privacy-canary-never-log'}}
            data = json.dumps(event).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Lambda-Runtime-Aws-Request-Id', f'request-{index}')
            self.send_header('Lambda-Runtime-Deadline-Ms', str(int(time.time() * 1000) + 10000))
            self.send_header('Lambda-Runtime-Invoked-Function-Arn',
                             'arn:aws:lambda:us-east-2:000000000000:function:local-trial')
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            index = len(results)
            body = self.rfile.read(int(self.headers['Content-Length']))
            assert self.path in [f'/2018-06-01/runtime/invocation/request-{index}/response',
                                 f'/2018-06-01/runtime/invocation/request-{index}/error'], self.path
            results.append({'mode': modes[index], 'path': self.path, 'result': json.loads(body)})
            self.send_response(202)
            self.send_header('Content-Length', '0')
            self.end_headers()

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Runtime)
    server.stopping = threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = dict(os.environ, AWS_LAMBDA_RUNTIME_API=f'127.0.0.1:{server.server_port}',
               AWS_LAMBDA_FUNCTION_NAME='local-trial', AWS_LAMBDA_FUNCTION_MEMORY_SIZE='128',
               AWS_LAMBDA_FUNCTION_VERSION='$LATEST')
    process = subprocess.Popen([str(args.binary.resolve())], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert complete.wait(15), f'timed out; process={process.poll()}, results={results}'
        assert len(results) == 5
        for index, status in [(0, 200), (1, 500), (3, 200), (4, 400)]:
            assert results[index]['path'].endswith('/response')
            assert results[index]['result']['statusCode'] == status, results[index]
        assert results[2]['path'].endswith('/error')
        assert results[2]['result']['errorMessage'] == 'synthetic trial function error'
        assert json.loads(results[0]['result']['body'])['trialId'] == 'local-0'
        assert json.loads(results[3]['result']['body'])['trialId'] == 'local-3'
    finally:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
        server.stopping.set()
        server.shutdown()
        server.server_close()
        (args.out / 'runtime-output.json').write_text(json.dumps(results, indent=2) + '\n')
        (args.out / 'backend.log').write_text(stdout + stderr)
    logs = stdout + stderr
    assert 'privacy-canary-never-log' not in logs
    observations = [json.loads(line) for line in logs.splitlines()
                    if line.startswith('{') and 'trial_backend_execution' in line]
    assert len(observations) == 5, observations
    assert [x['request_id'] for x in observations] == [f'request-{i}' for i in range(5)]
    assert observations[-1]['mode'] == 'invalid-command'
    assert 'trial_id' not in observations[-1]
    result = {'passed': 5, 'executions': len(observations), 'warmProcessCount': 1,
              'privacyCanaryAbsent': True, 'processReaped': process.returncode is not None,
              'binarySha256': hashlib.sha256(args.binary.read_bytes()).hexdigest(),
              'scope': 'local actual executable and Lambda Runtime API; not RIE or AWS'}
    (args.out / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
