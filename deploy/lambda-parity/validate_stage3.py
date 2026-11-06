#!/usr/bin/env python3
"""Offline structural/identity validation; not AWS ValidateTemplate or cfn-lint."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import zipfile


def read(path):
    return json.loads(path.read_text())


def validate(directory):
    scope = read(directory / 'review.json')
    assert scope['awsCallsPerformed'] == 0 and scope['cleanupAuthorized'] is False
    arns = list(scope['proposedBackendQualifiedArns'].values())
    assert len(arns) == 2 and all(a.endswith(':1') for a in arns)
    plan_path = directory / 'event-plan.json'
    assert hashlib.sha256(plan_path.read_bytes()).hexdigest() == scope['eventPlanSha256']
    events = read(plan_path)['events']
    assert len(events) == 44 and len({(r['side'], r['case'], r['step']) for r in events}) == 44
    for event in events:
        assert hashlib.sha256(Path(event['path']).read_bytes()).hexdigest() == event['sha256']
        assert hashlib.sha256(Path(event['expectationFixture']).read_bytes()).hexdigest() == event['expectationFixtureSha256']
    roles, functions, layers, logs = [], [], [], []
    for file in ['artifacts.template.json', 'backends.template.json', 'gateways.template.json']:
        t = read(directory / file)
        known = set(t.get('Parameters', {})) | set(t['Resources']) | {
            'AWS::Partition', 'AWS::Region', 'AWS::AccountId', 'AWS::StackName'}

        def refs(node):
            if isinstance(node, dict):
                if 'Ref' in node:
                    assert node['Ref'] in known, node['Ref']
                if 'Fn::GetAtt' in node:
                    assert node['Fn::GetAtt'][0] in t['Resources']
                for value in node.values():
                    refs(value)
            elif isinstance(node, list):
                for value in node:
                    refs(value)
        refs(t)
        for key, r in t['Resources'].items():
            kind, p = r['Type'], r['Properties']
            assert kind not in ['AWS::Lambda::Permission', 'AWS::Lambda::Url',
                                'AWS::ApiGateway::RestApi', 'AWS::ElasticLoadBalancingV2::LoadBalancer']
            if kind == 'AWS::Lambda::Function':
                functions.append(key)
                assert 'VpcConfig' not in p and 'endpointOverride' not in json.dumps(p)
                assert p['Architectures'] == ['x86_64'] and p['Runtime'] == 'provided.al2023'
                assert 'S3ObjectVersion' in p['Code']
                assert 'AWS_ACCESS_KEY_ID' not in p.get('Environment', {}).get('Variables', {})
            if kind == 'AWS::IAM::Role':
                roles.append(key)
                assert 'RoleName' in p
                trust = p['AssumeRolePolicyDocument']['Statement']
                assert len(trust) == 1 and trust[0]['Principal'] == {'Service': 'lambda.amazonaws.com'}
                assert 'ManagedPolicyArns' not in p
                for policy in p['Policies']:
                    for statement in policy['PolicyDocument']['Statement']:
                        assert statement['Effect'] == 'Allow'
                        if statement['Action'] == ['lambda:InvokeFunction']:
                            assert statement['Resource'] == arns
                        else:
                            assert set(statement['Action']) == {'logs:CreateLogStream', 'logs:PutLogEvents'}
                            assert 'Fn::GetAtt' in statement['Resource']
            if kind == 'AWS::Logs::LogGroup':
                logs.append(key)
                assert r['DeletionPolicy'] == 'Retain' and 'RetentionInDays' not in p
            if kind == 'AWS::Lambda::LayerVersion':
                layers.append(key)
                assert r['DeletionPolicy'] == 'Retain' and 'S3ObjectVersion' in p['Content']
            if kind == 'AWS::S3::Bucket':
                assert r['DeletionPolicy'] == 'Retain'
                assert all(p['PublicAccessBlockConfiguration'].values())
                assert p['VersioningConfiguration']['Status'] == 'Enabled'
                assert 'LifecycleConfiguration' not in p
                assert p['BucketEncryption']['ServerSideEncryptionConfiguration'][0]['ServerSideEncryptionByDefault']['SSEAlgorithm'] == 'AES256'
    assert len(roles) == len(functions) == len(logs) == 4 and len(layers) == 2
    for record in read(directory / 'uploads.json').values():
        path = Path(record['path'])
        digest = hashlib.sha256(path.read_bytes()).digest()
        assert digest.hex() == record['sha256']
        assert base64.b64encode(digest).decode() == record['lambdaCodeSha256']
    for side in ['java', 'rust']:
        config = directory / (side + '-configuration')
        p = read(config / 'lambda-proxy.yml')
        assert 'endpointOverride' not in p and p['logType'] == 'None'
        assert list(p['functions'].values()) == arns
        assert read(config / 'values.yml')['security.enabled'] is False
        assert read(config / 'values.yml')['unified-security.enabled'] is False
        handler = read(config / 'handler.yml')
        assert len(handler['handlers']) == 1 and handler['handlers'][0].endswith('@proxy')
        with zipfile.ZipFile(directory / (side + '-configuration.zip')) as z:
            for f in config.iterdir():
                assert z.read(f.name) == f.read_bytes()
    return {'valid': True, 'scope': 'offline structural and pinned-artifact validation',
            'functions': len(functions), 'roles': len(roles), 'layers': len(layers),
            'logs': len(logs), 'awsCalls': 0, 'cfnLint': 'unavailable; not run',
            'awsValidateTemplate': 'not called; no AWS authorization'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    result = validate(args.directory)
    with (args.directory / 'template-validation.json').open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps(result))
