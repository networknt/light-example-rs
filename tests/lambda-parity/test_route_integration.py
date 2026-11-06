import unittest
from route_integration import CONTRACT,dispatch_errors,response_errors,target_for
from run import read

class TargetRouteContracts(unittest.TestCase):
    def setUp(self):self.steps={s['id']:s for s in read(CONTRACT)['steps']}
    def call(self,target,path='/parity/a',method='POST'):
        return {'target':target,'event':{'path':path,'httpMethod':method},'signed':True,'invoke':{'logType':'None'},'backendResultKind':'response'}
    def test_known_wildcard_difference_is_explicit(self):
        s=self.steps['deep-parameter-over-wildcard'];self.assertEqual(target_for('java',s),'parity-echo-a');self.assertEqual(target_for('rust',s),'parity-echo-b')
    def test_literal_same_for_both(self):
        s=self.steps['literal-over-parameter'];self.assertEqual(target_for('java',s),target_for('rust',s))
    def test_wrong_target_rejected(self):
        self.assertIn('wrong target',dispatch_errors('rust',self.steps['literal-over-parameter'],[self.call('parity-echo-b')]))
    def test_duplicate_dispatch_rejected(self):
        c=self.call('parity-echo-a');self.assertTrue(dispatch_errors('java',self.steps['literal-over-parameter'],[c,c]))
    def test_rejection_must_have_zero_calls(self):
        self.assertTrue(dispatch_errors('java',self.steps['head-no-get-fallback'],[self.call('parity-echo-a')]))
    def test_method_forwarding_is_exact(self):
        s=self.steps['method-specific-target'];self.assertIn('forwarded path/method',dispatch_errors('rust',s,[self.call('parity-echo-b')]))
    def test_route_miss_not_generic_success(self):
        s=self.steps['get-no-post-fallback'];self.assertTrue(response_errors(s,{'statusCode':201,'body':'{"result":"created"}','headers':{'content-type':'application/json'},'isBase64Encoded':False}))
if __name__=='__main__':unittest.main()
