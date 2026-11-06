#!/usr/bin/env python3
"""Local production target selection; immutable packages, running backends."""
import argparse,base64,copy,json,uuid,zipfile
from pathlib import Path
from integration import Runtime,InvokeBridge,environment,configure,unpack,candidate_pins,RUST_ZIP
from error_integration import BACKEND_SHA,BACKEND_ZIP_SHA
from dynamic_echo import CANDIDATE
from run import ARTIFACTS,HERE,REPO,read,write,digest,event
CONTRACT=HERE/'routes-v2.json'

def target_for(side,step):
    return step.get('expectJavaTarget',step['target']) if side=='java' else step['target']

def response_errors(step,response):
    errors=[]
    if step['target'] is None:
        expected={'statusCode':400,'code':'ERR10086','message':'FAILED_TO_INVOKE_LAMBDA','description':f"Failed to invoke lambda function {step['path']}@{step['method'].lower()}.",'severity':'ERROR'}
        try:body=json.loads(response['body'])
        except (ValueError,KeyError,TypeError):body=None
        if response.get('statusCode')!=400 or body!=expected:errors.append({'expectedError':expected,'actual':response})
    elif response.get('statusCode')!=201 or response.get('body')!='{"result":"created"}':errors.append('success envelope')
    if response.get('isBase64Encoded') is not False:errors.append('base64')
    headers={k.lower():v for k,v in (response.get('headers') or {}).items()}
    headers.update({k.lower():v[-1] for k,v in (response.get('multiValueHeaders') or {}).items()})
    if headers!={'content-type':'application/json'}:errors.append('headers')
    return errors

def dispatch_errors(side,step,calls):
    target=target_for(side,step)
    if target is None:return [] if not calls else ['zero-dispatch rejection']
    if len(calls)!=1:return ['exactly one dispatch']
    call=calls[0];errors=[]
    if call['target']!=target:errors.append('wrong target')
    if call['event'].get('path')!=step['path'] or call['event'].get('httpMethod')!=step['method']:errors.append('forwarded path/method')
    if call['backendResultKind']!='response' or not call['signed'] or call['invoke']['logType']!='None':errors.append('SDK contract')
    return errors

def run(args):
    pins=candidate_pins(args);out=args.out.resolve();assert out.is_relative_to(ARTIFACTS.resolve());out.mkdir(parents=True,exist_ok=False)
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
            rt=Runtime('routes-'+identity,out);managed.append(rt);backends['parity-'+identity]=rt
            rt.start([binary],dict(environment(),PARITY_BACKEND_IDENTITY=identity),out)
        bridge=InvokeBridge(backends);run_id=uuid.uuid4().hex
        for order in contract['orders']:
            directory=out/order;directory.mkdir()
            sample=read(args.fabric/'tests/serverless-conformance/fixtures/v1/e/E-03-response-off-0-multi-v1.json')
            routes=contract['routes'] if order=='declared' else list(reversed(contract['routes']))
            sample['config']['files']['lambda-proxy']['functions']=dict(routes)
            java,rust=configure(args,directory,sample,f'http://127.0.0.1:{bridge.server.server_port}',out/'rust-package/bootstrap')
            for side in ['java','rust']:
                rt=Runtime('routes-'+order+'-'+side,out);managed.append(rt);env=environment();env['_HANDLER']='com.networknt.aws.lambda.app.LambdaApp::handleRequest'
                if side=='java':cmd=[out/'java-package/lambda-native','-Dlight-4j-config-dir='+str(java),'-Dlogback.configurationFile='+str(java/'logback.xml')]
                else:
                    cmd=[out/'rust-package/bootstrap'];env.update(LIGHT_LAMBDA_CONFIG_DIR=str(rust),LIGHT_LAMBDA_ALLOW_INSECURE_TEST_ENDPOINTS='1',LIGHT_LAMBDA_GATEWAY_ARN='arn:aws:lambda:us-east-1:000000000000:function:'+rt.name)
                rt.start(cmd,env,out)
                for index,step in enumerate(contract['steps']):
                    attempt=side+'-'+uuid.uuid4().hex;raw=event({'mode':'created','path':step['path'],'method':step['method']},step['id'],attempt,run_id)
                    write(directory/'events'/side/(str(index)+'.json'),raw)
                    before=len(bridge.calls);result=rt.submit(raw);response=json.loads(result['payload']);calls=copy.deepcopy(bridge.calls[before:])
                    errors=response_errors(step,response)+dispatch_errors(side,step,calls)
                    if result['kind']!='response':errors.append('outer Runtime error')
                    row={'side':side,'order':order,'step':index,'id':step['id'],'attemptId':attempt,'gatewayRequestId':result['id'],'gatewayPid':rt.process.pid,'response':response,'rawResponseBase64':base64.b64encode(result['payload']).decode(),'calls':calls,'passed':not errors,'errors':errors};rows.append(row);write(directory/'results'/side/(str(index)+'.json'),row)
        records=[]
        for rt in managed[:2]:
            rt.log.flush();records.extend(json.loads(line) for line in (out/(rt.name+'.log')).read_text().splitlines() if line.startswith('{'))
        entries=[r for r in records if r.get('phase')=='entry'];done=[r for r in records if r.get('phase')=='completion'];errors=list(bridge.errors)
        if not len(entries)==len(done)==len(bridge.calls)==contract['expectedExecutions']:errors.append('execution counts')
        if len({r['executionRequestId'] for r in entries})!=contract['expectedExecutions']:errors.append('duplicate execution IDs')
        if {r['executionRequestId'] for r in entries}!={r['executionRequestId'] for r in done}:errors.append('completion identities')
        for row in rows:
            wanted=target_for(row['side'],contract['steps'][row['step']]);matches=[r for r in entries if r['attemptId']==row['attemptId']]
            if len(matches)!=(0 if wanted is None else 1):errors.append('per-attempt execution count');continue
            if wanted is not None:
                r=matches[0];call=row['calls'][0]
                if r['backendIdentity']!=wanted.removeprefix('parity-') or r['backendVersion']!='1' or r['mode']!='created' or r['runId']!=run_id or r['caseId']!=row['id'] or r['executionRequestId']!=call['backendExecutionRequestId'] or r['executionRequestId']==call['invokeApiRequestId']:errors.append('backend identity/join')
        pairs=[{'order':order,'step':i,'contractsPass':all(r['passed'] for r in rows if r['order']==order and r['step']==i),'rawByteIdentical':len({r['rawResponseBase64'] for r in rows if r['order']==order and r['step']==i})==1} for order in contract['orders'] for i in range(len(contract['steps']))]
        report={'green':len(rows)==contract['expectedRequests'] and all(r['passed'] for r in rows) and not errors,'AWSCalls':0,'expectations':len(rows),'expectationPasses':sum(r['passed'] for r in rows),'sideSpecificContractPairs':sum(p['contractsPass'] for p in pairs),'byteIdenticalPairs':sum(p['rawByteIdentical'] for p in pairs),'backendExecutions':len(entries),'backendCompletions':len(done),'zeroDispatchRejections':sum(not r['calls'] for r in rows),'SDKWire':'unmeasured','JWKS':'outside proxy-only profile','RouterRewriting':'not exercised','errors':errors,'pairs':pairs}
        write(out/'backend-records.json',records);write(out/'rows.json',rows);write(out/'report.json',report);print(json.dumps(report));return 0 if report['green'] else 1
    except BaseException as error:
        write(out/'failure.json',{'type':type(error).__name__,'reason':str(error)});write(out/'partial-results.json',rows);raise
    finally:
        for rt in reversed(managed):cleanup.append(rt.close())
        if bridge:bridge.close()
        write(out/'cleanup.json',cleanup)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path);p.add_argument('--fabric',type=Path,default=REPO.parent/'light-fabric-light-lambda');p.add_argument('--java-zip',type=Path,default=CANDIDATE/'java-native-status-format-candidate.zip');p.add_argument('--candidate-manifest',type=Path,default=CANDIDATE/'candidate-manifest.json');p.add_argument('--backend-zip',type=Path,default=ARTIFACTS/'parity-java-proxy-mitigation-20261023T020303Z/aws-scope-final/backend-bootstrap.zip');return run(p.parse_args())
if __name__=='__main__':raise SystemExit(main())
