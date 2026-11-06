import json
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from integration import InvokeBridge, environment
from timing_integration import check_response
from run import read, HERE


class TimingContract(unittest.TestCase):
    def test_closed_modes_and_timeout_ordering(self):
        c = read(HERE / 'timing-v1.json')
        self.assertEqual(c['fixedDelaysMs'], {'delay-success': 250, 'deadline-delay': 2500, 'lambda-timeout': 6000})
        limits = c['limits']
        self.assertLess(c['fixedDelaysMs']['delay-success'], limits['fastApiCallTimeoutMs'])
        self.assertLess(limits['fastApiCallTimeoutMs'], c['fixedDelaysMs']['deadline-delay'])
        self.assertLess(c['fixedDelaysMs']['deadline-delay'], limits['backendLambdaTimeoutMs'])
        self.assertLess(limits['backendLambdaTimeoutMs'], c['fixedDelaysMs']['lambda-timeout'])
        self.assertLess(c['fixedDelaysMs']['lambda-timeout'], limits['patientApiCallTimeoutMs'])
        self.assertEqual(limits['rustFastIngressTimeoutMs'] - limits['rustResponseReserveMs'], 1100)
        self.assertGreater(limits['rustFastSdkTimeoutMs'], c['fixedDelaysMs']['deadline-delay'])

    def test_timing_opt_in_not_inherited(self):
        with patch.dict('os.environ', {'PARITY_BACKEND_TIMING': 'bounded-v1'}):
            self.assertNotIn('PARITY_BACKEND_TIMING', environment())

    def test_valid_target_iam_denial_never_calls_backend(self):
        class Never:
            def submit(self, *_):
                raise AssertionError('denied backend executed')
        bridge = InvokeBridge({'denied': Never()}, denied_targets={'denied'})
        try:
            req = urllib.request.Request(f'http://127.0.0.1:{bridge.server.server_port}/2015-03-31/functions/denied/invocations', data=b'{}')
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req)
            self.assertEqual(caught.exception.code, 403)
            self.assertEqual(caught.exception.headers['X-Amzn-ErrorType'], 'AccessDeniedException')
            self.assertIsNone(bridge.calls[0]['backendExecutionRequestId'])
            self.assertEqual(bridge.errors, [])
        finally:
            bridge.close()

    def test_independent_error_codes_not_interchangeable(self):
        expected = read(HERE / 'timing-v1.json')['expectations']
        for side, failures in expected.items():
            for mode, want in failures.items():
                response = {'statusCode': want['status'], 'body': json.dumps({'code': want['code']}),
                            'isBase64Encoded': False, 'headers': {'Content-Type': 'application/json'}}
                self.assertEqual(check_response(side, {'failure': mode}, response), [])
                response['body'] = json.dumps({'code': 'wrong'})
                self.assertTrue(check_response(side, {'failure': mode}, response))

    def test_error_privacy_rejected(self):
        response = {'statusCode': 502, 'body': '{"code":"ERR14014","detail":"Task timed out"}',
                    'isBase64Encoded': False, 'headers': {'content-type': 'application/json'}}
        self.assertTrue(check_response('rust', {'failure': 'lambda-timeout'}, response))


if __name__ == '__main__':
    unittest.main()
