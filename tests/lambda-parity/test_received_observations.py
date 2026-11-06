import copy
import unittest

from received_observations import compare, expected


class ReceivedObservationContract(unittest.TestCase):
    def sample(self):
        request = {'side': 'java', 'id': 'PARITY-created', 'step': 0, 'runId': 'run',
                   'attemptId': 'attempt', 'backendExecutionRequestId': 'execution'}
        record = {'schema': 'parity-request-observation/v1', 'phase': 'received-event',
                  'runId': 'run', 'caseId': 'PARITY-created', 'attemptId': 'attempt',
                  'executionRequestId': 'execution', 'backendIdentity': 'echo-a', 'backendVersion': '1',
                  'observation': {'httpMethod': {'state': 'value', 'value': 'POST'},
                                  'path': {'state': 'value', 'value': '/parity/a'},
                                  'headers': {'state': 'absent'},
                                  'multiValueHeaders': {'state': 'object', 'values': {}},
                                  'queryStringParameters': {'state': 'absent'},
                                  'multiValueQueryStringParameters': {'state': 'object', 'values': {}},
                                  'body': {'state': 'absent'},
                                  'isBase64Encoded': {'state': 'value', 'value': False}}}
        return request, record

    def test_actual_records_required_and_metadata_correlated(self):
        request, record = self.sample()
        self.assertTrue(compare([record], [request])['passed'])
        self.assertFalse(compare([], [request])['passed'])
        self.assertFalse(compare([record, copy.deepcopy(record)], [request])['passed'])
        self.assertFalse(compare([record], [request, copy.deepcopy(request)])['passed'])
        for field in ['runId', 'attemptId', 'caseId', 'backendIdentity', 'backendVersion', 'executionRequestId']:
            bad = copy.deepcopy(record)
            bad[field] = 'wrong'
            self.assertFalse(compare([bad], [request])['passed'], field)

    def test_null_does_not_replace_native_absence(self):
        request, record = self.sample()
        record['observation']['body'] = {'state': 'null'}
        result = compare([record], [request])
        self.assertFalse(result['passed'])
        self.assertEqual(result['rows'][0]['errors'][0]['actual']['body'], {'state': 'null'})
        self.assertEqual(expected('java', 'PARITY-created', 0)['body'], {'state': 'absent'})

    def test_independent_ordered_query_and_header_contracts(self):
        java = expected('java', 'PARITY-forwarding', 0)
        rust = expected('rust', 'PARITY-forwarding', 0)
        self.assertEqual(java['multiValueQueryStringParameters']['values']['q']['value'], ['a+b', '%2B', '雪', ''])
        self.assertEqual(rust['multiValueQueryStringParameters']['values']['q']['value'], ['a+b', '+', '雪', ''])
        self.assertEqual(rust['headers']['values']['x-synthetic']['value'], 'second')
        self.assertEqual(java['body'], {'state': 'string', 'utf8Hex': '73796e746865746963', 'byteLength': 9})
        request, record = self.sample()
        request['id'] = record['caseId'] = 'PARITY-forwarding'
        record['observation'] = copy.deepcopy(java)
        self.assertTrue(compare([record], [request])['passed'])
        record['observation']['multiValueQueryStringParameters']['values']['q']['value'].reverse()
        self.assertFalse(compare([record], [request])['passed'])

    def test_missing_and_unexpected_records_never_count_as_zero_dispatch(self):
        request, record = self.sample()
        request.update(id='PARITY-unknown-route-recovery', step=1, backendExecutionRequestId=None)
        self.assertTrue(compare([], [request])['passed'])
        request['backendExecutionRequestId'] = 'unexpected-dispatch'
        self.assertFalse(compare([], [request])['passed'])
        request['backendExecutionRequestId'] = None
        self.assertFalse(compare([record], [request])['passed'])
        self.assertFalse(compare([], [])['passed'])


if __name__ == '__main__':
    unittest.main()
