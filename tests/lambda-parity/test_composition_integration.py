import copy,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from composition_integration import call_errors,plans,prepare,response_errors

class CompositionContracts(unittest.TestCase):
    def setUp(self):
        self.p=next(p for p in plans() if p['name']=='transformers-forward-rust');self.s=self.p['steps'][0]
        self.c={'target':'parity-echo-b','event':{'path':'/changed','body':'transformed','headers':{'x-added':'updated'},'queryStringParameters':{'added':'7'}},'signed':True,'invoke':{'logType':'None'},'backendResultKind':'response'}
    def test_declared_order_passes(self):self.assertEqual(call_errors(self.p,self.s,[self.c],set()),[])
    def test_route_selection_must_follow_transform(self):
        self.c['target']='parity-echo-a';self.assertIn('target selected after transform',call_errors(self.p,self.s,[self.c],set()))
    def test_request_order_is_observable(self):
        self.c['event']['headers']['x-added']='request-before';self.assertIn('request header/transform order',call_errors(self.p,self.s,[self.c],set()))
    def test_zero_dispatch_rejection(self):
        self.assertIn('dispatch count',call_errors(self.p,self.p['steps'][1],[self.c],set()))
    def test_correlation_removed_after_generation(self):
        self.c['event']['headers']['x-correlation-id']='leaked';self.assertIn('correlation should precede removal',call_errors(self.p,self.s,[self.c],set()))
    def test_generated_correlation_cannot_repeat(self):
        p=next(p for p in plans() if p['name']=='headers-reversed-rust');s=p['steps'][1];self.c.update(target='parity-echo-a');self.c['event'].update(path='/x',body='clean',headers={'x-added':'request-before','x-remove':'request-before','x-correlation-id':'old'})
        self.assertIn('fresh generated correlation',call_errors(p,s,[self.c],{'old'}))
    def test_response_order_is_observable(self):
        r={'statusCode':201,'body':'{"result":"created"}','isBase64Encoded':False,'headers':{'x-added':'response-before','x-remove':'response-before'}}
        self.assertIn('response ordering',response_errors(self.p,self.s,r));self.assertIn('response remove ordering',response_errors(self.p,self.s,r))
    def test_native_rejection_not_functional_coverage(self):
        p=plans()[-1];self.assertEqual(p['family'],'service-gate');self.assertTrue(all(s['calls']==0 and s['code']=='ERR11406' for s in p['steps']))
    def test_native_gate_has_explicit_empty_service_registry_and_real_rule_program(self):
        sample={'config':{'files':{'lambda-proxy':{}}}}
        fixture={'ruleConfigurationPair':{'rust':{'rule':{'endpointRules':{},'ruleBodies':{}}}}}
        def load(path):return copy.deepcopy(sample if path.name.startswith('E-03') else fixture)
        with patch('composition_integration.read',side_effect=load),patch('composition_integration.configure',return_value=('java','rust')) as shared:
            prepare(SimpleNamespace(fabric=Path('/fixture-root')),Path('/owned-output'),plans()[-1],'http://127.0.0.1:1',Path('/pinned-bootstrap'))
            files=shared.call_args.args[2]['config']['files']
            self.assertEqual(files['service'],{'singletons':[]})
            self.assertEqual(files['rule'],fixture['ruleConfigurationPair']['rust']['rule'])
            self.assertTrue(files['request-transformer']['enabled'])
if __name__=='__main__':unittest.main()
