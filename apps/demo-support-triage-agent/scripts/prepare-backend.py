#!/usr/bin/env python3
"""Derive backend identity from an operator-exported activated A2A values JSON."""
import argparse
import json
import os
from pathlib import Path
from uuid import UUID


def prepare(values, agent_ref, host_id):
    if not isinstance(values, dict):
        raise ValueError('export must be a flat JSON object')
    # Config Server exports qualify keys with the config name; raw snapshot
    # property exports do not. Accept either complete form, never a mixture.
    qualified = any(key.startswith('a2a.') for key in values)
    prefix = 'a2a.' if qualified else ''
    if qualified and any(key.startswith(('a2aPolicy.', 'runtimePolicy.')) for key in values):
        raise ValueError('do not mix a2a-qualified and raw snapshot property keys')
    environment = values.get(prefix + 'runtimePolicy.envTag')
    if not isinstance(environment, str) or not environment.strip():
        raise ValueError('export must explicitly include runtimePolicy.envTag in its selected key form')
    raw = values.get(prefix + 'a2aPolicy.bindings')
    bindings = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(bindings, list):
        raise ValueError('export must contain a2aPolicy.bindings')
    matches = [item for item in bindings if item.get('agentRef') == agent_ref]
    if len(matches) != 1:
        raise ValueError('select exactly one published agentRef')
    binding = matches[0]
    if binding['backendKind'] != 'EXTERNAL_SIDECAR':
        raise ValueError('this demo requires EXTERNAL_SIDECAR')
    transport = binding['backendTransport']
    if transport['origin'] != 'http://127.0.0.1:9010/':
        raise ValueError('publish the demo loopback origin http://127.0.0.1:9010/')
    capabilities = transport['capabilities']
    if capabilities != {'contractVersion': 'light-a2a-backend/v1', 'streaming': False,
                        'cancellation': False, 'statusReconciliation': True,
                        'acceptedContentModes': ['text/plain'], 'maximumArtifactBytes': 65536}:
        raise ValueError('published capabilities do not match this demo')
    if 'support-triage' not in binding['allowedSkillIds']:
        raise ValueError('publish the support-triage skill alias')
    key_file = transport['contextKeyFile']
    if key_file != '/run/secrets/triage-context-key':
        raise ValueError('publish contextKeyFile=/run/secrets/triage-context-key')
    return {'audience': transport['audience'], 'hostId': str(UUID(host_id)),
            'environment': environment,
            'agentRef': agent_ref, 'bindingId': str(UUID(binding['bindingId'])),
            'publicationId': str(UUID(binding['publicationId'])),
            'policyDigest': binding['policyDigest'],
            'dataBoundaryDigest': transport['dataBoundaryDigest'],
            'contextKeyFile': key_file, 'stateDirectory': '/app/state'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--values', type=Path, required=True)
    parser.add_argument('--agent-ref', default='support-triage')
    parser.add_argument('--host-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = prepare(json.loads(args.values.read_text()), args.agent_ref, args.host_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        os.chmod(args.output, 0o600)
        json.dump(config, output, indent=2)
        output.write('\n')
    print('Wrote backend identity. Mount the matching context key separately.')


if __name__ == '__main__':
    main()
