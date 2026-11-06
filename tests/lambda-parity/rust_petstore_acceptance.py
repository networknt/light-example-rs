#!/usr/bin/env python3
"""Rust replacement acceptance using the unchanged trial chain and running backends.

Reuses Runtime/InvokeBridge, RSA encoding and JWKS tooling. Local only; no Java,
AWS, worker execution, business-data mutation or accepted-package replacement.
"""
import argparse, copy, importlib.util, json, os, shutil, time, uuid, zipfile
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes
from integration import Runtime, InvokeBridge, environment, unpack, RUST_ZIP, PINNED
from jwt_integration import Jwks, b64, integer, sanitized_call
from error_integration import BACKEND_SHA, BACKEND_ZIP_SHA
from run import ARTIFACTS, REPO, HERE, digest, event, read, write

PLAN = HERE/'rust-petstore-v1.json'
ROUTES = {'list':('GET','/v1/pets','PetsGetFunction'),
          'get':('GET','/v1/pets/1792800000001','PetsPetIdGetFunction'),
          'post':('POST','/v1/pets','PetsPostFunction'),
          'delete':('DELETE','/v1/pets/1792800000001','PetsPetIdDeleteFunction')}
ARN_PREFIX='arn:aws:lambda:us-east-2:964637446810:function:'
BACKEND_IDENTITIES={'list':'echo-a','get':'echo-b','post':'echo-a','delete':'echo-b'}
PRIVACY_EXCLUDED=['synthetic parity function error','private-canary','stackTrace','SyntheticFailure']

def credentials(issuer,audience):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    wrong=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    pub=key.public_key().public_numbers(); now=int(time.time()); tokens={}
    jwks={'keys':[{'kty':'RSA','alg':'RS256','use':'sig','kid':'rust-petstore-local','n':integer(pub.n),'e':integer(pub.e)}]}
    for label in ['reader','writer','invalid-signature','wrong-issuer','wrong-audience','expired','unrelated']:
        claims={'sub':'synthetic-'+label,'user_id':'synthetic-'+label,'client_id':'owned-trial',
                'iss':'synthetic-wrong-issuer' if label=='wrong-issuer' else issuer,
                'aud':'synthetic-wrong-audience' if label=='wrong-audience' else audience,
                'iat':now-7200,'exp':now-3600 if label=='expired' else now+3600,
                'jti':uuid.uuid4().hex,'scope':'portal.w' if label=='writer' else 'unrelated' if label=='unrelated' else 'portal.r'}
        unsigned=b64(json.dumps({'alg':'RS256','kid':'rust-petstore-local'}).encode())+'.'+b64(json.dumps(claims).encode())
        signer=wrong if label=='invalid-signature' else key
        tokens[label]=unsigned+'.'+b64(signer.sign(unsigned.encode(),padding.PKCS1v15(),hashes.SHA256()))
    return jwks,tokens

def validate_plan(plan):
    assert plan['schema']=='rust-petstore-acceptance/v1'
    assert len(plan['cases'])==plan['requests']==26
    assert len({s['id'] for s in plan['cases']})==26
    assert sum(s['calls'] for s in plan['cases'])==plan['backendExecutions']==18
    assert sum(s['calls'] and s.get('mode')!='function-error' for s in plan['cases'])==plan['backendCompletions']==17
    assert sum(not s['calls'] for s in plan['cases'])==plan['zeroDispatchRequests']==8
    assert plan['automaticRetries']==0 and plan['jwksFetches']==1

def headers(value):
    merged={k.lower():v for k,v in (value.get('headers') or {}).items()}
    merged.update({k.lower():v[-1] for k,v in (value.get('multiValueHeaders') or {}).items()})
    return merged

def response_errors(step,response):
    errors=[]
    if response.get('statusCode')!=step['status']: errors.append('status')
    if response.get('isBase64Encoded') is not False: errors.append('base64')
    if step.get('code'):
        try: code=json.loads(response['body']).get('code')
        except (ValueError,TypeError,KeyError): code=None
        if code!=step['code']: errors.append('code')
    elif step.get('mode')!='echo' and response.get('body')!=('{"code":"PARITY_APPLICATION_ERROR"}' if step.get('mode')=='application-error' else '{"result":"created"}'):
        errors.append('body')
    if any(v in json.dumps(response) for v in PRIVACY_EXCLUDED):errors.append('private backend detail')
    if step['calls'] and not step.get('code'):
        h=headers(response)
        if h.get('x-added')!='response-before' or h.get('x-chain')!='composed':errors.append('response header chain')
        if 'x-business' in h:errors.append('response header removal')
    return errors

def echo_errors(step,response,body,attempt,run_id):
    if step.get('mode')!='echo':return []
    try:actual=json.loads(response['body'])
    except (ValueError,KeyError,TypeError):return ['echo JSON']
    method,path,_=ROUTES[step['route']]
    controls={'x-parity-case':['echo'],'x-parity-run':[run_id],'x-parity-id':[step['id']],
              'x-parity-attempt':[attempt],'content-type':['application/json']}
    query={'q':['a+b','%2B'],'empty':['']} if step['id']=='list-reader' else None
    # Rust preserves the decoded query maps and scalar mirrors; E-04 percent decoding.
    scalar_query={'q':'+','empty':''} if query else {}
    multi_query={'q':['a+b','+'],'empty':['']} if query else {}
    parameterized=step['route'] in ['get','delete']
    wanted={'httpMethod':method,'path':path,'resource':'/v1/pets/{petId}' if parameterized else '/v1/pets',
            'pathParameters':{'petId':'1792800000001'} if parameterized else None,'body':body,'isBase64Encoded':False,
            'headers':{k:v[-1] for k,v in controls.items()},'multiValueHeaders':controls,
            'queryStringParameters':scalar_query,'multiValueQueryStringParameters':multi_query,
            'backendIdentity':BACKEND_IDENTITIES[step['route']],'backendVersion':'1'}
    return [] if actual==wanted else [{'field':'actual-backend-echo','expected':wanted,'actual':actual}]

def call_errors(step,calls,body,seen):
    if len(calls)!=step['calls']:return ['dispatch count']
    errors=[];method,path,target=ROUTES[step['route']]
    for call in calls:
        received=call['event']; h=headers(received)
        if call['target']!=ARN_PREFIX+target:errors.append('route target')
        if received.get('httpMethod')!=method or received.get('path')!=path or received.get('body')!=body:errors.append('forwarded method/path/body')
        if received.get('isBase64Encoded') is not False:errors.append('forwarded base64 state')
        if h.get('x-request')!='configured' or h.get('x-added')!='request-before':errors.append('request header chain')
        if step['id']=='warm-clean-request':
            if 'x-warm-witness' in h or received.get('multiValueQueryStringParameters'):errors.append('warm request leakage')
        cid=h.get('x-correlation-id')
        if not isinstance(cid,str) or not cid or cid in seen:errors.append('fresh correlation')
        else:seen.add(cid)
        if not call['signed'] or call['invoke']['logType']!='None':errors.append('Invoke contract')
        expected='error' if step.get('mode')=='function-error' else 'response'
        if call.get('backendResultKind')!=expected:errors.append('backend result kind')
    return errors

def reconcile_records(rows,calls,records):
    """Independent identity/count joins for this four-target declaration, also offline."""
    errors=[]
    entries=[r for r in records if r.get('phase')=='entry']
    done=[r for r in records if r.get('phase')=='completion']
    received=[r for r in records if r.get('schema')=='parity-request-observation/v1']
    ids={r['executionRequestId'] for r in entries}
    if len(entries)!=18 or len(calls)!=18 or len(ids)!=18:errors.append('entry/dispatch counts')
    if ids!={c['backendExecutionRequestId'] for c in calls}:errors.append('entry/Invoke identities')
    normal={c['backendExecutionRequestId'] for c in calls if c['backendResultKind']=='response'}
    if len(done)!=17 or len(normal)!=17 or {r['executionRequestId'] for r in done}!=normal:errors.append('completion identities')
    if len(received)!=18 or {r['executionRequestId'] for r in received}!=ids:errors.append('received identities')
    declarations={s['id']:s for s in read(PLAN)['cases']}
    for row in rows:
        step=declarations[row['id']];actual=[r for r in entries if r['attemptId']==row['attemptId']]
        observations=[r for r in received if r['attemptId']==row['attemptId']]
        if len(actual)!=step['calls'] or len(row['calls'])!=step['calls'] or len(observations)!=step['calls']:errors.append('per-attempt count: '+row['id'])
        for r,c in zip(actual,row['calls']):
            if r['backendIdentity']!=BACKEND_IDENTITIES[row['route']] or r['backendVersion']!='1':errors.append('backend identity: '+row['id'])
            if r['mode']!=step.get('mode','created') or r['caseId']!=step['id']:errors.append('backend mode/case: '+row['id'])
            if r['executionRequestId']!=c['backendExecutionRequestId'] or r['executionRequestId']==c['invokeApiRequestId']:errors.append('backend/API identity separation: '+row['id'])
            if not c['signed'] or c['invoke']['logType']!='None' or c['target']!=ARN_PREFIX+ROUTES[step['route']][2]:errors.append('Invoke contract: '+row['id'])
        for observation in observations:
            obs=observation['observation'];method=ROUTES[row['route']][0]
            if obs['httpMethod']!={'state':'value','value':method} or obs['isBase64Encoded']!={'state':'value','value':False}:errors.append('received method/base64: '+row['id'])
            if obs['path']!={'state':'redacted'}:errors.append('bounded path observation policy: '+row['id'])
    if len(rows)!=26 or not all(r['passed'] for r in rows):errors.append('request expectations')
    if len({r['gatewayPid'] for r in rows})!=1:errors.append('warm gateway identity')
    return errors

def prepare_layer(args,out,bootstrap,endpoint,jwks_url):
    source=out/'local-configuration';shutil.copytree(args.configuration,source)
    before={p.name:digest(p) for p in sorted(args.configuration.iterdir()) if p.is_file()}
    values=read(source/'values.yml')
    assert values['security.enabled'] and values['unified-security.enabled']
    assert values['security.enableVerifyJwt'] and values['security.enableVerifyScope']
    assert not values['security.ignoreJwtExpiry']
    values.update({'client.tokenKeyServerUrl':jwks_url,'client.tokenKeyUri':'/jwks','client.tokenKeyEnableHttp2':False})
    (source/'values.yml').write_text(json.dumps(values,indent=2)+'\n')
    proxy=read(source/'lambda-proxy.yml');expected={
        '/v1/pets@get':ARN_PREFIX+'PetsGetFunction','/v1/pets@post':ARN_PREFIX+'PetsPostFunction',
        '/v1/pets/{petId}@get':ARN_PREFIX+'PetsPetIdGetFunction','/v1/pets/{petId}@delete':ARN_PREFIX+'PetsPetIdDeleteFunction'}
    assert proxy['functions']==expected and proxy['logType']=='None' and proxy['region']=='us-east-2'
    proxy['endpointOverride']=endpoint;(source/'lambda-proxy.yml').write_text(json.dumps(proxy,indent=2)+'\n')
    after={p.name:digest(p) for p in sorted(source.iterdir()) if p.is_file()}
    assert {n for n in before if before[n]!=after[n]}=={'values.yml','lambda-proxy.yml'}
    for unchanged in ['handler.yml','openapi.yml','request-transformer.yml','response-transformer.yml','rule.yml','router.yml']:
        assert before[unchanged]==after[unchanged]
    spec=importlib.util.spec_from_file_location('rust_trial_pack',args.fabric/'apps/light-lambda/scripts/package_baseline.py')
    pack=importlib.util.module_from_spec(spec);spec.loader.exec_module(pack)
    with patch.dict(os.environ,{'LIGHT_LAMBDA_ALLOW_INSECURE_TEST_ENDPOINTS':'1'}):info=pack.layer(source,out/'local-config-layer.zip',bootstrap)
    pack.extract_layer(out/'local-config-layer.zip',out/'opt')
    write(out/'layer-report.json',info)
    write(out/'configuration-identities.json',{'source':str(args.configuration.resolve()),'sourceFiles':before,'localFiles':after,
        'adaptations':{'values.yml':'Only key endpoint URL/path and HTTP2 for owned numeric-loopback JWKS; issuer/audience/scope enforcement unchanged',
                       'lambda-proxy.yml':'Only endpointOverride for owned Invoke transport; exact four function identities unchanged'},
        'handlersRemoved':[],'handlersDisabled':[],'originalSourceUnchanged':all(digest(args.configuration/n)==v for n,v in before.items())})
    return out/'opt',values

def run(args):
    plan=read(PLAN);validate_plan(plan)
    out=args.out.resolve();assert out.is_relative_to(ARTIFACTS.resolve());out.mkdir(parents=True,exist_ok=False)
    write(out/'frozen-plan.json',plan)
    assert digest(RUST_ZIP)==PINNED['rust'] and digest(args.backend_zip)==BACKEND_ZIP_SHA
    unpack(RUST_ZIP,out/'gateway-package','rust')
    (out/'backend-package').mkdir()
    with zipfile.ZipFile(args.backend_zip) as z:
        assert z.namelist()==['bootstrap'];binary=out/'backend-package/bootstrap';binary.write_bytes(z.read('bootstrap'));binary.chmod(0o755)
    assert digest(binary)==BACKEND_SHA
    write(out/'identities.json',{'gatewayZip':str(RUST_ZIP),'gatewayZipSha256':digest(RUST_ZIP),'backendZip':str(args.backend_zip),
        'backendZipSha256':digest(args.backend_zip),'runnerSha256':digest(Path(__file__)),'planSha256':digest(PLAN),'AWSCalls':0})
    original_values=read(args.configuration/'values.yml')
    jwks,tokens=credentials(original_values['security.issuer'],original_values['security.audience'][0]);keys=None;bridge=None
    managed=[];rows=[];cleanup=[];all_records=[];seen=set();secret_values=list(tokens.values())
    try:
        keys=Jwks(jwks);write(out/'public-jwks.json',jwks)
        backends={}
        for route,(_,_,function) in ROUTES.items():
            rt=Runtime('rust-petstore-backend-'+route,out);managed.append(rt);backends[ARN_PREFIX+function]=rt
            rt.start([binary],dict(environment(),PARITY_BACKEND_IDENTITY=BACKEND_IDENTITIES[route],PARITY_BACKEND_OBSERVATIONS='synthetic-v1'),out)
        bridge=InvokeBridge(backends)
        configuration,values=prepare_layer(args,out,out/'gateway-package/bootstrap',f'http://127.0.0.1:{bridge.server.server_port}',keys.url)
        gateway=Runtime('rust-petstore-gateway',out);managed.append(gateway)
        env=dict(environment(),AWS_REGION='us-east-2',AWS_DEFAULT_REGION='us-east-2',RUST_LOG='info',
            LIGHT_LAMBDA_CONFIG_DIR=str(configuration),LIGHT_LAMBDA_ALLOW_INSECURE_TEST_ENDPOINTS='1',
            LIGHT_LAMBDA_GATEWAY_ARN=ARN_PREFIX+gateway.name)
        gateway.start([out/'gateway-package/bootstrap'],env,out);run_id='rust-petstore-'+uuid.uuid4().hex
        for i,step in enumerate(plan['cases']):
            method,path,_=ROUTES[step['route']];attempt='attempt-'+uuid.uuid4().hex
            body=step.get('body','{"id":1792800000001,"name":"synthetic-owned-trial","tag":"local-only"}' if method=='POST' else None)
            logical={'mode':step.get('mode','created'),'method':method,'path':path,'body':body}
            if i==0:logical['query']={'q':['a+b','%2B'],'empty':['']}
            raw=event(logical,step['id'],attempt,run_id)
            raw['multiValueHeaders'].update({'content-type':['application/json'],'x-forwarded-for':['198.51.100.7']})
            if method=='DELETE':raw['multiValueHeaders']['key']=['synthetic-owned-trial-key']
            if step['id']!='warm-clean-request':raw['multiValueHeaders']['x-warm-witness']=['request-'+str(i)]
            write(out/'events'/(str(i)+'.json'),raw) # Persist before adding the memory-only credential.
            if step['credential']!='missing':raw['multiValueHeaders']['authorization']=['Bearer '+tokens[step['credential']]]
            before=len(bridge.calls);fetches_before=len(keys.calls);result=gateway.submit(raw)
            response=json.loads(result['payload']);calls=copy.deepcopy(bridge.calls[before:])
            errors=response_errors(step,response)+call_errors(step,calls,body,seen)+echo_errors(step,response,body,attempt,run_id)
            if result['kind']!='response':errors.append('outer Runtime error')
            if any(token in json.dumps(response) for token in secret_values):raise AssertionError('credential leaked into gateway response; stop without persisting it')
            row={'id':step['id'],'route':step['route'],'attemptId':attempt,'gatewayPid':gateway.process.pid,
                 'gatewayRequestId':result['id'],'coverage':'service-execution' if step['calls'] else 'service-authentication-or-parser-rejection',
                 'response':response,'calls':[sanitized_call(c) for c in calls],'jwksDelta':len(keys.calls)-fetches_before,'errors':errors,'passed':not errors}
            rows.append(row);write(out/'results'/(str(i)+'.json'),row)
            if errors:raise AssertionError('expectation failed: '+step['id']+': '+json.dumps(errors))
        for rt in managed[:-1]:
            rt.log.flush();all_records.extend(json.loads(s) for s in (out/(rt.name+'.log')).read_text().splitlines() if s.startswith('{'))
        errors=reconcile_records(rows,bridge.calls,all_records)+bridge.errors
        entries=[r for r in all_records if r.get('phase')=='entry'];done=[r for r in all_records if r.get('phase')=='completion'];received=[r for r in all_records if r.get('phase')=='received-event']
        for row in rows:
            actual=[r for r in entries if r['attemptId']==row['attemptId']]
            if len(actual)!=len(row['calls']):errors.append('per-attempt execution count: '+row['id'])
            for r,c in zip(actual,row['calls']):
                if r['backendIdentity']!=BACKEND_IDENTITIES[row['route']] or r['backendVersion']!='1' or r['executionRequestId']!=c['backendExecutionRequestId'] or r['executionRequestId']==c['invokeApiRequestId']:errors.append('backend identity join: '+row['id'])
        if len(done)!=17 or len(received)!=18:errors.append('completion/received totals')
        if len(keys.calls)!=1 or keys.calls!=[{'method':'GET','path':'/jwks'}]:errors.append('JWKS fetch count or route')
        if len({r['gatewayPid'] for r in rows})!=1:errors.append('warm gateway isolation')
        for rt in managed:
            rt.log.flush();text=(out/(rt.name+'.log')).read_text()
            if any(t in text for t in secret_values):errors.append('credential log leakage: '+rt.name)
        write(out/'backend-records.json',all_records);write(out/'jwks-receipts.json',keys.calls)
        write(out/'report.json',{'green':not errors,'requests':len(rows),'expectationPasses':sum(r['passed'] for r in rows),
            'backendExecutions':len(entries),'backendCompletions':len(done),'receivedRecords':len(received),'zeroDispatch':sum(not r['calls'] for r in rows),
            'jwksFetches':len(keys.calls),'errors':errors,'AWSCalls':0,'backendType':'Four owned instances of unchanged controlled backend, not live petstore functions',
            'executionBoundary':'Pinned package through owned Runtime API and production SDK; not new RIE or AWS proof','SDKWire':'unmeasured',
            'JWT':'Synthetic RS256; issuer/audience unchanged; tokens and private keys memory-only','Validator':'absent from selected profile; no schema-validation proof',
            'Router':'forwarding only; rewriting excluded','Transformers':'existing /x-only rules untouched; petstore paths do not execute rules',
            'admissionOnlyCases':0,'oneWarmGatewayProcess':len({r['gatewayPid'] for r in rows})==1})
        if errors:raise AssertionError('reconciliation failed: '+','.join(errors))
        return 0
    except BaseException as e:
        write(out/'failure.json',{'type':type(e).__name__,'reason':str(e),'completedRequests':len(rows),'backendCalls':len(bridge.calls) if bridge else 0})
        raise
    finally:
        write(out/'rows.json',rows)
        if bridge:write(out/'sanitized-calls.json',[sanitized_call(c) for c in bridge.calls])
        for rt in reversed(managed):cleanup.append(rt.close())
        if bridge:bridge.close()
        if keys:keys.close()
        write(out/'cleanup.json',cleanup)
        if cleanup and not all(r['reaped'] for r in cleanup):raise AssertionError('owned process cleanup failed')
        # Runtime histories must also remain token-free before considering a run green.
        for path in out.rglob('*'):
            if path.is_file() and path.suffix in ['.json','.log','.yml']:
                data=path.read_text()
                if any(t in data for t in secret_values):raise AssertionError('credential evidence leakage: '+str(path))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path)
    p.add_argument('--fabric',type=Path,default=REPO.parent/'light-fabric-light-lambda')
    p.add_argument('--configuration',type=Path,default=REPO.parent/'light-fabric-light-lambda/apps/light-lambda/deploy/l3/config')
    p.add_argument('--backend-zip',type=Path,default=ARTIFACTS/'parity-java-proxy-mitigation-20261023T020303Z/aws-scope-final/backend-bootstrap.zip')
    return run(p.parse_args())
if __name__=='__main__':raise SystemExit(main())
