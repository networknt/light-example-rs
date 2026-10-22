import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from run import HERE, fixture, event, inventory, read, summarize, write, digest, main


class SuiteContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = read(HERE.parents[2] / 'light-fabric-light-lambda/tests/serverless-conformance/fixtures/v1/e/E-03-response-off-0-multi-v1.json')

    def test_paired_builder_preserves_presence_order_and_precision(self):
        request = {'mode': 'empty', 'body': '{"n":9007199254740993}',
                   'query': {'q': ['%252B', '%2B', '+', '']}}
        raw = event(request, 'case', 'attempt')
        self.assertEqual(raw['body'], request['body'])
        self.assertEqual(raw['multiValueQueryStringParameters']['q'], request['query']['q'])
        self.assertNotIn('body', event({'mode': 'empty'}, 'case', 'attempt'))
        self.assertIsNone(event({'mode': 'empty', 'body': None}, 'case', 'attempt')['body'])

    def test_existing_query_difference_is_exact_and_only_decodes_once(self):
        case = {'id': 'case', 'reason': 'contract', 'requests': [{
            'mode': 'empty', 'query': {'q': ['%252B', '%2B', '+', '']}}]}
        f = fixture(case, self.template)
        self.assertEqual(f['expect']['backendCalls'][0]['event']['multiValueQueryStringParameters']['q'], ['%2B', '+', '+', ''])
        self.assertEqual(f['expectJava']['backendCalls'][0]['event']['multiValueQueryStringParameters']['q'], ['%252B', '%2B', '+', ''])

    def test_unsupported_mode_cannot_be_silently_run(self):
        with self.assertRaises(ValueError):
            fixture({'id': 'case', 'reason': 'contract', 'requests': [{'mode': 'unknown'}]}, self.template)

    def test_missing_evidence_and_selected_unavailable_are_non_green(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            write(out / 'manifest.json', {'selected': 1, 'total': 1,
                  'rows': [{'id': 'validator', 'selected': True, 'outcome': 'unavailable'}]})
            self.assertFalse(summarize(out)['green'])

    def test_changed_fixture_is_failure_even_with_cached_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            write(out / 'fixtures/case.json', {'before': True})
            sha = digest(out / 'fixtures/case.json')
            write(out / 'manifest.json', {'selected': 1, 'total': 1, 'rows': [{
                'id': 'case', 'selected': True, 'outcome': 'blocked',
                'fixture': 'case.json', 'fixtureSha256': sha}]})
            write(out / 'compare/coverage.json', {'rows': [{'id': 'case', 'outcome': 'pass'}]})
            (out / 'fixtures/case.json').write_text('{}')
            report = summarize(out)
            self.assertFalse(report['green'])
            self.assertEqual(report['counts']['fail'], 1)

    def test_inventory_separates_local_and_unavailable(self):
        cases = inventory()
        self.assertEqual(len({c['id'] for c in cases}), len(cases))
        self.assertTrue(any(c['availability'] == 'unavailable' for c in cases))

    def test_nested_reports_are_sealed_and_backend_count_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            write(out / 'fixtures/case.json', {'synthetic': True})
            write(out / 'manifest.json', {'selected': 1, 'total': 1, 'rows': [{
                'id': 'case', 'selected': True, 'outcome': 'blocked',
                'fixture': 'case.json', 'fixtureSha256': digest(out / 'fixtures/case.json')}]})
            write(out / 'compare/coverage.json', {'rows': [{'id': 'case', 'outcome': 'pass'}]})
            backend = {'passed': True, 'rows': [{'requests': 16}]}
            write(out / 'backend/report.json', backend)
            (out / 'backend/report.md').write_text('nested evidence\n')
            (out / 'report.md').write_text('generated top-level report\n')
            report = summarize(out)
            self.assertTrue(report['green'])
            self.assertIn('backend/report.json', report['evidenceSha256'])
            self.assertIn('backend/report.md', report['evidenceSha256'])
            self.assertNotIn('report.md', report['evidenceSha256'])
            write(out / 'report.json', report)
            self.assertNotIn('report.json', summarize(out)['evidenceSha256'])
            backend['rows'][0]['requests'] = 999
            (out / 'backend/report.json').write_text(json.dumps(backend))
            with patch('sys.argv', ['run.py', 'compare', '--out', str(out)]):
                with self.assertRaisesRegex(ValueError, 'saved evidence changed: backend/report.json'):
                    main()

    def test_iac_has_no_public_ingress_and_only_qualified_invoke_targets(self):
        template = read(HERE.parents[1] / 'deploy/lambda-parity/template.yaml')
        resources = template['Resources']
        self.assertFalse(any(r['Type'] in ['AWS::Lambda::Url', 'AWS::Lambda::Permission', 'AWS::ApiGateway::RestApi'] for r in resources.values()))
        for name in ['JavaRole', 'RustRole']:
            statements = resources[name]['Properties']['Policies'][0]['PolicyDocument']['Statement']
            invoke = next(s for s in statements if s['Action'] == ['lambda:InvokeFunction'])
            self.assertEqual(invoke['Resource'], [{'Ref': 'EchoAQualifiedArn'}, {'Ref': 'EchoBQualifiedArn'}])


if __name__ == '__main__':
    unittest.main()
