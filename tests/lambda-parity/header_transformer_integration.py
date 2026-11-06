#!/usr/bin/env python3
"""Opt-in Java production header-action qualification; no accepted pin changes."""
import argparse, copy, json, shutil, uuid, zipfile
from pathlib import Path
from integration import Runtime, InvokeBridge, environment, unpack, JAVA_CONFIG, JAVA_CONFIG_SHA, PINNED
from error_integration import BACKEND_SHA, BACKEND_ZIP_SHA
from run import ARTIFACTS, REPO, digest, event, read, write

SCOPE = ARTIFACTS / 'native-transformer-scope-20261024'
REVIEW_SHA = '6f089b3cbd2127caa5bf1f2d358238585eb9969b3e99f29e368b1b16fd25e75a'
BASE_SHA = '122d03391f999aad4f6ccf022c0fb1188241c2218c670ff013aa884510033db7'
BASE = ARTIFACTS / 'parity-java-status-format-20261023T061219Z'
CLASSES = ['com/networknt/rule/header/HeaderReplaceRequestTransformAction.class',
           'com/networknt/rule/header/HeaderReplaceResponseTransformAction.class']

def candidate_pins(args):
    """Separate additive packaging scope, never an override of integration's guard."""
    m = read(args.candidate_manifest)
    assert m['schema'] == 'parity-header-transformer-candidate/v1'
    assert m['reviewZipSha256'] == REVIEW_SHA == digest(SCOPE/'review.zip')
    assert m['baseCandidateZipSha256'] == BASE_SHA == digest(BASE/'java-native-status-format-candidate.zip')
    assert Path(m['zip']).resolve() == args.java_zip.resolve()
    assert digest(args.java_zip) == m['zipSha256']
    inputs = read(SCOPE/'inputs.json')['files']
    for path in [BASE/'status-format-fat.jar']:
        assert digest(path) == inputs[str(path)]['sha256'] == m['inputs'][str(path)]
    addon=SCOPE/'proposed/native-reflection-addon.json'
    with zipfile.ZipFile(SCOPE/'review.zip') as review:
        assert review.read('proposed/native-reflection-addon.json')==addon.read_bytes()
    assert digest(addon)==m['inputs'][str(addon)]
    plugin = Path('/home/steve/.m2/repository/com/networknt/header-replace/2.4.2-SNAPSHOT/header-replace-2.4.2-SNAPSHOT.jar')
    assert digest(plugin) == inputs[str(plugin)]['sha256'] == m['inputs'][str(plugin)]
    jar = Path(m['jar']); assert digest(jar) == m['jarSha256']
    with zipfile.ZipFile(BASE/'status-format-fat.jar') as old, zipfile.ZipFile(jar) as new, zipfile.ZipFile(plugin) as actions:
        assert len(new.namelist()) == len(set(new.namelist()))
        assert set(new.namelist()) - set(old.namelist()) == set(CLASSES)
        assert not set(old.namelist()) - set(new.namelist())
        assert all(old.read(n) == new.read(n) for n in old.namelist())
        assert all(new.read(n) == actions.read(n) for n in CLASSES)
    with zipfile.ZipFile(BASE/'java-native-status-format-candidate.zip') as old, zipfile.ZipFile(args.java_zip) as new:
        assert new.read('bootstrap') == old.read('bootstrap')
        import hashlib
        assert hashlib.sha256(new.read('lambda-native')).hexdigest() == m['binarySha256']
    return dict(PINNED, java=m['zipSha256'])

def normalized_headers(value):
    result = {k.lower():v for k,v in (value.get('headers') or {}).items()}
    result.update({k.lower():v[-1] for k,v in (value.get('multiValueHeaders') or {}).items()})
    return result

def errors_for(profile, step, response, calls, seen):
    errors=[]
    if response.get('statusCode') != step['status']: errors.append('status')
    if step.get('code'):
        try: code=json.loads(response['body']).get('code')
        except (ValueError, KeyError, TypeError): code=None
        if code != step['code']: errors.append('code')
    elif response.get('body') != ('{"code":"PARITY_APPLICATION_ERROR"}' if step['id']=='application-error' else '{"result":"created"}'):
        errors.append('body')
    if response.get('isBase64Encoded') is not False: errors.append('base64')
    if len(calls) != step['backendExecutions']: errors.append('dispatch count')
    if not calls: return errors
    forward=profile != 'reversed'
    undefined=step['id']=='caught-rule-error-still-dispatches'
    for call in calls:
        ev=call['event']; h=normalized_headers(ev)
        if call['target']!='parity-echo-a' or ev.get('path')!=step.get('path','/x') or ev.get('body')!=step['body']: errors.append('target/path/body')
        if not call['signed'] or call['invoke']['logType']!='None' or call['backendResultKind']!='response': errors.append('SDK contract')
        transformed=forward and not undefined
        if h.get('x-added')!=('request-rule' if transformed else 'request-before'): errors.append('request ordering')
        copied='request-source' if transformed else ('raw-source' if step['id']!='source-missing' and not undefined else None)
        if h.get('x-copied')!=copied: errors.append('copy or warm isolation')
        if transformed and 'x-remove' in h: errors.append('remove')
        if not transformed and h.get('x-remove')!='request-source': errors.append('source preserved by header middleware')
        cid=h.get('x-correlation-id')
        if not isinstance(cid,str) or not cid or cid in seen: errors.append('fresh correlation')
        else: seen.add(cid)
    response_header=normalized_headers(response)
    if response_header.get('x-added')!=('response-rule' if forward and not undefined else 'response-before'): errors.append('response ordering')
    return errors

def prepare(args, directory, profile, endpoint):
    # Java YAML is not submitted to the shared Rust layer validator.
    sample=read(args.fabric/'tests/serverless-conformance/fixtures/v1/e/E-03-response-off-0-multi-v1.json')
    files=copy.deepcopy(sample['config']['files'])
    files['values']=dict(files.get('values',{}), **sample['config']['values'])
    files['values'].update({'security.enabled':False,'unified-security.enabled':False,'logger.enabled':False})
    source=directory/'java-configuration-source';source.mkdir()
    proposed=SCOPE/'proposed'/('reversed' if profile=='reversed' else 'forward')
    for p in proposed.glob('*.yml'): files[p.stem]=read(p)
    files['lambda-proxy'].update(endpointOverride=endpoint,logType='None',connectionTimeout=10000,readTimeout=60000,
        writeTimeout=60000,apiCallTimeout=60000,apiCallAttemptTimeout=20000,metricsName='lambda-proxy',functions={'/x@post':'parity-echo-a'})
    if profile=='missing-executor': files['service']={'singletons':[]}
    if profile=='unknown-action': files['rule']['ruleBodies']['request-headers']['actions'][0]['actionClassName']='synthetic.unavailable.UnknownAction'
    if profile=='undefined-rule-characterization':
        files['rule']['endpointRules']['/x@post']['req-tra']=['undefined-synthetic-rule']
        files['rule']['endpointRules']['/x@post']['res-tra']=['undefined-synthetic-rule']
        files['rule']['endpointRules']['/x/warm@post']={'req-tra':['request-headers'],'res-tra':['response-headers']}
        files['lambda-proxy']['functions']['/x/warm@post']='parity-echo-a'
    for name,data in files.items(): write(source/(name+'.yml'),data)
    assert digest(JAVA_CONFIG)==JAVA_CONFIG_SHA
    with zipfile.ZipFile(JAVA_CONFIG) as z:
        for name in ['config.yml','status.yml']: (source/name).write_bytes(z.read(name))
    level=profile.removeprefix('privacy-') if profile.startswith('privacy-') else 'WARN'
    shutil.copyfile(SCOPE/'qualification/logging'/(level+'.xml'),source/'logback.xml')
    write(directory/'configuration-identities.json',{p.name:digest(p) for p in sorted(source.iterdir())})
    return source,level

def run(args):
    pins=candidate_pins(args); out=args.out.resolve(); assert out.is_relative_to(ARTIFACTS.resolve())
    out.mkdir(parents=True,exist_ok=False)
    plan=read(SCOPE/'TEST-PLAN.json');write(out/'frozen-plan.json',plan)
    assert digest(args.backend_zip)==BACKEND_ZIP_SHA
    write(out/'pins.json',{'candidate':read(args.candidate_manifest),'backendZipSha256':BACKEND_ZIP_SHA,'runnerSha256':digest(Path(__file__)),'AWSCalls':0})
    unpack(args.java_zip,out/'java-package','java',pins)
    (out/'backend-package').mkdir()
    with zipfile.ZipFile(args.backend_zip) as z:
        assert z.namelist()==['bootstrap']; binary=out/'backend-package/bootstrap';binary.write_bytes(z.read('bootstrap'));binary.chmod(0o755)
    assert digest(binary)==BACKEND_SHA
    managed=[];closed=set();bridge=None;rows=[];cleanup=[];log_checks=[]
    def close(rt):
        if rt.name not in closed: cleanup.append(rt.close());closed.add(rt.name)
    try:
        backend=Runtime('header-transformer-echo-a',out);managed.append(backend)
        backend.start([binary],dict(environment(),PARITY_BACKEND_IDENTITY='echo-a'),out)
        bridge=InvokeBridge({'parity-echo-a':backend});run_id=uuid.uuid4().hex
        for profile in dict.fromkeys(s['profile'] for s in plan['cases']):
            directory=out/profile;directory.mkdir();config,level=prepare(args,directory,profile,f'http://127.0.0.1:{bridge.server.server_port}')
            rt=Runtime('header-'+profile,out);managed.append(rt)
            env=environment();env['_HANDLER']='com.networknt.aws.lambda.app.LambdaApp::handleRequest'
            rt.start([out/'java-package/lambda-native','-Dlight-4j-config-dir='+str(config),'-Dlogback.configurationFile='+str(config/'logback.xml')],env,out)
            seen=set();canaries=[]
            for i,declared in enumerate(s for s in plan['cases'] if s['profile']==profile):
                step=copy.deepcopy(declared);step['body']='plain'
                if step['id']=='valid-rule-warm-endpoint':step['path']='/x/warm'
                if step['id']=='route-miss':step['path']='/missing'
                private='PRIVATE-'+uuid.uuid4().hex;canaries.append(private)
                step['body']=private
                attempt='attempt-'+uuid.uuid4().hex
                raw=event({'mode':'application-error' if step['id']=='application-error' else 'created','method':'POST','path':step.get('path','/x'),'body':step['body']},profile+'-'+str(i),attempt,run_id)
                raw['headers']={'x-unrelated-private':private,'authorization':'Bearer '+private,'cookie':'private='+private}
                if step['id']!='source-missing':raw['headers']['x-remove']='raw-source'
                write(directory/'events'/(str(i)+'.json'),raw);before=len(bridge.calls)
                result=rt.submit(raw);response=json.loads(result['payload']);calls=copy.deepcopy(bridge.calls[before:])
                errors=errors_for(profile,step,response,calls,seen)
                if result['kind']!='response':errors.append('outer Runtime error')
                row={'profile':profile,'id':step['id'],'coverage':step['coverage'],'attemptId':attempt,'gatewayPid':rt.process.pid,'gatewayRequestId':result['id'],'response':response,'calls':calls,'errors':errors,'passed':not errors}
                rows.append(row);write(directory/'results'/(str(i)+'.json'),row)
                rt.log.flush();logs=(out/(rt.name+'.log')).read_text()
                if any(c in logs for c in canaries):raise AssertionError('privacy leakage: '+profile+'/'+step['id'])
                if errors:raise AssertionError('expectation failure: '+profile+'/'+step['id']+': '+','.join(errors))
            close(rt)
            logs=(out/(rt.name+'.log')).read_text()
            checks={'profile':profile,'level':level,'actualRootStatus':('Setting level of ROOT logger to '+level) in logs,
                    'debugEmitted':'DEBUG com.networknt.rule.header.' in logs,
                    'traceEmitted':'TRACE com.networknt.aws.lambda.handler.middleware.transformer.' in logs,
                    'canaryLeak':any(c in logs for c in canaries)}
            log_checks.append(checks);write(out/'logging-checks.json',log_checks)
            assert checks['actualRootStatus'] and not checks['canaryLeak'], 'actual native logging filter/privacy unproven'
            if profile.startswith('privacy-'):
                assert checks['debugEmitted']==(level in ['DEBUG','TRACE']) and checks['traceEmitted']==(level=='TRACE'), 'effective logging level mismatch'
        backend.log.flush();records=[json.loads(s) for s in (out/(backend.name+'.log')).read_text().splitlines() if s.startswith('{')]
        entries=[r for r in records if r.get('phase')=='entry'];done=[r for r in records if r.get('phase')=='completion']
        write(out/'backend-records.json',records)
        assert len(rows)==20 and len(bridge.calls)==len(entries)==len(done)==14
        assert len({r['executionRequestId'] for r in entries})==14
        assert {r['executionRequestId'] for r in entries}=={r['executionRequestId'] for r in done}
        for row in rows:
            actual=[r for r in entries if r['attemptId']==row['attemptId']]
            assert len(actual)==len(row['calls'])
            for r,c in zip(actual,row['calls']):
                assert r['backendIdentity']=='echo-a' and r['backendVersion']=='1'
                assert r['executionRequestId']==c['backendExecutionRequestId']!=c['invokeApiRequestId']
        assert not bridge.errors
        write(out/'report.json',{'green':True,'expectationPasses':20,'backendExecutions':14,'backendCompletions':14,'zeroDispatch':6,'AWSCalls':0,'SDKWire':'unmeasured','pairedParity':'not claimed','headerActionsOnly':True})
        return 0
    except BaseException as e:
        write(out/'failure.json',{'type':type(e).__name__,'reason':str(e),'completedRequests':len(rows),'dispatches':len(bridge.calls) if bridge else 0})
        raise
    finally:
        write(out/'rows.json',rows)
        if bridge:write(out/'bridge-calls.json',bridge.calls)
        for rt in reversed(managed):close(rt)
        if bridge:bridge.close()
        write(out/'cleanup.json',cleanup)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path)
    p.add_argument('--fabric',type=Path,default=REPO.parent/'light-fabric-light-lambda')
    p.add_argument('--java-zip',type=Path,default=SCOPE/'candidate-build/java-native-header-transformer-candidate.zip')
    p.add_argument('--candidate-manifest',type=Path,default=SCOPE/'candidate-build/candidate-manifest.json')
    p.add_argument('--backend-zip',type=Path,default=ARTIFACTS/'parity-java-proxy-mitigation-20261023T020303Z/aws-scope-final/backend-bootstrap.zip')
    return run(p.parse_args())
if __name__=='__main__':raise SystemExit(main())
