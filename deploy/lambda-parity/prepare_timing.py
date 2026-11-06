#!/usr/bin/env python3
"""Offline-only, exact new-resource scope for the IAM/timing batch. No AWS calls."""
import argparse
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'tests/lambda-parity'))
from run import ARTIFACTS, HERE, digest, read, write, event
from integration import JAVA_ZIP, RUST_ZIP, PINNED, candidate_pins

ACCOUNT = '964637446810'
REGION = 'us-east-2'
PREFIX = 'parity-s4-20261023'
BUCKET = 'll-parity-s3-20261022-224001-964637446810-us-east-2'
ECHO = 'arn:aws:lambda:us-east-2:964637446810:function:parity-s3-20261022-224001-echo-a:2'


def identity(path):
    raw = path.read_bytes()
    import hashlib
    h = hashlib.sha256(raw).digest()
    return {'path': str(path), 'sha256': h.hex(), 'lambdaCodeSha256': base64.b64encode(h).decode(),
            'bytes': len(raw), 'key': PREFIX + '/' + path.stem + '/' + h.hex() + '.zip'}


def add_function(document, logical, name, code, env, timeout, memory, invoke=(), layer=None):
    resources = document['Resources']
    resources[logical + 'Logs'] = {'Type': 'AWS::Logs::LogGroup', 'DeletionPolicy': 'Retain',
        'UpdateReplacePolicy': 'Retain', 'Properties': {'LogGroupName': '/aws/lambda/' + name}}
    statements = [{'Effect': 'Allow', 'Action': ['logs:CreateLogStream', 'logs:PutLogEvents'],
                   'Resource': {'Fn::GetAtt': [logical + 'Logs', 'Arn']}}]
    if invoke:
        statements.append({'Effect': 'Allow', 'Action': ['lambda:InvokeFunction'], 'Resource': list(invoke)})
    resources[logical + 'Role'] = {'Type': 'AWS::IAM::Role', 'Properties': {
        'RoleName': name + '-role',
        'AssumeRolePolicyDocument': {'Version': '2012-10-17', 'Statement': [
            {'Effect': 'Allow', 'Principal': {'Service': 'lambda.amazonaws.com'}, 'Action': 'sts:AssumeRole'}]},
        'Policies': [{'PolicyName': 'TrialOwnResources', 'PolicyDocument': {'Version': '2012-10-17', 'Statement': statements}}]}}
    document['Parameters'][logical + 'ObjectVersion'] = {'Type': 'String', 'MinLength': 1}
    if code.get('versionId'):
        document['Parameters'][logical + 'ObjectVersion']['AllowedValues'] = [code['versionId']]
    properties = {'FunctionName': name, 'Runtime': 'provided.al2023', 'Architectures': ['x86_64'],
        'Handler': 'com.networknt.aws.lambda.app.LambdaApp::handleRequest' if logical.startswith('Java') else 'bootstrap',
        'Code': {'S3Bucket': BUCKET, 'S3Key': code['key'], 'S3ObjectVersion': {'Ref': logical + 'ObjectVersion'}},
        'Role': {'Fn::GetAtt': [logical + 'Role', 'Arn']}, 'MemorySize': memory, 'Timeout': timeout,
        'Environment': {'Variables': env}, 'LoggingConfig': {'LogFormat': 'Text', 'LogGroup': '/aws/lambda/' + name}}
    if layer:
        document['Parameters'][logical + 'LayerObjectVersion'] = {'Type': 'String', 'MinLength': 1}
        resources[logical + 'Layer'] = {'Type': 'AWS::Lambda::LayerVersion', 'DeletionPolicy': 'Retain',
            'UpdateReplacePolicy': 'Retain', 'Properties': {'LayerName': name + '-config',
                'CompatibleArchitectures': ['x86_64'], 'CompatibleRuntimes': ['provided.al2023'],
                'Content': {'S3Bucket': BUCKET, 'S3Key': layer['key'],
                            'S3ObjectVersion': {'Ref': logical + 'LayerObjectVersion'}}}}
        properties['Layers'] = [{'Ref': logical + 'Layer'}]
    resources[logical] = {'Type': 'AWS::Lambda::Function', 'DeletionPolicy': 'Retain',
                         'UpdateReplacePolicy': 'Retain', 'Properties': properties}
    resources[logical + 'Version'] = {'Type': 'AWS::Lambda::Version', 'DeletionPolicy': 'Retain',
        'UpdateReplacePolicy': 'Retain', 'Properties': {'FunctionName': {'Ref': logical}, 'CodeSha256': code['lambdaCodeSha256']}}
    document['Outputs'][logical + 'QualifiedArn'] = {'Value': {'Ref': logical + 'Version'}}


def prepare(args):
    pins = candidate_pins(args)
    out = args.out.resolve()
    assert out.is_relative_to(ARTIFACTS.resolve())
    out.mkdir(parents=True, exist_ok=False)
    integration_dir = args.evidence / args.integration_name
    integration = read(integration_dir / 'report.json')
    direct = read((args.direct_evidence or args.evidence / 'final-direct') / 'report.json')
    old = read((args.preserved_evidence or args.evidence / 'final-preserved-14') / 'integration-report.json')
    assert direct['green'] and old['green'] and integration['gatewaySteps'] == 18
    assert all(integration['backendBinarySha256'] == r for r in [digest(args.backend_binary), direct['backendSha256'], old['backendBinarySha256']])
    spec = importlib.util.spec_from_file_location('timing_pack', REPO.parent / 'light-fabric-light-lambda/apps/light-lambda/scripts/package_baseline.py')
    pack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pack)
    backend = out / 'backend-bootstrap.zip'
    pack.canonical_zip(backend, {'bootstrap': args.backend_binary.read_bytes()}, {'bootstrap': 0o755}, 1792708800)
    artifacts = {'backend': identity(backend), 'java': identity(args.java_zip), 'rust': identity(RUST_ZIP)}
    assert all(artifacts[s]['sha256'] == pins[s] == integration['gatewayZipSha256'][s] == old['gatewayZipSha256'][s] for s in ['java', 'rust'])
    preserved = {r['ParameterKey']: r['ParameterValue'] for r in read(
        ARTIFACTS / 'parity-received-aws-20261023T001101Z/aws-final/baseline/gateways-resolved-parameters.json')}
    for side in ['java', 'rust']:
        if pins[side] == PINNED[side]:
            artifacts[side].update(key=preserved[side.title() + 'Key'],
                                   versionId=preserved[side.title() + 'ObjectVersion'], reuseExistingObject=True)
    targets = {name: f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:{PREFIX}-{name}:1' for name in ['delay', 'denied']}
    names, layers = {}, {}
    for side in ['java', 'rust']:
        for profile in ['fast', 'patient']:
            key = side + '-' + profile
            source = integration_dir / side / profile / ('java-configuration-source' if side == 'java' else 'configuration-source')
            dest = out / (key + '-configuration')
            shutil.copytree(source, dest)
            proxy = read(dest / 'lambda-proxy.yml')
            proxy.pop('endpointOverride')
            proxy['region'] = REGION
            proxy['functions'] = {'/parity/a@post': ECHO, '/parity/denied@post': targets['denied'], '/parity/delay@post': targets['delay']}
            (dest / 'lambda-proxy.yml').write_text(json.dumps(proxy, indent=2) + '\n')
            values = read(dest / 'values.yml')
            values['light-lambda.accountId'] = ACCOUNT
            (dest / 'values.yml').write_text(json.dumps(values, indent=2) + '\n')
            layer = out / (key + '-configuration.zip')
            if side == 'rust':
                from unittest.mock import patch
                with patch.dict(os.environ, {'SOURCE_DATE_EPOCH': '1792708800'}):
                    report = pack.layer(dest, layer, integration_dir / 'rust-package/bootstrap')
            else:
                pack.canonical_zip(layer, {p.name: p.read_bytes() for p in sorted(dest.iterdir())}, {}, 1792708800)
                report = {'localNativeInit': str(source), 'status': 'real packaged local Init/service exercised'}
            layers[key] = identity(layer)
            write(out / (key + '-layer-validation.json'), report)
            names[key] = PREFIX + '-' + key + '-gateway'
    backends = {'AWSTemplateFormatVersion': '2010-09-09', 'Parameters': {}, 'Resources': {}, 'Outputs': {}}
    gateways = copy.deepcopy(backends)
    for name in ['denied', 'delay']:
        env = {'PARITY_BACKEND_IDENTITY': name}
        if name == 'delay':
            env['PARITY_BACKEND_TIMING'] = 'bounded-v1'
        add_function(backends, name.title(), PREFIX + '-' + name, artifacts['backend'], env, 4, 128)
    for key, name in names.items():
        side, profile = key.split('-')
        logical = side.title() + profile.title()
        # Reuse the already AWS-qualified bootstrap environment on both sides.
        # Lambda supplies reserved _HANDLER from Properties.Handler itself.
        env = {'LIGHT_LAMBDA_CONFIG_DIR': '/opt',
               'LIGHT_LAMBDA_GATEWAY_ARN': f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:{name}'}
        add_function(gateways, logical, name, artifacts[side], env, 20, 512,
                     invoke=[ECHO, targets['delay']], layer=layers[key])
    for suffix, document in [('backends', backends), ('gateways', gateways)]:
        write(out / (suffix + '.template.json'), document)
        write(out / (suffix + '.parameters.json'), [
            {'ParameterKey': k, 'ParameterValue': v['AllowedValues'][0] if 'AllowedValues' in v else 'REPLACE_WITH_VERIFIED_S3_VERSION_ID'}
            for k, v in document['Parameters'].items()])
    contract = read(HERE / 'timing-v1.json')
    write(out / 'timing-contract.json', contract)
    events = []
    for side in ['java', 'rust']:
        for case in contract['cases']:
            for index, step in enumerate(case['steps']):
                path = {'echo-a': '/parity/a', 'delay': '/parity/delay', 'denied': '/parity/denied'}[step['target']]
                dest = out / 'events' / side / (case['id'] + '-' + str(index) + '.json')
                write(dest, event({'path': path, 'mode': step['mode']}, case['id'], side + '-' + uuid_hex(), 'aws-timing-trial'))
                events.append({'side': side, 'profile': case['profile'], 'id': case['id'], 'step': index,
                               'path': str(dest), 'sha256': digest(dest), 'expected': step})
    write(out / 'event-plan.json', {'events': events, 'primingRequests': 4, 'selectedRequests': 18,
                                   'expectedSelectedEntries': 16, 'expectedSelectedCompletions': 14})
    broad_path = args.native_summary or args.evidence / 'maven-final-summary.json'
    broad = read(broad_path) if broad_path.exists() else None
    broader_ok = broad is not None and broad['failures'] == 0 and broad['errors'] == 0
    qualified = integration['green'] and integration['gatewayExpectationPasses'] == 18 and broader_ok
    review = {'schema': 'parity-iam-timing-scope/v1', 'deploymentReady': qualified,
        'deploymentAuthorized': False, 'awsCalls': 0,
        'account': ACCOUNT, 'region': REGION, 'prefix': PREFIX,
        'stacks': [PREFIX + '-backends', PREFIX + '-gateways'], 'existingArtifactBucket': BUCKET,
        'artifacts': artifacts, 'layers': layers, 'proposedNewTargetVersions': targets,
        'proposedNewGatewayVersions': {k: f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:{v}:1' for k, v in names.items()},
        'gatewayInvokeAllowlist': [ECHO, targets['delay']], 'deniedExcluded': targets['denied'],
        'existingGatewayRoles': 'unchanged; denied target remains excluded from both version-2 parity gateway roles',
        'localResults': {'direct': direct['passes'], 'gatewaySteps': 18, 'gatewayPasses': integration['gatewayExpectationPasses'],
                         'preservedCases': old['selected'], 'preservedSteps': old['gatewaySteps']},
        'executionBlocker': (None if qualified else
            'Timing expectations remain non-green; preserve failures and expectations.' if not integration['green'] else
            'Broader native checks are missing/non-green; retain the pre-mitigation D03 assertion and obtain explicit versioned characterization disposition before claiming readiness.'),
        'broaderNativeSummarySha256': digest(broad_path) if broad is not None else None,
        'broaderNativeContract': broad.get('nativeContract', 'original') if broad else None,
        'limits': contract['limits'], 'runnerConcurrency': 1, 'retries': 0,
        'plannedDirectChecks': 4, 'plannedGatewayRequestsIncludingPriming': 22,
        'plannedDownstreamIncludingPriming': {'entries': 20, 'completions': 18},
        'totalPlannedLambdaExecutions': 46,
        'cleanupAuthorized': False, 'cleanupOwnership': {'newFunctions': [PREFIX + '-' + n for n in ['denied', 'delay']] + list(names.values()),
            'newRoles': [PREFIX + '-' + n + '-role' for n in ['denied', 'delay']] + [n + '-role' for n in names.values()],
            'newLogGroups': ['/aws/lambda/' + n for n in [PREFIX + '-denied', PREFIX + '-delay'] + list(names.values())],
            'newLayerVersions': [n + '-config:1' for n in names.values()],
            'newObjectsOnly': [v['key'] for v in [artifacts['backend'], artifacts['java'], *layers.values()] if not v.get('reuseExistingObject')],
            'preserveBucketAndVersion2Resources': True},
        'exclusions': ['AWS deployment before approval', 'resource deletion', 'SDK-wire qualification', 'JWKS',
                       'deferred handlers', 'Validator', 'Router rewriting', 'paused experiments', 'accepted deployment changes']}
    write(out / 'review.json', review)
    validate(out)
    print(json.dumps({'out': str(out), 'deploymentReady': qualified, 'deploymentAuthorized': False, 'localPasses': integration['gatewayExpectationPasses'], 'awsCalls': 0}))


def uuid_hex():
    import uuid
    return uuid.uuid4().hex


def validate(out):
    review = read(out / 'review.json')
    for suffix in ['backends', 'gateways']:
        doc = read(out / (suffix + '.template.json'))
        params = read(out / (suffix + '.parameters.json'))
        assert set(doc['Parameters']) == {p['ParameterKey'] for p in params}
        text = json.dumps(doc)
        for key in doc['Parameters']:
            assert '"Ref": "' + key + '"' in text
        for resource in doc['Resources'].values():
            assert resource['Type'] in ['AWS::IAM::Role', 'AWS::Logs::LogGroup', 'AWS::Lambda::Function', 'AWS::Lambda::LayerVersion', 'AWS::Lambda::Version']
            props = resource['Properties']
            if resource['Type'] == 'AWS::IAM::Role':
                assert 'ManagedPolicyArns' not in props
                statements = props['Policies'][0]['PolicyDocument']['Statement']
                invoke = [s for s in statements if s['Action'] == ['lambda:InvokeFunction']]
                assert (invoke[0]['Resource'] if invoke else []) == (review['gatewayInvokeAllowlist'] if suffix == 'gateways' else [])
                assert review['deniedExcluded'] not in json.dumps(statements)
            if resource['Type'] == 'AWS::Lambda::Function':
                assert 'VpcConfig' not in props and 'ReservedConcurrentExecutions' not in props
    write(out / 'local-validation.json', {'passed': True, 'structuralAndIAM': True, 'awsValidation': 'not called',
          'cfnLint': 'pending availability check; not implied by structural validation',
          'resourceCounts': {s: len(read(out / (s + '.template.json'))['Resources']) for s in ['backends', 'gateways']}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--integration-name', default='request-budget-integration')
    parser.add_argument('--direct-evidence', type=Path)
    parser.add_argument('--preserved-evidence', type=Path)
    parser.add_argument('--java-zip', type=Path, default=JAVA_ZIP)
    parser.add_argument('--candidate-manifest', type=Path)
    parser.add_argument('--native-summary', type=Path,
                        help='explicit qualified native test-contract summary; original evidence remains unchanged')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--backend-binary', type=Path, default=REPO / 'target/x86_64-unknown-linux-musl/release/lambda-trial-backend')
    prepare(parser.parse_args())
