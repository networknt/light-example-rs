#!/usr/bin/env python3
"""Artifact-bound stage 3 approval package. Offline only; no AWS SDK/CLI calls."""
import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import zipfile
import uuid

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / 'tests/lambda-parity'))
from run import ARTIFACTS, digest, event, inventory, read, write
from integration import JAVA_ZIP, RUST_ZIP, PINNED

def code_identity(path):
    data = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(),
            'lambdaCodeSha256': base64.b64encode(hashlib.sha256(data).digest()).decode(),
            'sizeBytes': len(data)}


def parameter_rows(values):
    return [{'ParameterKey': k, 'ParameterValue': str(v)} for k, v in values.items()]


def prepare(args):
    source = args.integration.resolve()
    qualified = read(source / 'integration-report.json')
    cleanup = read(source / 'integration-cleanup.json')
    if not qualified['green'] or qualified['gatewaySteps'] != 44 or qualified['backendExecutions'] != 42:
        raise ValueError('stage 3 requires the fourteen-case integration checkpoint')
    if len(cleanup) != 4 or not all(r['reaped'] for r in cleanup):
        raise ValueError('integration process cleanup is incomplete')
    if not re.fullmatch(r'parity-[a-z0-9-]{1,30}', args.prefix):
        raise ValueError('invalid fresh trial prefix')
    if args.account != '964637446810' or args.region != 'us-east-2':
        raise ValueError('this approval package is scoped to 964637446810/us-east-2')
    out = args.out.resolve()
    if not out.is_relative_to(ARTIFACTS.resolve()):
        raise ValueError('use the Light Lambda artifacts directory')
    out.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('stage3_pack', REPO.parent / 'light-fabric-light-lambda/apps/light-lambda/scripts/package_baseline.py')
    pack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pack)
    backend_binary = args.backend_binary.resolve()
    if digest(backend_binary) != qualified['backendBinarySha256']:
        raise ValueError('backend binary drift since integration qualification')
    # Package exactly the tested executable; never reuse an older ZIP merely
    # because its filename refers to the same backend source repository.
    backend_zip = out / 'backend-bootstrap.zip'
    pack.canonical_zip(backend_zip, {'bootstrap': backend_binary.read_bytes()}, {'bootstrap': 0o755}, 1792708800)
    artifacts = {name: code_identity(path) for name, path in [
        ('backend', backend_zip), ('java', JAVA_ZIP), ('rust', RUST_ZIP)]}
    assert all(artifacts[s]['sha256'] == PINNED[s] == qualified['gatewayZipSha256'][s] for s in ['java', 'rust'])
    with zipfile.ZipFile(backend_zip) as z:
        assert hashlib.sha256(z.read('bootstrap')).hexdigest() == qualified['backendBinarySha256']
    names = {s: args.prefix + '-' + s for s in ['echo-a', 'echo-b', 'java-gateway', 'rust-gateway']}
    # Proposed :1 identities, not claims about existing resources. Execution must
    # stop unless fresh stack outputs resolve exactly to these immutable versions.
    arns = {s: f'arn:aws:lambda:{args.region}:{args.account}:function:{names[s]}:1' for s in ['echo-a', 'echo-b']}
    bucket = f'll-{args.prefix}-{args.account}-{args.region}'
    if len(bucket) > 63:
        raise ValueError('artifact bucket name exceeds S3 bound')
    config = {}
    for side in ['java', 'rust']:
        src = source / ('java-configuration-source' if side == 'java' else 'configuration-source')
        dest = out / (side + '-configuration')
        shutil.copytree(src, dest)
        proxy = read(dest / 'lambda-proxy.yml')
        proxy.pop('endpointOverride')
        proxy['region'] = args.region
        proxy['functions'] = {'/parity/a@post': arns['echo-a'], '/parity/b@post': arns['echo-b']}
        (dest / 'lambda-proxy.yml').write_text(json.dumps(proxy, indent=2) + '\n')
        values = read(dest / 'values.yml')
        values['light-lambda.accountId'] = args.account
        (dest / 'values.yml').write_text(json.dumps(values, indent=2) + '\n')
        layer = out / (side + '-configuration.zip')
        # Reuse the actual package/config-layer tooling. Rust validates offline;
        # Java retains config/status from the qualified native layer3 source.
        from unittest.mock import patch
        with patch.dict(os.environ, {'SOURCE_DATE_EPOCH': '1792708800'}):
            if side == 'rust':
                info = pack.layer(dest, layer, source / 'rust-package/bootstrap')
            else:
                pack.canonical_zip(layer, {f.name: f.read_bytes() for f in sorted(dest.iterdir())}, {}, pack.epoch())
                info = {'nativeInitEvidence': str(source), 'nativeStatusCatalogue': 'pinned layer3; unchanged'}
        config[side] = dict(code_identity(layer), validation=info,
                            files={f.name: digest(f) for f in sorted(dest.iterdir())})
    backend = read(HERE / 'backends.template.yaml')
    gateway = read(HERE / 'template.yaml')
    for document in [backend, gateway]:
        for resource in document['Resources'].values():
            if resource['Type'] == 'AWS::Logs::LogGroup':
                resource['Properties'].pop('RetentionInDays', None)  # No automatic cleanup/TTL.
    for short in ['EchoA', 'EchoB']:
        backend['Resources'][short + 'Role']['Properties']['RoleName'] = {'Fn::Sub': '${TrialPrefix}-' + ('echo-a' if short == 'EchoA' else 'echo-b') + '-role'}
    for side in ['Java', 'Rust']:
        key = side.lower()
        gateway['Resources'][side + 'Role']['Properties']['RoleName'] = {'Fn::Sub': '${TrialPrefix}-' + key + '-gateway-role'}
        props = gateway['Resources'][side]['Properties']
        props.update(MemorySize=512, Timeout=20)
        if side == 'Java':
            props['Handler'] = 'com.networknt.aws.lambda.app.LambdaApp::handleRequest'
        gateway['Parameters'][side + 'ConfigKey'] = {'Type': 'String'}
        gateway['Parameters'][side + 'ConfigObjectVersion'] = {'Type': 'String'}
        gateway['Resources'][side + 'ConfigLayer'] = {
            'Type': 'AWS::Lambda::LayerVersion', 'DeletionPolicy': 'Retain', 'UpdateReplacePolicy': 'Retain',
            'Properties': {'LayerName': {'Fn::Sub': '${TrialPrefix}-' + key + '-config'},
                           'CompatibleArchitectures': ['x86_64'], 'CompatibleRuntimes': ['provided.al2023'],
                           'Content': {'S3Bucket': {'Ref': 'ArtifactBucket'}, 'S3Key': {'Ref': side + 'ConfigKey'},
                                       'S3ObjectVersion': {'Ref': side + 'ConfigObjectVersion'}}}}
        props['Layers'] = [{'Ref': side + 'ConfigLayer'}]
        # Bind permissions and profile to the exact proposed immutable identities.
        invoke = next(s for s in gateway['Resources'][side + 'Role']['Properties']['Policies'][0]['PolicyDocument']['Statement'] if s['Action'] == ['lambda:InvokeFunction'])
        invoke['Resource'] = list(arns.values())
    for key, value in [('EchoAQualifiedArn', arns['echo-a']), ('EchoBQualifiedArn', arns['echo-b'])]:
        gateway['Parameters'][key]['AllowedValues'] = [value]
    bucket_template = {'AWSTemplateFormatVersion': '2010-09-09', 'Resources': {'Artifacts': {
        'Type': 'AWS::S3::Bucket', 'DeletionPolicy': 'Retain', 'UpdateReplacePolicy': 'Retain',
        'Properties': {'BucketName': bucket, 'VersioningConfiguration': {'Status': 'Enabled'},
                       'BucketEncryption': {'ServerSideEncryptionConfiguration': [{'ServerSideEncryptionByDefault': {'SSEAlgorithm': 'AES256'}}]},
                       'PublicAccessBlockConfiguration': {k: True for k in ['BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets']}}}}}
    for name, data in [('artifacts.template.json', bucket_template), ('backends.template.json', backend), ('gateways.template.json', gateway)]:
        write(out / name, data)
    upload = {k: {'key': f'{args.prefix}/{k}/{v["sha256"]}.zip', **v} for k, v in {**artifacts, **{s + '-config': v for s, v in config.items()}}.items()}
    write(out / 'uploads.json', upload)
    bparams = {'TrialPrefix': args.prefix, 'ArtifactBucket': bucket, 'BackendKey': upload['backend']['key'],
               'BackendObjectVersion': 'REPLACE_WITH_VERIFIED_OBJECT_VERSION', 'BackendCodeSha256': artifacts['backend']['lambdaCodeSha256']}
    gparams = {'TrialPrefix': args.prefix, 'ArtifactBucket': bucket,
               'EchoAQualifiedArn': arns['echo-a'], 'EchoBQualifiedArn': arns['echo-b']}
    for side in ['Java', 'Rust']:
        s = side.lower()
        gparams.update({side + 'Key': upload[s]['key'], side + 'ObjectVersion': 'REPLACE_WITH_VERIFIED_OBJECT_VERSION',
                        side + 'CodeSha256': artifacts[s]['lambdaCodeSha256'], side + 'ConfigKey': upload[s + '-config']['key'],
                        side + 'ConfigObjectVersion': 'REPLACE_WITH_VERIFIED_OBJECT_VERSION'})
    write(out / 'backends.parameters.json', parameter_rows(bparams))
    write(out / 'gateways.parameters.json', parameter_rows(gparams))
    policies = {name: r['Properties'] for doc in [backend, gateway] for name, r in doc['Resources'].items() if r['Type'] == 'AWS::IAM::Role'}
    write(out / 'iam-scope.json', policies)
    cases = [c for c in inventory() if c['availability'] == 'local']
    write(out / 'cases.json', cases)
    events = []
    for case in cases:
        fixture_path = source / 'fixtures' / (case['id'] + '.json')
        for side in ['java', 'rust']:
            for index, logical in enumerate(case['requests']):
                path = out / 'events' / side / f'{case["id"]}-{index}.json'
                write(path, event(logical, case['id'], side + '-' + uuid.uuid4().hex, 'aws-' + args.prefix))
                events.append({'case': case['id'], 'side': side, 'step': index,
                               'path': str(path), 'sha256': digest(path),
                               'expectationFixture': str(fixture_path), 'expectationFixtureSha256': digest(fixture_path),
                               'expectationField': 'expectJava' if side == 'java' else 'expect'})
    write(out / 'event-plan.json', {'events': events, 'targetBindings': arns,
                                   'expectations': 'unchanged local integration fixtures; qualified deployment target bindings only'})
    review = {'schema': 'lambda-parity-stage3-scope/v1', 'status': 'prepared; not authorized or deployed',
              'account': args.account, 'region': args.region, 'prefix': args.prefix,
              'functions': names, 'proposedBackendQualifiedArns': arns,
              'versionGate': 'new functions only; require outputs exactly :1 and matching CodeSha256 or STOP; never substitute $LATEST/aliases',
              'configurations': config, 'artifacts': artifacts, 'artifactBucket': bucket,
              'stacks': [args.prefix + '-artifacts', args.prefix + '-backends', args.prefix + '-gateways'],
              'logGroups': ['/aws/lambda/' + n for n in names.values()],
              'roles': [n + '-role' for n in names.values()],
              'layers': [args.prefix + '-' + s + '-config:1' for s in ['java', 'rust']],
              'selectedCases': len(cases), 'gatewayInvocations': 44, 'expectedDownstreamExecutions': 42,
              'eventPlanSha256': digest(out / 'event-plan.json'),
              'directBackendContractInvocations': 32, 'totalMaximumPlannedExecutions': 118,
              'concurrency': 1, 'runnerRetries': 0, 'applicationAuthentication': 'disabled; direct Invoke remains IAM-authenticated',
              'localIntegrationEvidence': str(source), 'localIntegrationReportSha256': digest(source / 'integration-report.json'),
              'preserve': ['all accepted gateways/business functions', 'all existing resources', 'original ZIPs/configuration/evidence'],
              'awsCallsPerformed': 0, 'cleanupAuthorized': False,
              'cleanupTargets': {'stacks': [args.prefix + '-gateways', args.prefix + '-backends', args.prefix + '-artifacts'],
                                 'functionsAndTheirVersions': list(names.values()), 'roles': [n + '-role' for n in names.values()],
                                 'retainedLogGroups': ['/aws/lambda/' + n for n in names.values()],
                                 'retainedLayers': [args.prefix + '-' + s + '-config:1' for s in ['java', 'rust']],
                                 'retainedBucketAndObjectVersions': bucket},
              'exclusions': ['error-backend remapping', 'observability promotion', 'denied/delay targets', 'Validator', 'Router rewriting', 'paused workers', 'public ingress'],
              'pendingBeforeExecution': ['owner approval of this exact scope', 'active AWS session and account/region readback',
                                         'fresh-name absence checks', 'actual S3 VersionId readback and replacing explicit placeholders',
                                         'published :1 code/config/role readbacks', 'CloudWatch bounded evidence collection with positive controls'],
              'costEstimateUsd': {'maxPlannedComputeAndRequests': 0.009, 'logIngestAllowance': 0.001,
                                  'artifactStorageApproxMonthly': 0.001,
                                  'assumptions': 'no free tier assumed; backend128MB/5s, gateways512MB/20s; us-east-2 standard Lambda request/GBs estimates; logs/S3 accrue until manual deletion; no ALB/network endpoint charges'}}
    write(out / 'review.json', review)
    lines = ['# Prepared stage 3 scope — owner authorization required', '',
             f'Account {args.account}; region {args.region}; new prefix `{args.prefix}` only.', '',
             'No AWS calls or cleanup are authorized by preparing this package.', '',
             '## Exact function candidates', '']
    lines += ['- `' + n + ':1`' for n in names.values()]
    lines += ['', 'Fresh-name/version/code readbacks must match; stop on drift. No $LATEST or aliases.', '',
              '## Artifacts (SHA-256)', '']
    lines += ['- ' + k + ': `' + v['sha256'] + '`' for k, v in {**artifacts, **{s+' layer':v for s,v in config.items()}}.items()]
    lines += ['', '## Deployment/test gates', '',
              'Review the full IAM documents, templates, uploads and parameter files. Gateway Invoke permission is limited to the two backend qualified ARNs in review.json; each role writes only its own log group.', '',
              'Use an approved AWS session, check account/region and absence of names, create only the artifact/backend/gateway stacks, record actual S3 VersionIds, then verify published :1 hashes and layers before any tests. Parameter placeholders must never be guessed.', '',
              'Run 32 direct backend contract requests separately, then the 44 exact events in event-plan.json once each with no runner retries. Check both independent gateway expectations and outer Invoke outcome. Require 42 downstream distinct backend executions, positive CloudWatch controls and bounded60s evidence collection; incomplete evidence is non-green. Preserve all raw results and failures.', '',
              '## Cleanup and costs', '',
              'Cleanup requires a separate explicit decision. Targets are only cleanupTargets in review.json, including retained logs/layers and the private versioned artifact bucket. No TTL, lifecycle deletion, automatic cleanup, public ingress or VPC is added. Existing resources are preserved.', '',
              'Estimated bounded compute/requests below USD0.009, about USD0.001 log ingestion allowance and USD0.001/month artifact storage; no free-tier credit assumed. Logs/S3 continue accruing until manual deletion. See review.json for assumptions, exact resources and exclusions.', '',
              'See deploy/lambda-parity/runbook.md for the reusable preparation workflow. AWS execution/readback and cleanup each still require their applicable authorization.', '']
    (out / 'AWS-SCOPE.md').write_text('\n'.join(lines))
    print(json.dumps({'out': str(out), 'awsCalls': 0, 'approvalRequired': True, 'selectedCases': len(cases)}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--integration', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--account', default='964637446810')
    parser.add_argument('--region', default='us-east-2')
    parser.add_argument('--prefix', default='parity-s3-20261022-224001')
    parser.add_argument('--backend-binary', type=Path, default=REPO / 'target/x86_64-unknown-linux-musl/release/lambda-trial-backend')
    return prepare(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
