import json,unittest
from pathlib import Path
from error_integration import response_errors,execution_errors
from jwt_integration import sanitized_call,credentials,SEQUENCE
class NextBatchContracts(unittest.TestCase):
 def setUp(self):self.c=json.loads((Path(__file__).parent/'errors-v1.json').read_text())
 def test_outer_exchange_error_is_failure_not_new_expectation(self):
  actual={'code':0,'message':'missing finalized response flag'}
  self.assertTrue(response_errors('java','wrong-type',actual,self.c))
  self.assertEqual(self.c['expectations']['java']['wrong-type']['code'],'ERR14004')
 def test_native_empty_media_type_contract_is_preserved(self):
  raw={'statusCode':200,'headers':{},'body':'%%%','isBase64Encoded':True}
  self.assertEqual(response_errors('java','invalid-base64',raw,self.c),[])
  raw['headers']['content-type']='invented';self.assertTrue(response_errors('java','invalid-base64',raw,self.c))
 def test_privacy_canary_cannot_hide_in_an_expected_error_code(self):
  raw={'statusCode':502,'headers':{'content-type':'application/json'},'body':json.dumps({'code':'ERR14014','detail':'private-canary'}),'isBase64Encoded':False}
  self.assertTrue(any(e['field']=='privacy' for e in response_errors('rust','function-error',raw,self.c)))
 def test_missing_execution_evidence_is_not_zero_dispatch_success(self):
  self.assertTrue(execution_errors([],[],1))
 def test_completion_without_entry_is_rejected(self):
  r={'schema':'parity-execution/v1','phase':'completion','executionRequestId':'orphan'}
  self.assertTrue(execution_errors([r],[],0))
 def test_saved_credential_redaction_retains_selected_fields(self):
  original={'requestBytesBase64':'private','event':{'headers':{'Authorization':'Bearer synthetic','x-selected':'kept'},'multiValueHeaders':{'authorization':['Bearer synthetic']},'body':'opaque'},'backendPayloadBase64':'unchanged'}
  clean=sanitized_call(original)
  self.assertNotIn('requestBytesBase64',clean);self.assertNotIn('Authorization',clean['event']['headers']);self.assertNotIn('authorization',clean['event']['multiValueHeaders']);self.assertEqual(clean['event']['headers']['x-selected'],'kept');self.assertEqual(clean['backendPayloadBase64'],'unchanged');self.assertIn('Authorization',original['event']['headers'])
 def test_jwt_material_is_public_jwks_and_synthetic_recipes_only(self):
  jwks,tokens=credentials();self.assertEqual(jwks['keys'][0]['alg'],'RS256');self.assertNotIn('d',jwks['keys'][0]);self.assertEqual(len(tokens),5)
  self.assertEqual(sum(x[-1] for x in SEQUENCE),10)
  claims=lambda name:json.loads(__import__('base64').urlsafe_b64decode(tokens[name].split('.')[1]+'=='))
  self.assertEqual(claims('wrong-scope')['scp'],['write']);self.assertEqual(claims('valid-a')['aud'],'test-audience');self.assertLess(claims('expired')['exp'],claims('expired')['iat']+7200)
if __name__=='__main__':unittest.main()
