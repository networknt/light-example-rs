#!/usr/bin/env python3
"""Run an isolated backend Docker contract smoke. No Portal database is modified."""
import argparse
import base64
import datetime
import hashlib
import hmac
import json
import secrets
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


def command(*args, input=None):
    return subprocess.run(args, input=input, check=True, capture_output=True, text=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='networknt/demo-support-triage-agent:0.1.0-local-triage')
    args = parser.parse_args()
    name = 'triage-smoke-' + secrets.token_hex(6)
    volume = name + '-state'
    uid = lambda: str(uuid.uuid4())  # Disposable test identities, never Portal events.
    digest = lambda value: 'sha256:' + hashlib.sha256(value).hexdigest()
    encode = lambda value: json.dumps(value, separators=(',', ':')).encode()
    key = secrets.token_bytes(32)
    config = {'audience': 'support-triage-backend', 'hostId': uid(), 'environment': 'dev',
              'agentRef': 'support-triage', 'bindingId': uid(), 'publicationId': uid(),
              'policyDigest': digest(b'smoke-policy'), 'dataBoundaryDigest': digest(b'smoke-data'),
              'contextKeyFile': '/app/state/key', 'stateDirectory': '/app/state'}
    contract = command('docker', 'run', '--rm', args.image, '/app/service', '--contract-digest')
    try:
        command('docker', 'volume', 'create', volume)
        with tempfile.TemporaryDirectory(prefix=name) as directory:
            root = Path(directory)
            (root/'backend.json').write_bytes(encode(config))
            (root/'key').write_bytes(key)
            (root/'key').chmod(0o600)
            command('docker', 'run', '--rm', '--user', '0', '-v', f'{root}:/input:ro',
                    '-v', f'{volume}:/app/state', '--entrypoint', '/bin/sh', args.image, '-ec',
                    'cp /input/backend.json /app/state/backend.json; cp /input/key /app/state/key; '
                    'chown -R 999:999 /app/state; chmod 700 /app/state; chmod 600 /app/state/key')
        command('docker', 'run', '-d', '--name', name, '-e', 'TRIAGE_CONFIG=/app/state/backend.json',
                '-v', f'{volume}:/app/state', args.image)

        def ready():
            for _ in range(50):
                result = subprocess.run(['docker', 'exec', name, 'curl', '-fsS',
                    'http://127.0.0.1:9010/health/ready'], capture_output=True)
                if result.returncode == 0:
                    return
                time.sleep(0.1)
            raise RuntimeError('backend readiness failed')

        def call(body, operation='INVOKE', operation_id=None):
            now = datetime.datetime.now(datetime.timezone.utc)
            request = encode(body)
            context = {'contractVersion': 'light-a2a-backend/v1', 'invocationId': uid(),
                'issuer': 'light-a2a', 'audience': config['audience'], 'hostId': config['hostId'],
                'environment': 'dev', 'principalSubject': 'user:smoke', 'callerAgentRef': 'smoke-client',
                'targetAgentRef': config['agentRef'], 'bindingId': config['bindingId'],
                'publicationId': config['publicationId'], 'selectedSkillId': body['skillId'],
                'operation': operation, 'taskId': body['taskId'], 'contextId': body['contextId'],
                'idempotencyKey': body['idempotencyKey'], 'backendOperationId': operation_id,
                'policyDigest': config['policyDigest'], 'dataBoundaryDigest': config['dataBoundaryDigest'],
                'requestDigest': digest(request), 'budget': {'maximumInputBytes': 16384,
                    'maximumOutputBytes': 16384, 'maximumArtifactBytes': 65536}, 'traceparent': None,
                'issuedAt': now.isoformat(), 'deadline': (now+datetime.timedelta(minutes=2)).isoformat(),
                'expiresAt': (now+datetime.timedelta(minutes=1)).isoformat()}
            encoded = base64.urlsafe_b64encode(encode(context)).rstrip(b'=')
            signature = hmac.new(key, encoded+b'\0'+request, hashlib.sha256).hexdigest()
            path = {'INVOKE': 'invoke', 'STATUS': 'status'}[operation]
            # Pass test authorization through stdin, never command-line arguments.
            curl_config = '\n'.join([
                'url = "http://127.0.0.1:9010/v1/'+path+'"', 'request = "POST"',
                'header = "content-type: application/json"',
                'header = "x-light-a2a-backend-contract-digest: '+contract+'"',
                'header = "x-light-a2a-backend-context: '+encoded.decode()+'"',
                'header = "x-light-a2a-backend-signature: '+signature+'"',
                'data = '+json.dumps(request.decode()), 'write-out = "\\n%{http_code}"'])
            return curl_config

        def send(config):
            output = command('docker', 'exec', '-i', name, 'curl', '-sS', '-K', '-', input=config)
            body, status = output.rsplit('\n', 1)
            return int(status), json.loads(body)

        ready()
        request = {'taskId': uid(), 'contextId': uid(), 'idempotencyKey': 'smoke-1',
            'skillId': 'support-triage', 'message': {'role': 'user', 'parts': [
                {'kind': 'text', 'text': 'Production outage affecting all users'}]}, 'metadata': {}}
        first = call(request)
        status, response = send(first)
        assert status == 200 and response['state'] == 'COMPLETED', response
        assert response['result']['category'] == 'availability' and response['result']['priority'] == 'high'
        assert send(first)[0] == 401, 'replay was accepted'
        assert send(call(request))[1] == response, 'idempotent retry changed result'
        command('docker', 'restart', name)
        ready()
        assert send(first)[0] == 401, 'replay state lost on restart'
        request['message'] = None
        request['idempotencyKey'] = 'status-1'
        assert send(call(request, 'STATUS', response['backendOperationId'])) == (200, response)
        print(json.dumps(response['result'], indent=2))
        print('PASS: Docker backend invocation, replay rejection, idempotency and restart/status recovery')
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True)
        subprocess.run(['docker', 'volume', 'rm', volume], capture_output=True)


if __name__ == '__main__':
    main()
