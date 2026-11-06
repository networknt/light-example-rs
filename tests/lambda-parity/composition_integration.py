#!/usr/bin/env python3
"""Local real-factory composition; unavailable native profiles stay explicit."""
import argparse,base64,copy,json,uuid,zipfile
from pathlib import Path
from integration import Runtime,InvokeBridge,environment,configure,unpack,candidate_pins,RUST_ZIP
from dynamic_echo import CANDIDATE
from error_integration import BACKEND_SHA,BACKEND_ZIP_SHA
from run import ARTIFACTS,REPO,read,write,digest,event
CLASSES={'proxy':'proxy.LambdaProxyMiddleware','correlation':'correlation.CorrelationMiddleware','requestHeader':'header.RequestHeaderMiddleware','responseHeader':'header.ResponseHeaderMiddleware','requestTransformer':'transformer.RequestTransformerMiddleware','responseTransformer':'transformer.ResponseTransformerMiddleware'}
PREFIX='com.networknt.aws.lambda.handler.middleware.'

def plans():
    headers=[{'id':'first','path':'/x','body':'plain','status':201,'calls':1},
             {'id':'fresh','path':'/x','body':'clean','status':201,'calls':1},
             {'id':'backend-error','path':'/x','body':'clean','mode':'application-error','status':500,'calls':1},
             {'id':'route-error','path':'/missing','body':'clean','status':400,'code':'ERR10086','calls':0},
             {'id':'warm-recovery','path':'/x','body':'clean','status':201,'calls':1}]
    transformed=[{'id':'transformed','path':'/x','body':'mutate','status':201,'calls':1},
                 {'id':'body-limit-before-route','path':'/x','bodyBytes':32768,'status':500,'code':'ERR14032','calls':0},
                 {'id':'untransformed-route-error','path':'/x','body':'plain','status':400,'code':'ERR10086','calls':0},
                 {'id':'backend-error','path':'/x','body':'mutate','mode':'application-error','status':500,'calls':1},
                 {'id':'warm-recovery','path':'/x','body':'mutate','status':201,'calls':1}]
    result=[]
    for side in ['java','rust']:
        for order in ['forward','reversed']:result.append({'name':'headers-'+order+'-'+side,'side':side,'family':'headers','order':order,'steps':headers})
    for order in ['forward','reversed']:result.append({'name':'transformers-'+order+'-rust','side':'rust','family':'transformers','order':order,'steps':transformed})
    result.append({'name':'native-transformer-service-gate','side':'java','family':'service-gate','order':'forward','steps':[{'id':s,'path':'/x','body':'mutate','status':404,'code':'ERR11406','calls':0} for s in ['first','warm']]})
    return result

def prepare(args,directory,profile,endpoint,binary):
    sample=read(args.fabric/'tests/serverless-conformance/fixtures/v1/e/E-03-response-off-0-multi-v1.json');files=sample['config']['files']
    full=profile['family']=='transformers';gate=profile['family']=='service-gate';forward=profile['order']=='forward'
    request=(['correlation','requestHeader'] if forward else ['requestHeader','correlation'])
    response=['responseHeader']
    if full:
        request=['correlation','requestHeader','requestTransformer'] if forward else ['requestTransformer','requestHeader','correlation']
        response=['responseHeader','responseTransformer'] if forward else ['responseTransformer','responseHeader']
    if gate:request=['correlation','requestTransformer'];response=[]
    aliases=list(dict.fromkeys(request+['proxy']+response))
    files['handler']={'enabled':True,'handlers':[PREFIX+CLASSES[a]+'@'+a for a in aliases],'chains':{'request':request,'response':response},'defaultHandlers':['request','proxy','response'],'paths':[]}
    files['correlation']={'enabled':True,'autogenCorrelationID':True}
    if gate:files['service']={'singletons':[]}
    files['header']={'enabled':True,'request':{'remove':['x-correlation-id','x-remove'],'update':{'x-synthetic':'configured','x-added':'request-before','x-remove':'request-before'}},'response':{'update':{'x-added':'response-before','x-remove':'response-before','x-chain':'composition'}}}
    files['lambda-proxy']['functions']={('/changed@post' if full else '/x@post'):'parity-echo-b' if full else 'parity-echo-a'}
    if full or gate:
        fixtures=args.fabric/'tests/serverless-conformance/fixtures/v1/t'
        first=read(fixtures/'T-01-metadata-native-cel-multi-contract-v1.json')
        second=read(fixtures/'T-02-response-header-remove-update-multi-contract-v1.json')
        if full:
            rule={'endpointRules':{'/x@post':{'req-tra':['test-edge'],'res-tra':['slow']},'/changed@post':{'res-tra':['slow']}},'ruleBodies':{}}
            for f in [first,second]:rule['ruleBodies'].update(copy.deepcopy(f['ruleConfigurationPair']['rust']['rule']['ruleBodies']))
            files['rule']=rule
        else:
            # The shared layer tool also validates Rust Init. Supply a genuine
            # immutable Rust rule program for that check; this profile executes
            # Java only and never counts that validation as Transformer service
            # coverage. Java still has no configured RuleExecutor provider.
            files['rule']=copy.deepcopy(first['ruleConfigurationPair']['rust']['rule'])
        files['request-transformer']={'enabled':True,'appliedPathPrefixes':['/x']}
        files['response-transformer']={'enabled':True,'appliedPathPrefixes':['/']}
    return configure(args,directory,sample,endpoint,binary)

def response_errors(profile,step,response):
    errors=[]
    if response.get('statusCode')!=step['status']:errors.append('status')
    if step.get('code'):
        try:code=json.loads(response['body']).get('code')
        except (ValueError,KeyError,TypeError):code=None
        if code!=step['code']:errors.append('code')
    else:
        wanted='{"code":"PARITY_APPLICATION_ERROR"}' if step.get('mode')=='application-error' else '{"result":"created"}'
        if response.get('body')!=wanted:errors.append('body')
    if response.get('isBase64Encoded') is not False:errors.append('base64')
    if step['calls']:
        headers={k.lower():v for k,v in (response.get('headers') or {}).items()}
        headers.update({k.lower():v[-1] for k,v in (response.get('multiValueHeaders') or {}).items()})
        after=profile['family']=='transformers' and profile['order']=='forward'
        if headers.get('x-added')!=('after' if after else 'response-before'):errors.append('response ordering')
        if after and 'x-remove' in headers:errors.append('response remove ordering')
        if not after and headers.get('x-remove')!='response-before':errors.append('response header')
    return errors

def call_errors(profile,step,calls,generated):
    errors=[]
    if len(calls)!=step['calls']:return ['dispatch count']
    for call in calls:
        ev=call['event'];headers={k.lower():v for k,v in (ev.get('headers') or {}).items()};full=profile['family']=='transformers';forward=profile['order']=='forward'
        if call['target']!=('parity-echo-b' if full else 'parity-echo-a'):errors.append('target selected after transform')
        if ev.get('path')!=('/changed' if full else '/x') or ev.get('body')!=('transformed' if full else step['body']):errors.append('request transformation')
        if headers.get('x-added')!=('updated' if full and forward else 'request-before'):errors.append('request header/transform order')
        if full and forward and 'x-remove' in headers:errors.append('request remove ordering')
        if not (full and forward) and headers.get('x-remove')!='request-before':errors.append('request header')
        cid=headers.get('x-correlation-id')
        if forward and cid is not None:errors.append('correlation should precede removal')
        if not forward:
            if not isinstance(cid,str) or not cid or cid=='caller-first' or cid in generated:errors.append('fresh generated correlation')
            if isinstance(cid,str):generated.add(cid)
        if step['id']!='first' and 'x-unrelated' in headers:errors.append('warm header leak')
        if full and (ev.get('queryStringParameters') or {}).get('added')!='7':errors.append('transformed query')
        if not call['signed'] or call['invoke']['logType']!='None' or call['backendResultKind']!='response':errors.append('SDK contract')
    return errors

def run(args):
    pins=candidate_pins(args);out=args.out.resolve();assert out.is_relative_to(ARTIFACTS.resolve());out.mkdir(parents=True,exist_ok=False)
    plan=plans();write(out/'declared-profiles.json',plan);assert digest(args.backend_zip)==BACKEND_ZIP_SHA
    write(out/'pins.json',{'gatewayZipSha256':pins,'backendZipSha256':digest(args.backend_zip),'runnerSha256':digest(Path(__file__)),'AWSCalls':0})
    (out/'backend-package').mkdir()
    with zipfile.ZipFile(args.backend_zip) as z:
        assert z.namelist()==['bootstrap'];binary=out/'backend-package/bootstrap';binary.write_bytes(z.read('bootstrap'));binary.chmod(0o755)
    assert digest(binary)==BACKEND_SHA
    managed=[];bridge=None;rows=[];unavailable=[];cleanup=[]
    try:
        for side,z in [('java',args.java_zip),('rust',RUST_ZIP)]:unpack(z,out/(side+'-package'),side,pins)
        backends={}
        for identity in ['echo-a','echo-b']:
            rt=Runtime('composition-'+identity,out);managed.append(rt);backends['parity-'+identity]=rt
            rt.start([binary],dict(environment(),PARITY_BACKEND_IDENTITY=identity),out)
        bridge=InvokeBridge(backends)
        for profile in plan:
            directory=out/profile['name'];directory.mkdir();java,rust=prepare(args,directory,profile,f'http://127.0.0.1:{bridge.server.server_port}',out/'rust-package/bootstrap')
            rt=Runtime(profile['name'],out);managed.append(rt);env=environment();env['_HANDLER']='com.networknt.aws.lambda.app.LambdaApp::handleRequest'
            if profile['side']=='java':cmd=[out/'java-package/lambda-native','-Dlight-4j-config-dir='+str(java),'-Dlogback.configurationFile='+str(java/'logback.xml')]
            else:
                cmd=[out/'rust-package/bootstrap'];env.update(LIGHT_LAMBDA_CONFIG_DIR=str(rust),LIGHT_LAMBDA_ALLOW_INSECURE_TEST_ENDPOINTS='1',LIGHT_LAMBDA_GATEWAY_ARN='arn:aws:lambda:us-east-1:000000000000:function:'+rt.name)
            rt.start(cmd,env,out);generated=set();run_id=uuid.uuid4().hex
            for index,step in enumerate(profile['steps']):
                attempt='step-'+uuid.uuid4().hex;raw=event({'mode':step.get('mode','created'),'method':'POST','path':step['path'],'body':'x'*step['bodyBytes'] if 'bodyBytes' in step else step['body']},profile['name']+'-'+str(index),attempt,run_id)
                raw['headers']={}
                if step['id']=='first':raw['headers'].update({'x-correlation-id':'caller-first','x-unrelated':'first-only'})
                write(directory/'events'/(str(index)+'.json'),raw);before=len(bridge.calls)
                try:result=rt.submit(raw)
                except RuntimeError:
                    if index!=0 or not rt.fatal:raise
                    unavailable.append({'profile':profile['name'],'boundary':'native factory/Init','initErrors':rt.fatal,'log':rt.name+'.log','backendCalls':len(bridge.calls)-before});break
                if result['kind']!='response' and index==0:
                    unavailable.append({'profile':profile['name'],'boundary':'first invocation factory/runtime error','payload':json.loads(result['payload']),'log':rt.name+'.log','backendCalls':len(bridge.calls)-before});break
                response=json.loads(result['payload']);calls=copy.deepcopy(bridge.calls[before:]);errors=response_errors(profile,step,response)+call_errors(profile,step,calls,generated)
                if result['kind']!='response':errors.append('outer Runtime error')
                row={'profile':profile['name'],'side':profile['side'],'family':profile['family'],'step':index,'id':step['id'],'attemptId':attempt,'gatewayPid':rt.process.pid,'gatewayRequestId':result['id'],'response':response,'calls':calls,'passed':not errors,'errors':errors,'coverage':'service-rejection-only' if profile['family']=='service-gate' else 'handler-execution'};rows.append(row);write(directory/'results'/(str(index)+'.json'),row)
        records=[]
        for rt in managed[:2]:
            rt.log.flush();records.extend(json.loads(line) for line in (out/(rt.name+'.log')).read_text().splitlines() if line.startswith('{'))
        entries=[r for r in records if r.get('phase')=='entry'];done=[r for r in records if r.get('phase')=='completion'];errors=list(bridge.errors)
        if not len(entries)==len(done)==len(bridge.calls):errors.append('execution count')
        if len({r['executionRequestId'] for r in entries})!=len(entries) or {r['executionRequestId'] for r in entries}!={r['executionRequestId'] for r in done}:errors.append('execution/completion identities')
        for row in rows:
            matches=[r for r in entries if r['attemptId']==row['attemptId']]
            if len(matches)!=len(row['calls']):errors.append('per-attempt execution count')
            for r,call in zip(matches,row['calls']):
                if r['backendIdentity']!=call['target'].removeprefix('parity-') or r['backendVersion']!='1' or r['executionRequestId']!=call['backendExecutionRequestId'] or r['executionRequestId']==call['invokeApiRequestId']:errors.append('backend identity join')
        write(out/'rows.json',rows);write(out/'backend-records.json',records);write(out/'unavailable.json',unavailable)
        report={'green':all(r['passed'] for r in rows) and not errors and not unavailable,'executedExpectations':len(rows),'expectationPasses':sum(r['passed'] for r in rows),'functionalChecks':sum(r['coverage']=='handler-execution' for r in rows),'serviceRejectionChecks':sum(r['coverage']=='service-rejection-only' for r in rows),'unavailableProfiles':unavailable,'backendExecutions':len(entries),'backendCompletions':len(done),'zeroDispatchRejections':sum(not r['calls'] for r in rows),'errors':errors,'AWSCalls':0,'JWKS':'outside proxy-only profile','SDKWire':'unmeasured','pairedParity':'not claimed; Rust Transformer execution separate from native service gate'}
        write(out/'report.json',report);print(json.dumps(report));return 0 if report['green'] else 1
    except BaseException as error:
        write(out/'failure.json',{'type':type(error).__name__,'reason':str(error)});write(out/'partial-results.json',rows);raise
    finally:
        for rt in reversed(managed):cleanup.append(rt.close())
        if bridge:bridge.close()
        write(out/'cleanup.json',cleanup)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path);p.add_argument('--fabric',type=Path,default=REPO.parent/'light-fabric-light-lambda');p.add_argument('--java-zip',type=Path,default=CANDIDATE/'java-native-status-format-candidate.zip');p.add_argument('--candidate-manifest',type=Path,default=CANDIDATE/'candidate-manifest.json');p.add_argument('--backend-zip',type=Path,default=ARTIFACTS/'parity-java-proxy-mitigation-20261023T020303Z/aws-scope-final/backend-bootstrap.zip');return run(p.parse_args())
if __name__=='__main__':raise SystemExit(main())
