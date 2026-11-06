#!/usr/bin/env python3
"""Additive local real SDK -> running backend echo profile; no AWS calls."""
import argparse,base64,copy,json,uuid,zipfile
from pathlib import Path
from integration import Runtime,InvokeBridge,environment,configure,unpack,candidate_pins,RUST_ZIP
from error_integration import BACKEND_SHA,BACKEND_ZIP_SHA
from run import ARTIFACTS,HERE,REPO,read,write,digest,event
from received_observations import expected as received_expected
CONTRACT=HERE/'dynamic-echo-v1.json'
CANDIDATE=ARTIFACTS/'parity-java-status-format-20261023T061219Z'

def expected_echo(side,step,run_id,attempt):
    """Bind only send-ledger identifiers to the predeclared independent golden."""
    contract=read(CONTRACT)
    value=copy.deepcopy(contract['profiles'][side]);value.update(copy.deepcopy(step.get('expected',{}).get(side,{})))
    controls={'x-parity-case':['echo'],'x-parity-run':[run_id],'x-parity-id':[step['id']],'x-parity-attempt':[attempt]}
    if step.get('syntheticHeader'):controls['x-synthetic']=['first','second']
    value['multiValueHeaders']=controls
    if side=='rust':value['headers']={k:v[-1] for k,v in controls.items()}
    return value

def response_errors(side,step,response,run_id,attempt):
    errors=[]
    if response.get('statusCode')!=step.get('expectedStatus',200):errors.append('status')
    if response.get('isBase64Encoded') is not False:errors.append('base64')
    headers={k.lower():v for k,v in (response.get('headers') or {}).items()}
    headers.update({k.lower():v[-1] for k,v in (response.get('multiValueHeaders') or {}).items()})
    if headers!={'content-type':'application/json'}:errors.append('headers')
    if 'expectedBody' in step:
        if response.get('body')!=step['expectedBody']:errors.append('error body')
    else:
        try:actual=json.loads(response['body'])
        except (ValueError,KeyError,TypeError):return errors+['echo JSON']
        wanted=expected_echo(side,step,run_id,attempt)
        if actual!=wanted:errors.append({'echoExpected':wanted,'echoActual':actual})
    for forbidden in read(CONTRACT)['privacyExcluded']:
        if forbidden in json.dumps(response):errors.append('echo privacy')
    return errors

def expected_received(side,step):
    """Reuse original received-field goldens, independently of echo responses."""
    contract=read(HERE/'received-contracts.json')
    recipe=copy.deepcopy(contract['cases']['PARITY-forwarding'][0]) if step.get('syntheticHeader') else {}
    if 'body' in step['request']:recipe['bodyText']=step['request']['body']
    recipe['path']=step['request'].get('path','/parity/a')
    contract['cases']['dynamic']=[recipe]
    wanted=received_expected(side,'dynamic',0,contract)
    if step.get('oversizeBody'):wanted['body']={'state':'redacted'}
    return wanted

def run(args):
    pins=candidate_pins(args);out=args.out.resolve()
    assert out.is_relative_to(ARTIFACTS.resolve());out.mkdir(parents=True,exist_ok=False)
    contract=read(CONTRACT);write(out/'declared-contract.json',contract)
    assert digest(args.backend_zip)==BACKEND_ZIP_SHA
    write(out/'pins.json',{'gatewayZipSha256':pins,'backendZipSha256':digest(args.backend_zip),'contractSha256':digest(CONTRACT),'runnerSha256':digest(Path(__file__)),'AWSCalls':0})
    (out/'backend-package').mkdir()
    with zipfile.ZipFile(args.backend_zip) as z:
        assert z.namelist()==['bootstrap'];binary=out/'backend-package/bootstrap';binary.write_bytes(z.read('bootstrap'));binary.chmod(0o755)
    assert digest(binary)==BACKEND_SHA
    managed=[];bridge=None;rows=[];cleanup=[]
    try:
        for side,z in [('java',args.java_zip),('rust',RUST_ZIP)]:unpack(z,out/(side+'-package'),side,pins)
        backends={}
        for identity in ['echo-a','echo-b']:
            rt=Runtime('dynamic-'+identity,out);managed.append(rt);backends['parity-'+identity]=rt
            rt.start([binary],dict(environment(),PARITY_BACKEND_IDENTITY=identity,PARITY_BACKEND_OBSERVATIONS='synthetic-v1'),out)
        bridge=InvokeBridge(backends)
        sample=read(args.fabric/'tests/serverless-conformance/fixtures/v1/e/E-03-response-off-0-multi-v1.json')
        sample['config']['files']['lambda-proxy']['functions']={'/parity/a@post':'parity-echo-a','/parity/b@post':'parity-echo-b'}
        java,rust=configure(args,out,sample,f'http://127.0.0.1:{bridge.server.server_port}',out/'rust-package/bootstrap')
        run_id=uuid.uuid4().hex
        for side in ['java','rust']:
            rt=Runtime('dynamic-'+side,out);managed.append(rt);env=environment();env['_HANDLER']='com.networknt.aws.lambda.app.LambdaApp::handleRequest'
            if side=='java':cmd=[out/'java-package/lambda-native','-Dlight-4j-config-dir='+str(java),'-Dlogback.configurationFile='+str(java/'logback.xml')]
            else:
                cmd=[out/'rust-package/bootstrap'];env.update(LIGHT_LAMBDA_CONFIG_DIR=str(rust),LIGHT_LAMBDA_ALLOW_INSECURE_TEST_ENDPOINTS='1',LIGHT_LAMBDA_GATEWAY_ARN='arn:aws:lambda:us-east-1:000000000000:function:'+rt.name)
            rt.start(cmd,env,out)
            for index,step in enumerate(contract['steps']):
                attempt=side+'-'+uuid.uuid4().hex;raw=event(step['request'],step['id'],attempt,run_id)
                if step.get('oversizeBody'):raw['body']='x'*step['oversizeBody']
                raw['multiValueHeaders'].update({'authorization':['synthetic-auth-canary'],'cookie':['synthetic-cookie-canary'],'x-private':['synthetic-private-canary']})
                write(out/'events'/side/(str(index)+'.json'),raw)
                before=len(bridge.calls);result=rt.submit(raw);response=json.loads(result['payload']);calls=copy.deepcopy(bridge.calls[before:])
                errors=response_errors(side,step,response,run_id,attempt)
                if result['kind']!='response':errors.append('outer Runtime error')
                if len(calls)!=1:errors.append('exactly one Invoke')
                target='parity-echo-b' if step['id']=='echo-b' else 'parity-echo-a'
                for call in calls:
                    if call['target']!=target or call['backendResultKind']!='response':errors.append('target/result')
                    if not call['signed'] or call['invoke']['logType']!='None':errors.append('SDK contract')
                row={'side':side,'step':index,'id':step['id'],'attemptId':attempt,'gatewayRequestId':result['id'],'gatewayPid':rt.process.pid,'response':response,'rawResponseBase64':base64.b64encode(result['payload']).decode(),'calls':calls,'passed':not errors,'errors':errors}
                rows.append(row);write(out/'results'/side/(str(index)+'.json'),row)
        records=[]
        for rt in managed[:2]:
            rt.log.flush();records.extend(json.loads(line) for line in (out/(rt.name+'.log')).read_text().splitlines() if line.startswith('{'))
        entries=[r for r in records if r.get('schema')=='parity-execution/v1' and r.get('phase')=='entry'];done=[r for r in records if r.get('schema')=='parity-execution/v1' and r.get('phase')=='completion'];received=[r for r in records if r.get('schema')=='parity-request-observation/v1']
        errors=list(bridge.errors);wanted=2*len(contract['steps'])
        if not len(entries)==len(done)==len(received)==len(bridge.calls)==wanted:errors.append('independent execution counts')
        if len({r['executionRequestId'] for r in entries})!=wanted:errors.append('duplicate execution IDs')
        if {r['executionRequestId'] for r in entries}!={r['executionRequestId'] for r in done}:errors.append('completion IDs')
        for row in rows:
            found=[r for r in entries if r['attemptId']==row['attemptId']]
            if len(found)!=1 or len(row['calls'])!=1:errors.append('attempt join');continue
            r=found[0];call=row['calls'][0]
            if r['executionRequestId']!=call['backendExecutionRequestId'] or r['backendIdentity']!=call['target'].removeprefix('parity-') or r['backendVersion']!='1':errors.append('execution identity')
            if call['invokeApiRequestId']==r['executionRequestId']:errors.append('API/execution ID conflation')
            observed=[v for v in received if v['executionRequestId']==r['executionRequestId']]
            if len(observed)!=1:errors.append('received-event join')
            elif observed[0]['observation']!=expected_received(row['side'],contract['steps'][row['step']]):
                errors.append({'receivedEvent':row['attemptId'],'expected':expected_received(row['side'],contract['steps'][row['step']]),'actual':observed[0]['observation']})
            if row['id']!='bounded-rejection':
                actual=json.loads(row['response']['body'])
                # Echo full allowlisted response was independently checked above.
                # The actual SDK-received event is retained separately, not used
                # as a golden or labelled as raw SDK wire measurement.
                if actual.get('backendIdentity')!=r['backendIdentity']:errors.append('echo/log identity')
        pairs=[{'step':i,'contractsPass':all(r['passed'] for r in rows if r['step']==i),'rawByteIdentical':len({r['rawResponseBase64'] for r in rows if r['step']==i})==1} for i in range(len(contract['steps']))]
        report={'green':all(r['passed'] for r in rows) and not errors,'AWSCalls':0,'topology':'real Init/service/SDK -> owned Invoke bridge -> running compiled backend','expectations':len(rows),'expectationPasses':sum(r['passed'] for r in rows),'sideSpecificContractPairs':sum(p['contractsPass'] for p in pairs),'byteIdenticalPairs':sum(p['rawByteIdentical'] for p in pairs),'backendEntries':len(entries),'backendCompletions':len(done),'receivedRecords':len(received),'JWKS':'outside proxy-only profile','SDKWire':'unmeasured','errors':errors,'pairs':pairs}
        write(out/'backend-records.json',records);write(out/'report.json',report);write(out/'rows.json',rows);print(json.dumps(report));return 0 if report['green'] else 1
    except BaseException as error:
        write(out/'failure.json',{'type':type(error).__name__,'reason':str(error)});write(out/'partial-results.json',rows);raise
    finally:
        for rt in reversed(managed):cleanup.append(rt.close())
        if bridge:bridge.close()
        write(out/'cleanup.json',cleanup)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path);p.add_argument('--fabric',type=Path,default=REPO.parent/'light-fabric-light-lambda');p.add_argument('--java-zip',type=Path,default=CANDIDATE/'java-native-status-format-candidate.zip');p.add_argument('--candidate-manifest',type=Path,default=CANDIDATE/'candidate-manifest.json');p.add_argument('--backend-zip',type=Path,default=ARTIFACTS/'parity-java-proxy-mitigation-20261023T020303Z/aws-scope-final/backend-bootstrap.zip');return run(p.parse_args())
if __name__=='__main__':raise SystemExit(main())
