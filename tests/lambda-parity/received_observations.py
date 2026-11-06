"""Independent expectations over actual backend logs. No SDK event reconstruction."""
import copy
from pathlib import Path

from run import read

CONTRACT = Path(__file__).with_name('received-contracts.json')


def expected(side, case, step, contract=None):
    contract = contract or read(CONTRACT)
    recipe = contract['cases'][case][step]
    value = copy.deepcopy(contract['profiles'][side])
    if recipe.get('calls', 1) == 0:
        return None
    if 'path' in recipe:
        value['path']['value'] = recipe['path']
    if 'bodyText' in recipe:
        data = recipe['bodyText'].encode('utf-8')
        value['body'] = {'state': 'string', 'utf8Hex': data.hex(), 'byteLength': len(data)}
    value.update(copy.deepcopy(recipe.get(side, {})))
    return value


def compare(records, requests, backend_version='1'):
    """requests are send-ledger IDs only; no expected values come from payloads."""
    contract = read(CONTRACT)
    observed = [r for r in records if r.get('schema') == 'parity-request-observation/v1']
    rows = []
    wanted = {r['attemptId'] for r in requests}
    errors = []
    if len(wanted) != len(requests):
        errors.append('duplicate send-ledger attempt')
    if any(r.get('attemptId') not in wanted for r in observed):
        errors.append('unexpected attempt observation')
    for request in requests:
        side, case, step = request['side'], request['id'], request['step']
        want = expected(side, case, step, contract)
        got = [r for r in observed if r.get('attemptId') == request['attemptId']]
        failures = []
        if want is None and request['backendExecutionRequestId'] is not None:
            failures.append({'field': 'zeroDispatch', 'expected': None,
                             'actual': request['backendExecutionRequestId']})
        if len(got) != (0 if want is None else 1):
            failures.append({'field': 'observationCount', 'expected': 0 if want is None else 1, 'actual': len(got)})
        if want is not None and len(got) == 1:
            row = got[0]
            if row.get('observation') != want:
                failures.append({'field': 'observation', 'expected': want, 'actual': row.get('observation')})
            identity = 'echo-b' if want['path']['value'] == '/parity/b' else 'echo-a'
            for key, value in [('runId', request['runId']), ('caseId', case),
                               ('executionRequestId', request['backendExecutionRequestId']),
                               ('backendIdentity', identity), ('backendVersion', backend_version),
                               ('phase', 'received-event')]:
                if row.get(key) != value:
                    failures.append({'field': key, 'expected': value, 'actual': row.get(key)})
        rows.append({'side': side, 'id': case, 'step': step, 'passed': not failures, 'errors': failures,
                     'coverage': 'zero-dispatch' if want is None else 'backend-received-event'})
    ids = [r.get('executionRequestId') for r in observed]
    if len(ids) != len(set(ids)):
        errors.append('duplicate execution observation')
    return {'schema': 'parity-received-comparison/v1', 'scope': 'actual backend-received events; not raw SDK wire',
            'passed': not errors and bool(rows) and all(r['passed'] for r in rows), 'errors': errors,
            'observations': len(observed), 'requestChecks': len(rows), 'rows': rows,
            'jwksCounts': 'outside proxy-only observation profile'}
