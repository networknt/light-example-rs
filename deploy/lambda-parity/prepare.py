#!/usr/bin/env python3
"""Prepare an artifact-bound review scope. Never contacts AWS or deploys."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', required=True)
    parser.add_argument('--region', required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--prefix', required=True)
    for name in ['backend', 'java', 'rust']:
        parser.add_argument('--' + name + '-zip', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9]{12}', args.account):
        parser.error('account must be explicit 12 digit ID')
    if not re.fullmatch(r'[a-z]{2}-[a-z]+-[0-9]+', args.region):
        parser.error('invalid region')
    if not re.fullmatch(r'parity-[a-z0-9-]{1,30}', args.prefix):
        parser.error('prefix must identify a new parity trial')
    artifacts = {}
    for name in ['backend', 'java', 'rust']:
        path = getattr(args, name + '_zip').resolve()
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if 'bootstrap' not in names or any(n.startswith('/') or '..' in Path(n).parts for n in names):
                parser.error('invalid Lambda archive layout: ' + name)
            if not (archive.getinfo('bootstrap').external_attr >> 16) & 0o111:
                parser.error('bootstrap must be executable: ' + name)
        artifacts[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'sizeBytes': path.stat().st_size}
    args.out.mkdir(parents=True, exist_ok=False)
    resources = [f'{args.prefix}-{suffix}' for suffix in ['echo-a', 'echo-b', 'java-gateway', 'rust-gateway']]
    review = {'schema': 'lambda-parity-aws-review/v1', 'deployable': False,
              'account': args.account, 'region': args.region, 'profile': args.profile,
              'artifacts': artifacts, 'functions': resources,
              'logGroups': ['/aws/lambda/' + name for name in resources],
              'stacks': [args.prefix + '-backends', args.prefix + '-gateways'],
              'roles': 'four stack-owned execution roles; generated physical names',
              'limits': {'concurrency': 1, 'maximumGatewayInvocations': 26,
                         'maximumBackendContractInvocations': 32,
                         'backendTimeoutSeconds': 5, 'gatewayTimeoutSeconds': 10,
                         'evidenceDeadlineSeconds': 60, 'logRetentionDays': 3,
                         'requestBodyBytes': 4096, 'automaticRetries': 0},
              'permissions': {'gatewayInvoke': 'only A/B qualified version ARNs; no aliases or wildcard',
                              'backend': 'own log streams only',
                              'runner': 'separate scoped Invoke, GetFunction/GetFunctionConfiguration, read own trial logs; STS GetCallerIdentity'},
              'notAuthorized': ['upload', 'create stack', 'create IAM', 'publish layer', 'invoke', 'delete'],
              'pending': ['owner authorization', 'S3 immutable object versions',
                          'resolved backend version ARNs', 'trial-owned per-gateway config layer digests and versions',
                          'gateway native architecture/runtime qualification', 'role/policy snapshots',
                          'STS account/region verification before any AWS action',
                          'exact selected AWS case expectations and estimated regional charges',
                          'CloudWatch positive control, bounded collection and deduplication',
                          'explicit cleanup confirmation'],
              'cleanup': 'only named trial stacks/functions, stack-owned IAM and trial layers; logs/versions retained for review; preserve accepted deployments, pet-store, artifacts and failed runs'}
    (args.out / 'review.json').write_text(json.dumps(review, indent=2) + '\n')
    for name in ['template.yaml', 'backends.template.yaml']:
        source = Path(__file__).parent / name
        (args.out / name).write_bytes(source.read_bytes())
    print(json.dumps({'out': str(args.out), 'deployable': False, 'awsCalls': 0}))


if __name__ == '__main__':
    main()
