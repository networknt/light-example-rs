import copy,json,unittest
from rust_petstore_acceptance import PLAN,read,validate_plan,response_errors,call_errors,echo_errors,ARN_PREFIX,ROUTES,BACKEND_IDENTITIES,reconcile_records

class RustPetstoreAcceptanceContracts(unittest.TestCase):
    def setUp(self):
        self.step={'id':'recover-issuer','route':'list','status':201,'calls':1}
        self.response={'statusCode':201,'body':'{"result":"created"}','isBase64Encoded':False,
                       'headers':{'x-added':'response-before','x-chain':'composed'}}
        self.call={'target':ARN_PREFIX+'PetsGetFunction','event':{'httpMethod':'GET','path':'/v1/pets','body':None,
            'isBase64Encoded':False,'headers':{'x-added':'request-before','x-request':'configured','x-correlation-id':'fresh'}},
            'signed':True,'invoke':{'logType':'None'},'backendResultKind':'response'}
    def test_frozen_totals_and_required_cases(self):
        p=read(PLAN);validate_plan(p)
        self.assertTrue({'wrong-issuer','wrong-audience','post-reader-existing-any-scope','recover-function-error'} <= {s['id'] for s in p['cases']})
    def test_response_and_forwarding(self):
        self.assertEqual(response_errors(self.step,self.response),[])
        self.assertEqual(call_errors(self.step,[self.call],None,set()),[])
    def test_auth_error_cannot_dispatch(self):
        self.step.update(calls=0,status=401,code='ERR10000')
        self.assertEqual(call_errors(self.step,[self.call],None,set()),['dispatch count'])
    def test_target_and_path_are_independent(self):
        self.call['target']=ARN_PREFIX+'PetsPostFunction';self.call['event']['path']='/pets'
        errors=call_errors(self.step,[self.call],None,set())
        self.assertIn('route target',errors);self.assertIn('forwarded method/path/body',errors)
    def test_function_error_keeps_existing_mapping(self):
        self.step.update(status=502,code='ERR14014');self.response.update(statusCode=502,body='{"code":"ERR14014"}')
        self.assertEqual(response_errors(self.step,self.response),[])
        self.response['body']='{"code":"ERR14004"}';self.assertIn('code',response_errors(self.step,self.response))
    def test_private_backend_detail_fails(self):
        self.response['body']='synthetic parity function error'
        self.assertIn('private backend detail',response_errors(self.step,self.response))
    def test_warm_headers_must_not_survive(self):
        self.step['id']='warm-clean-request';self.call['event']['headers']['x-warm-witness']='old'
        self.assertIn('warm request leakage',call_errors(self.step,[self.call],None,set()))
    def test_reused_correlation_fails(self):
        self.assertIn('fresh correlation',call_errors(self.step,[self.call],None,{'fresh'}))
    def test_backend_echo_cannot_be_replaced_by_bridge_expectation(self):
        self.step.update(id='list-reader',mode='echo')
        self.assertTrue(echo_errors(self.step,{'body':'{}'},None,'attempt','run'))
    def test_wrong_issuer_expectation_stays_strict(self):
        s=next(s for s in read(PLAN)['cases'] if s['id']=='wrong-issuer')
        self.assertEqual((s['status'],s['code'],s['calls']),(401,'ERR10000',0))

class RustPetstoreReconciliation(unittest.TestCase):
    def setUp(self):
        self.rows=[];self.calls=[];self.records=[]
        for i,s in enumerate(read(PLAN)['cases']):
            attempt='attempt-'+str(i);ident='execution-'+str(i);mode=s.get('mode','created');route=s['route'];calls=[]
            if s['calls']:
                call={'target':ARN_PREFIX+ROUTES[route][2],'backendExecutionRequestId':ident,'invokeApiRequestId':'api-'+str(i),
                      'backendResultKind':'error' if mode=='function-error' else 'response','signed':True,'invoke':{'logType':'None'}}
                calls.append(call);self.calls.append(call)
                entry={'phase':'entry','attemptId':attempt,'executionRequestId':ident,'backendIdentity':BACKEND_IDENTITIES[route],
                       'backendVersion':'1','mode':mode,'caseId':s['id']};self.records.append(entry)
                if mode!='function-error':self.records.append(dict(entry,phase='completion'))
                self.records.append(dict(entry,schema='parity-request-observation/v1',phase='received-event',observation={
                    'httpMethod':{'state':'value','value':ROUTES[route][0]},'isBase64Encoded':{'state':'value','value':False},'path':{'state':'redacted'}}))
            self.rows.append({'id':s['id'],'route':route,'attemptId':attempt,'calls':calls,'passed':True,'gatewayPid':42})
    def test_declared_a_and_b_identities_pass_without_normalization(self):
        self.assertEqual(reconcile_records(self.rows,self.calls,self.records),[])
    def test_actual_wrong_identity_is_still_rejected(self):
        next(r for r in self.records if r['caseId']=='get-reader' and r['phase']=='entry')['backendIdentity']='echo-a'
        self.assertIn('backend identity: get-reader',reconcile_records(self.rows,self.calls,self.records))
    def test_missing_completion_is_not_zero(self):
        self.records.remove(next(r for r in self.records if r['phase']=='completion'))
        self.assertIn('completion identities',reconcile_records(self.rows,self.calls,self.records))
    def test_duplicate_dispatch_does_not_pass_totals(self):
        self.calls.append(copy.deepcopy(self.calls[0]))
        self.assertIn('entry/dispatch counts',reconcile_records(self.rows,self.calls,self.records))
if __name__=='__main__':unittest.main()
