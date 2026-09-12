#!/usr/bin/env python3
"""Run the actual light-a2a router against a disposable operational database."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time


def run(*args):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        # Database diagnostics can contain generated credentials; redact them.
        import re
        detail = re.sub(r'[0-9a-f]{64}', '[redacted]', result.stderr)
        raise RuntimeError('fixture command failed: ' + detail[-3000:])
    return result.stdout.strip()


def main():
    repo = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portal-config', type=Path, default=repo.parent/'portal-config-loc')
    parser.add_argument('--postgres-image', default='pgvector/pgvector:pg17')
    args = parser.parse_args()
    operations = args.portal_config.resolve()/'all-in-lt/postgres-db/operations'
    if not (operations/'bin/bootstrap-operational-databases.sh').is_file():
        parser.error('requires the canonical operational database bundle in portal-config-loc')
    name = 'triage-sidecar-test-' + secrets.token_hex(6)
    try:
        run('docker', 'run', '-d', '--name', name, '-e', 'POSTGRES_PASSWORD='+secrets.token_hex(32),
            '-p', '127.0.0.1::5432', '-v', f'{operations}:/opt/operational-store:ro', args.postgres_image)
        for _ in range(100):
            status = subprocess.run(['docker','exec',name,'pg_isready','-h','127.0.0.1','-U','postgres'],capture_output=True)
            if status.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError('disposable database did not become ready')
        port = int(run('docker','port',name,'5432/tcp').rsplit(':',1)[1])
        print('Provisioning disposable operational schemas; the local Portal database is untouched.', flush=True)
        run('docker','exec','-e','OPERATIONAL_HOST_SECRET_ROOT=/tmp/triage-secrets',
            '-e','OPERATIONAL_DATABASE_HOST=127.0.0.1','-e','OPERATIONAL_DATABASE_PORT='+str(port),name,
            'bash','/opt/operational-store/bin/bootstrap-operational-databases.sh')
        with tempfile.TemporaryDirectory(prefix='triage-sidecar-fixture-') as directory:
            root = Path(directory)
            for service in ('a2a','artifact'):
                value=run('docker','exec',name,'cat',f'/tmp/triage-secrets/dev.lightapi.net/{service}-database-url')
                path=root/(service+'-url')
                path.write_text(value)
                path.chmod(0o600)
            row=next(line.split('\t') for line in (operations/'operational-databases.tsv').read_text().splitlines() if line.startswith('operations\t'))
            (root/'fixture.json').write_text(json.dumps({'hostId':row[2],'bindingId':row[3],'bindingDigest':row[4],'port':port}))
            env=dict(os.environ,TRIAGE_SIDECAR_FIXTURE=str(root))
            subprocess.run(['cargo','test','--locked','-p','demo-support-triage-agent','--features','sidecar-test',
                '--test','sidecar','--','--ignored','--nocapture'],cwd=repo,env=env,check=True)
        print('PASS: light-a2a router -> signed backend -> durable A2A task -> sidecar state restart')
    finally:
        subprocess.run(['docker','rm','-fv',name],capture_output=True)


if __name__ == '__main__':
    main()
