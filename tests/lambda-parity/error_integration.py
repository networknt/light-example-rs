#!/usr/bin/env python3
"""Actual packaged Init/service/SDK -> existing running parity backend.

Additive frozen side-specific expectations; original case/fixture files unchanged.
This profile never contacts AWS or fabricates backend replies.
"""
import argparse,base64,copy,json,uuid,zipfile,hashlib
from pathlib import Path
from integration import Runtime,InvokeBridge,environment,configure,unpack,candidate_pins,RUST_ZIP
from run import ARTIFACTS,REPO,HERE,read,write,digest,event
CANDIDATE=ARTIFACTS/'parity-java-proxy-mitigation-20261023T020303Z'
BACKEND_SHA='729ff94f614b92a1a3f2252f974f5753ce03fc4435a962094c1ca477763fa256'
BACKEND_ZIP_SHA='4e0bb9cc4e5c38e892a25f49713a157e1f878452b5ab78073e695465101cd974'

def response_errors(side,mode,response,contract):
 expected=contract['expectations'][side][mode];errors=[]
 if response.get('statusCode')!=expected['status']:errors.append({'field':'status','expected':expected['status'],'actual':response.get('statusCode')})
 if response.get('isBase64Encoded')!=expected['base64']:errors.append({'field':'base64','expected':expected['base64'],'actual':response.get('isBase64Encoded')})
 if 'body' in expected and response.get('body')!=expected['body']:errors.append({'field':'body','expected':expected['body'],'actual':response.get('body')})
 if 'code' in expected:
  try:code=json.loads(response['body'])['code']
  except (ValueError,KeyError,TypeError):code=None
  if code!=expected['code']:errors.append({'field':'code','expected':expected['code'],'actual':code})
  for forbidden in contract['privacyExcluded']:
   if forbidden in json.dumps(response):errors.append({'field':'privacy','leaked':forbidden})
 headers={k.lower():v for k,v in (response.get('headers') or {}).items()}
 headers.update({k.lower():v[-1] for k,v in (response.get('multiValueHeaders') or {}).items()})
 if 'headers' in expected:
  if headers!=expected['headers']:errors.append({'field':'headers','expected':expected['headers'],'actual':headers})
 elif headers.get('content-type')!='application/json':errors.append({'field':'content-type','actual':headers})
 return errors

def execution_errors(records,calls,expected):
 entries=[r for r in records if r.get('schema')=='parity-execution/v1' and r.get('phase')=='entry'];done=[r for r in records if r.get('schema')=='parity-execution/v1' and r.get('phase')=='completion'];errors=[]
 if len(entries)!=expected or len({r['executionRequestId'] for r in entries})!=expected:errors.append('entry count/identity')
 if len(calls)!=expected or len({r['backendExecutionRequestId'] for r in calls})!=expected:errors.append('Invoke count/identity')
 normal={c['backendExecutionRequestId'] for c in calls if c.get('backendResultKind')=='response'}
 if len(done)!=len(normal) or {r['executionRequestId'] for r in done}!=normal:errors.append('completion count/identity')
 if {r['executionRequestId'] for r in entries}!={c['backendExecutionRequestId'] for c in calls}:errors.append('entry/Invoke join')
 by_id={r['executionRequestId']:r for r in entries}
 for c in calls:
  r=by_id.get(c['backendExecutionRequestId']);ev=c['event']
  if not r or r['attemptId']!=ev['multiValueHeaders']['x-parity-attempt'][0] or r['mode']!=ev['multiValueHeaders']['x-parity-case'][0] or r['backendIdentity']!='echo-a' or r['backendVersion']!='1':errors.append('backend identity/attempt/mode')
  if not c['signed'] or c['invoke']['logType']!='None' or c['invokeApiRequestId']==c['backendExecutionRequestId']:errors.append('Invoke transport contract')
 return errors

def run(args):
 pins=candidate_pins(args);contract=read(HERE/'errors-v1.json');out=args.out.resolve()
 assert out.is_relative_to(ARTIFACTS.resolve());out.mkdir(parents=True,exist_ok=False)
 write(out/'declared-contract.json',contract)
 write(out/'pre-execution.json',{'gatewayPins':pins,'contractSha256':digest(HERE/'errors-v1.json'),'backendZipSha256':digest(args.backend_zip),'sourceSha256':digest(Path(__file__)),'AWSCalls':0})
 assert digest(args.backend_zip)==BACKEND_ZIP_SHA
 (out/'backend-package').mkdir()
 with zipfile.ZipFile(args.backend_zip) as z:
  assert z.namelist()==['bootstrap'];binary=out/'backend-package/bootstrap';binary.write_bytes(z.read('bootstrap'));binary.chmod(0o755)
 assert digest(binary)==BACKEND_SHA
 managed=[];bridge=None;rows=[];cleanup=[]
 try:
  for side,z in [('java',args.java_zip),('rust',RUST_ZIP)]:unpack(z,out/(side+'-package'),side,pins)
  backend=Runtime('errors-echo-a',out);managed.append(backend);backend.start([binary],dict(environment(),PARITY_BACKEND_IDENTITY='echo-a'),out)
  bridge=InvokeBridge({'parity-echo-a':backend})
  fixture=args.fabric/'tests/serverless-conformance/fixtures/v1/e/E-03-response-off-0-multi-v1.json';sample=read(fixture)
  sample['config']['files']['lambda-proxy']['functions']={'/parity/a@post':'parity-echo-a'}
  java,rust=configure(args,out,sample,f'http://127.0.0.1:{bridge.server.server_port}',out/'rust-package/bootstrap')
  run_id=uuid.uuid4().hex
  for side in ['java','rust']:
   rt=Runtime('errors-'+side+'-gateway',out);managed.append(rt);env=environment();env['_HANDLER']='com.networknt.aws.lambda.app.LambdaApp::handleRequest'
   if side=='java':cmd=[out/'java-package/lambda-native','-Dlight-4j-config-dir='+str(java),'-Dlogback.configurationFile='+str(java/'logback.xml')]
   else:
    cmd=[out/'rust-package/bootstrap'];env.update(LIGHT_LAMBDA_CONFIG_DIR=str(rust),LIGHT_LAMBDA_ALLOW_INSECURE_TEST_ENDPOINTS='1',LIGHT_LAMBDA_GATEWAY_ARN='arn:aws:lambda:us-east-1:000000000000:function:'+rt.name)
   rt.start(cmd,env,out)
   for index,mode in enumerate(contract['sequence']):
    attempt=side+'-'+uuid.uuid4().hex;raw=event({'mode':mode},'ERRORS-'+mode,attempt,run_id);before=len(bridge.calls)
    write(out/'events'/side/(str(index)+'.json'),raw);result=rt.submit(raw);response=json.loads(result['payload']);calls=copy.deepcopy(bridge.calls[before:]);errors=response_errors(side,mode,response,contract)
    if result['kind']!='response':errors.append({'field':'outerRuntime','actual':result['kind']})
    if len(calls)!=1:errors.append({'field':'dispatchCount','expected':1,'actual':len(calls)})
    if calls and calls[0]['backendResultKind']!=('error' if mode=='function-error' else 'response'):errors.append({'field':'backendRuntimeKind'})
    row={'side':side,'mode':mode,'step':index,'attemptId':attempt,'gatewayRequestId':result['id'],'gatewayPid':rt.process.pid,'response':response,'rawResponseBase64':base64.b64encode(result['payload']).decode(),'calls':calls,'passed':not errors,'errors':errors};rows.append(row)
    write(out/'results'/side/(str(index)+'.json'),row)
  backend.log.flush();records=[]
  for line in (out/'errors-echo-a.log').read_text().splitlines():
   if line.startswith('{'):records.append(json.loads(line))
  errs=execution_errors(records,bridge.calls,22)+bridge.errors
  write(out/'backend-records.json',records);write(out/'invoke-transport.json',bridge.calls)
  pairs=[{'step':i,'mode':contract['sequence'][i],'contractPass':all(r['passed'] for r in rows if r['step']==i),'byteIdentical':len({r['rawResponseBase64'] for r in rows if r['step']==i})==1} for i in range(11)]
  green=all(r['passed'] for r in rows) and not errs
  report={'schema':'lambda-parity-errors-local/v1','green':green,'AWSCalls':0,'topology':'real packaged Init/service/SDK -> owned Invoke HTTP -> running backend Runtime API','gatewayExpectations':len(rows),'expectationPasses':sum(r['passed'] for r in rows),'pairedContracts':sum(p['contractPass'] for p in pairs),'byteIdenticalPairs':sum(p['byteIdentical'] for p in pairs),'backendEntries':sum(r.get('phase')=='entry' for r in records),'backendCompletions':sum(r.get('phase')=='completion' for r in records),'InvokeCalls':len(bridge.calls),'gatewayZipSha256':pins,'backendBinarySha256':digest(binary),'originalJavaAssertionConflict':'open; candidate mitigation only','broaderExchangeStateDefect':'open','errors':errs,'pairs':pairs,'rows':rows}
  write(out/'report.json',report);print(json.dumps({k:v for k,v in report.items() if k not in ['rows','pairs']}));return 0 if green else 1
 except BaseException as error:
  write(out/'failure.json',{'type':type(error).__name__,'reason':str(error)});write(out/'partial-results.json',rows)
  if bridge:write(out/'partial-invokes.json',bridge.calls)
  raise
 finally:
  for rt in reversed(managed):cleanup.append(rt.close())
  if bridge:bridge.close()
  write(out/'cleanup.json',cleanup)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path);p.add_argument('--fabric',type=Path,default=REPO.parent/'light-fabric-light-lambda');p.add_argument('--java-zip',type=Path,default=CANDIDATE/'java-native-proxy-mitigation-candidate.zip');p.add_argument('--candidate-manifest',type=Path,default=CANDIDATE/'candidate-manifest.json');p.add_argument('--backend-zip',type=Path,default=CANDIDATE/'aws-scope-final/backend-bootstrap.zip');return run(p.parse_args())
if __name__=='__main__':raise SystemExit(main())
