import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from integration import InvokeBridge, environment, observation, unpack


class IntegrationContract(unittest.TestCase):
    def test_credentials_and_proxies_are_not_inherited(self):
        with patch.dict(os.environ, {'AWS_SESSION_TOKEN': 'private', 'AWS_PROFILE': 'private',
                                     'PARITY_BACKEND_OBSERVATIONS': 'synthetic-v1',
                                     'HTTPS_PROXY': 'https://not-owned.invalid',
                                     'LIGHT_LAMBDA_ALLOW_LOGGER_SET': '1'}):
            env = environment()
        self.assertNotIn('AWS_SESSION_TOKEN', env)
        self.assertNotIn('AWS_PROFILE', env)
        self.assertNotIn('HTTPS_PROXY', env)
        self.assertNotIn('LIGHT_LAMBDA_ALLOW_LOGGER_SET', env)
        self.assertNotIn('PARITY_BACKEND_OBSERVATIONS', env)
        self.assertEqual(env['AWS_ACCESS_KEY_ID'], 'synthetic')

    def test_response_collection_preserves_case_multiplicity_and_body(self):
        raw = {'statusCode': 200, 'headers': {'Content-Type': 'application/json'},
               'multiValueHeaders': {'Set-Cookie': ['b', 'a']}, 'body': 'AP9B',
               'isBase64Encoded': True}
        value = observation(raw, [])
        self.assertEqual(value['headers'], [['Content-Type', 'application/json'],
                                           ['Set-Cookie', 'b'], ['Set-Cookie', 'a']])
        self.assertEqual(value['body'], 'AP9B')
        self.assertTrue(value['bodyBase64'])
        self.assertEqual(value['responseMaps']['multiValueHeaders'], raw['multiValueHeaders'])

    def test_package_drift_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'unapproved.zip').write_bytes(b'not-approved')
            with self.assertRaisesRegex(ValueError, 'ZIP drift'):
                unpack(path / 'unapproved.zip', path / 'extracted', 'rust')
            self.assertFalse((path / 'extracted').exists())

    def test_bridge_passes_actual_bytes_and_distinct_request_identity(self):
        # This is a transport unit stub, not the real-backend qualification.
        class Stub:
            def submit(self, event, ident):
                self.event, self.ident = event, ident
                return {'payload': b'{ "statusCode": 201, "body": "opaque" }\n', 'kind': 'response'}
        stub = Stub()
        bridge = InvokeBridge({'parity-echo-a': stub})
        try:
            request = urllib.request.Request(
                f'http://127.0.0.1:{bridge.server.server_port}/2015-03-31/functions/parity-echo-a/invocations',
                data=b'{"body":"synthetic"}', headers={'X-Amz-Log-Type': 'None',
                                                         'Authorization': 'AWS4-HMAC-SHA256 synthetic'})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.read(), b'{ "statusCode": 201, "body": "opaque" }\n')
                self.assertNotEqual(response.headers['X-Amzn-RequestId'], stub.ident)
            self.assertEqual(stub.event, {'body': 'synthetic'})
            self.assertEqual(len(bridge.calls), 1)
            self.assertEqual(bridge.calls[0]['backendExecutionRequestId'], stub.ident)
            self.assertEqual(bridge.errors, [])
        finally:
            bridge.close()

    def test_missing_response_fields_are_not_repaired(self):
        with self.assertRaises(KeyError):
            observation({'body': 'invalid'}, [])


if __name__ == '__main__':
    unittest.main()
