import copy,unittest
from types import SimpleNamespace
from unittest.mock import patch
from header_transformer_integration import SCOPE,candidate_pins,errors_for,read

class HeaderTransformerContracts(unittest.TestCase):
    def setUp(self):
        self.step={'id':'source-present','status':201,'backendExecutions':1,'body':'plain'}
        self.response={'statusCode':201,'body':'{"result":"created"}','isBase64Encoded':False,'headers':{'x-added':'response-rule'}}
        self.call={'target':'parity-echo-a','event':{'path':'/x','body':'plain','headers':{'x-added':'request-rule','x-copied':'request-source','x-correlation-id':'fresh'}},'signed':True,'invoke':{'logType':'None'},'backendResultKind':'response'}
    def check(self,profile='forward',seen=None):return errors_for(profile,self.step,self.response,[self.call],seen or set())
    def test_actual_order_and_source_copy(self):self.assertEqual(self.check(),[])
    def test_missing_source_after_reversed_warm_request(self):
        self.step['id']='source-missing';self.response['headers']['x-added']='response-before'
        self.call['event']['headers'].update({'x-added':'request-before','x-remove':'request-source','x-copied':'old'})
        self.assertIn('copy or warm isolation',self.check('reversed'))
    def test_order_is_not_normalized(self):
        self.call['event']['headers']['x-added']='request-before';self.assertIn('request ordering',self.check())
    def test_response_order_is_not_normalized(self):
        self.response['headers']['x-added']='response-before';self.assertIn('response ordering',self.check())
    def test_zero_dispatch_is_enforced(self):
        self.step['backendExecutions']=0;self.assertIn('dispatch count',self.check())
    def test_fresh_exchange_correlation(self):self.assertIn('fresh correlation',self.check(seen={'fresh'}))
    def test_candidate_is_separate_opt_in(self):
        args=SimpleNamespace(java_zip=SCOPE/'candidate-build/java-native-header-transformer-candidate.zip',candidate_manifest=SCOPE/'candidate-build/candidate-manifest.json')
        self.assertEqual(candidate_pins(args)['java'],read(args.candidate_manifest)['zipSha256'])
    def test_unknown_scope_rejected(self):
        m=read(SCOPE/'candidate-build/candidate-manifest.json');m['reviewZipSha256']='unapproved'
        args=SimpleNamespace(java_zip=SCOPE/'candidate-build/java-native-header-transformer-candidate.zip',candidate_manifest=SCOPE/'candidate-build/candidate-manifest.json')
        with patch('header_transformer_integration.read',return_value=m),self.assertRaises(AssertionError):candidate_pins(args)
if __name__=='__main__':unittest.main()
