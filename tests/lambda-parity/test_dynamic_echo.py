import copy,json,unittest
from dynamic_echo import CONTRACT,expected_echo,expected_received,response_errors
from run import read

class DynamicEchoContract(unittest.TestCase):
    def setUp(self):
        self.step=read(CONTRACT)['steps'][2]
        self.body=expected_echo('rust',self.step,'synthetic-run','synthetic-attempt')
        self.response={'statusCode':200,'isBase64Encoded':False,'headers':{'content-type':'application/json'},'body':json.dumps(self.body)}
    def check(self,response):return response_errors('rust',self.step,response,'synthetic-run','synthetic-attempt')
    def test_declared_golden_passes(self):self.assertEqual(self.check(self.response),[])
    def test_lost_query_multiplicity_rejected(self):
        self.body['multiValueQueryStringParameters']['q']=[''];self.response['body']=json.dumps(self.body);self.assertTrue(self.check(self.response))
    def test_wrong_backend_identity_rejected(self):
        self.body['backendIdentity']='echo-b';self.response['body']=json.dumps(self.body);self.assertTrue(self.check(self.response))
    def test_credentials_in_echo_rejected(self):
        self.body['authorization']='synthetic-auth-canary';self.response['body']=json.dumps(self.body);self.assertIn('echo privacy',self.check(self.response))
    def test_bad_envelope_and_json_rejected(self):
        self.response.update(statusCode=500,body='{broken',isBase64Encoded=True);errors=self.check(self.response);self.assertIn('status',errors);self.assertIn('base64',errors);self.assertIn('echo JSON',errors)
    def test_received_null_not_normalized_to_echo_object(self):
        step=read(CONTRACT)['steps'][0]
        self.assertEqual(expected_echo('rust',step,'run','attempt')['queryStringParameters'],{})
        self.assertEqual(expected_received('rust',step)['queryStringParameters'],{'state':'null'})
    def test_warm_clean_golden_has_no_prior_synthetic_header(self):
        step=read(CONTRACT)['steps'][-1];value=expected_echo('rust',step,'run','recovery')
        self.assertNotIn('x-synthetic',value['headers']);self.assertEqual(value['body'],None)
if __name__=='__main__':unittest.main()
