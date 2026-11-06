#!/usr/bin/env python3
"""Local Specification -> verified JWT/scope -> real proxy backend composition.

Synthetic RSA keys/tokens stay in memory. Loopback JWKS and production SDK paths;
no AWS calls, live credentials, worker execution or production code changes.
"""
import argparse,base64,copy,hashlib,http.server,importlib.util,json,threading,time,uuid,zipfile,os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa,padding
from cryptography.hazmat.primitives import hashes
from integration import Runtime,InvokeBridge,environment,configure,unpack,candidate_pins,RUST_ZIP
from error_integration import CANDIDATE,BACKEND_SHA,BACKEND_ZIP_SHA
from run import ARTIFACTS,REPO,read,write,digest,event
SEQUENCE=[('valid-a','created',201,None,1),('missing','created',401,'ERR10002',0),('valid-a','created',201,None,1),('invalid-signature','created',401,'ERR10000',0),('valid-b','created',201,None,1),('wrong-scope','created',403,'ERR10005',0),('valid-b','created',201,None,1),('valid-a','application-error',500,None,1),('valid-b','created',201,None,1),('valid-a','function-error',None,None,1),('valid-b','created',201,None,1),('expired','created',401,'ERR10001',0),('valid-a','created',201,None,1),('valid-b','created',201,None,1)]
def b64(raw):return base64.urlsafe_b64encode(raw).decode().rstrip('=')
def integer(n):return b64(n.to_bytes((n.bit_length()+7)//8,'big'))
def credentials():
 key=rsa.generate_private_key(public_exponent=65537,key_size=2048);wrong=rsa.generate_private_key(public_exponent=65537,key_size=2048);pub=key.public_key().public_numbers()
 jwks={'keys':[{'kty':'RSA','alg':'RS256','use':'sig','kid':'local-parity','n':integer(pub.n),'e':integer(pub.e)}]};tokens={};now=int(time.time())
 for label in ['valid-a','valid-b','invalid-signature','wrong-scope','expired']:
  claims={'sub':label,'user_id':label,'client_id':'synthetic-client','iss':'test-issuer','aud':'test-audience','iat':now-7200,'exp':now-3600 if label=='expired' else now+3600,'jti':uuid.uuid4().hex,'scp':['write'] if label=='wrong-scope' else ['read']}
  raw=b64(json.dumps({'alg':'RS256','kid':'local-parity'}).encode())+'.'+b64(json.dumps(claims).encode());signer=wrong if label=='invalid-signature' else key;tokens[label]=raw+'.'+b64(signer.sign(raw.encode(),padding.PKCS1v15(),hashes.SHA256()))
 return jwks,tokens
class Jwks:
 def __init__(self,value):
  self.calls=[];owner=self;data=json.dumps(value).encode()
  class Handler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    owner.calls.append({'method':'GET','path':self.path})
    if self.path!='/jwks':self.send_error(404);return
    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 @property
 def url(self):return 'http://127.0.0.1:'+str(self.server.server_port)
 def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
def sanitized_call(call):
 c=copy.deepcopy(call);c.pop('requestBytesBase64',None);present=False
 for field in ['headers','multiValueHeaders']:
  values=c['event'].get(field) or {}
  for key in list(values):
   if key.lower() in ['authorization','x-scope-token','cookie']:values.pop(key);present=True
 c['credentialFieldsRemoved']=present;return c

def profile(args,out,endpoint,jwks,rust):
 sample=read(args.fabric/'tests/serverless-conformance/fixtures/v1/s/S-05-scope-list-multi-contract-v1.json');files=sample['config']['files'];files['lambda-proxy']['functions']={'/x@get':'parity-echo-a'}
 files['client']['oauth']['token']['key']['server_url']=jwks
 files['security']['enabled']=True
 sample['config']['values']['openapi-handler.enabled']=True
 files['cache']={'enabled':False,'caches':[{'cacheName':'token','maxSize':100,'expiryInMinutes':15}]}
 files['service']={'singletons':[{'com.networknt.cache.CacheManager':['com.networknt.cache.CaffeineCacheManager']}]}
 java,_=configure(args,out,sample,endpoint,rust)
 native_cache={'caches':[{'cacheName':'jwt','maxSize':1000,'expiryInMinutes':15},{'cacheName':'jwk','maxSize':1000,'expiryInMinutes':600}]}
 (java/'cache.yml').write_text(json.dumps(native_cache,indent=2)+'\n')
 # Reuse the native conformance empty-JKS bootstrap convention for loopback HTTP.
 # No private key or real certificate/credential is loaded. Rust keeps PEM/JKS admission unchanged.
 store_source=java/'EmptyTrust.java';store_source.write_text('import java.nio.file.*;import java.security.*;class EmptyTrust{public static void main(String[]a)throws Exception{var s=KeyStore.getInstance("JKS");s.load(null,"test-only-store".toCharArray());try(var o=Files.newOutputStream(Path.of(a[0]))){s.store(o,"test-only-store".toCharArray());}}}')
 import subprocess
 result=subprocess.run(['rtk','proxy','java',str(store_source),str(java/'test-only-truststore.jks')],capture_output=True,text=True,check=True)
 (out/'empty-truststore-helper.log').write_text(result.stdout+result.stderr)
 native_client=read(java/'client.yml');native_client['tls'].update(loadDefaultTrustStore=False,loadTrustStore=True,trustStore='test-only-truststore.jks',trustStorePass='test-only-store')
 (java/'client.yml').write_text(json.dumps(native_client,indent=2)+'\n')
 # configure() deliberately closes authentication for its proxy-only profile.
 # This additive profile explicitly restores the approved security configuration
 # in a new source/layer; it never changes configure() or the original fixtures.
 source=out/'configuration-source';values=read(source/'values.yml');values.update({'security.enabled':True,'unified-security.enabled':False,'security.issuer':'test-issuer','security.audience':['test-audience'],'security.skipVerifyScopeWithoutSpec':False,'client.tokenKeyServerUrl':jwks,'client.tokenKeyUri':'/jwks','client.tokenKeyEnableHttp2':False})
 for path in [source/'values.yml',java/'values.yml']:path.write_text(json.dumps(values,indent=2)+'\n')
 spec=importlib.util.spec_from_file_location('jwt_layer_pack',args.fabric/'apps/light-lambda/scripts/package_baseline.py');pack=importlib.util.module_from_spec(spec);spec.loader.exec_module(pack)
 from unittest.mock import patch
 with patch.dict(os.environ,{'LIGHT_LAMBDA_ALLOW_INSECURE_TEST_ENDPOINTS':'1'}):info=pack.layer(source,out/'jwt-config-layer.zip',rust)
 pack.extract_layer(out/'jwt-config-layer.zip',out/'jwt-opt');write(out/'jwt-layer-report.json',info)
 return java,out/'jwt-opt'
def run(args):
 pins=candidate_pins(args);out=args.out.resolve();assert out.is_relative_to(ARTIFACTS.resolve());out.mkdir(parents=True,exist_ok=False)
 write(out/'declared-sequence.json',{'schema':'lambda-parity-jwt-composition/v1','sequence':SEQUENCE,'functionError':{'java':[500,'ERR14004'],'rust':[502,'ERR14014']},'JWKSFetchesPerGateway':1,'perSideBackendEntries':10,'perSideCompletions':9,'originalFixture':'S-05-scope-list-multi-contract-v1','credentialPolicy':'synthetic RS256 only; private keys and tokens in memory; credential fields excluded from persisted Invoke receipts','AWSCalls':0})
 write(out/'identities.json',{'gatewayZipSha256':pins,'backendZipSha256':digest(args.backend_zip),'sourceSha256':digest(Path(__file__))})
 assert digest(args.backend_zip)==BACKEND_ZIP_SHA;(out/'backend-package').mkdir()
 with zipfile.ZipFile(args.backend_zip) as z:binary=out/'backend-package/bootstrap';binary.write_bytes(z.read('bootstrap'));binary.chmod(0o755)
 assert digest(binary)==BACKEND_SHA
 runtimes=[];bridges=[];jwks_servers=[];cleanup=[];rows=[];allcalls=[];secret_values=[];records=[]
 try:
  for side,z in [('java',args.java_zip),('rust',RUST_ZIP)]:unpack(z,out/(side+'-package'),side,pins)
  for side in ['java','rust']:
   directory=out/side;directory.mkdir();jwks,tokens=credentials();secret_values.extend(tokens.values());keys=Jwks(jwks);jwks_servers.append(keys);write(directory/'public-jwks.json',jwks)
   backend=Runtime('jwt-'+side+'-echo-a',out);runtimes.append(backend);backend.start([binary],dict(environment(),PARITY_BACKEND_IDENTITY='echo-a',PARITY_BACKEND_OBSERVATIONS='synthetic-v1'),out)
   bridge=InvokeBridge({'parity-echo-a':backend});bridges.append(bridge);java,rust=profile(args,directory,f'http://127.0.0.1:{bridge.server.server_port}',keys.url,out/'rust-package/bootstrap')
   rt=Runtime('jwt-'+side+'-gateway',out);runtimes.append(rt);env=environment();env['_HANDLER']='com.networknt.aws.lambda.app.LambdaApp::handleRequest'
   if side=='java':cmd=[out/'java-package/lambda-native','-Dlight-4j-config-dir='+str(java),'-Dlogback.configurationFile='+str(java/'logback.xml')]
   else:
    cmd=[out/'rust-package/bootstrap'];env.update(LIGHT_LAMBDA_CONFIG_DIR=str(rust),LIGHT_LAMBDA_ALLOW_INSECURE_TEST_ENDPOINTS='1',LIGHT_LAMBDA_GATEWAY_ARN='arn:aws:lambda:us-east-1:000000000000:function:'+rt.name)
   rt.start(cmd,env,out);run_id=uuid.uuid4().hex
   for i,(credential,mode,status,code,dispatch) in enumerate(SEQUENCE):
    raw=event({'mode':mode,'method':'GET','path':'/x'},'JWT-'+str(i),side+'-'+uuid.uuid4().hex,run_id)
    raw['headers']={}
    if credential!='missing':raw['headers']={'authorization':'Bearer '+tokens[credential]};raw['multiValueHeaders']['authorization']=['Bearer '+tokens[credential]]
    before=len(bridge.calls);res=rt.submit(raw);response=json.loads(res['payload']);calls=bridge.calls[before:];errors=[]
    expected_status,expected_code=(500,'ERR14004') if side=='java' else (502,'ERR14014')
    if mode!='function-error':expected_status,expected_code=status,code
    if res['kind']!='response':errors.append({'field':'outerRuntime','actual':res['kind']})
    if response.get('statusCode')!=expected_status:errors.append({'field':'status','expected':expected_status,'actual':response.get('statusCode')})
    if expected_code:
     try:actual_code=json.loads(response['body'])['code']
     except (ValueError,TypeError,KeyError):actual_code=None
     if actual_code!=expected_code:errors.append({'field':'code','expected':expected_code,'actual':actual_code})
    else:
     wanted='{"code":"PARITY_APPLICATION_ERROR"}' if mode=='application-error' else '{"result":"created"}'
     if response.get('body')!=wanted:errors.append({'field':'body','expected':wanted,'actual':response.get('body')})
    if len(calls)!=dispatch:errors.append({'field':'InvokeCount','expected':dispatch,'actual':len(calls)})
    if len(keys.calls)!=1:errors.append({'field':'JWKSFetches','expected':1,'actual':len(keys.calls)})
    for value in tokens.values():
     if value in json.dumps(response):errors.append({'field':'credentialPrivacy'})
    row={'side':side,'step':i,'credentialRecipe':credential,'mode':mode,'response':response,'outerRuntime':res['kind'],'gatewayRequestId':res['id'],'gatewayPid':rt.process.pid,'InvokeCalls':len(calls),'JWKSFetches':len(keys.calls),'attemptId':raw['multiValueHeaders']['x-parity-attempt'][0],'rawEventSha256':hashlib.sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest(),'calls':[sanitized_call(c) for c in calls],'passed':not errors,'errors':errors};rows.append(row);write(directory/'results'/(str(i)+'.json'),row)
   backend.log.flush()
   side_records=[json.loads(line) for line in (out/(backend.name+'.log')).read_text().splitlines() if line.startswith('{')];records+=side_records
   write(directory/'JWKS-calls.json',keys.calls);allcalls.extend([sanitized_call(c) for c in bridge.calls])
   assert not bridge.errors,bridge.errors
  entries=[r for r in records if r.get('phase')=='entry'];done=[r for r in records if r.get('phase')=='completion'];observed=[r for r in records if r.get('schema')=='parity-request-observation/v1'];count_errors=[]
  if len(entries)!=20 or len({r['executionRequestId'] for r in entries})!=20 or len(done)!=18 or len({r['executionRequestId'] for r in done})!=18:count_errors.append('backend entry/completion counts')
  if len(allcalls)!=20 or {r['executionRequestId'] for r in entries}!={c['backendExecutionRequestId'] for c in allcalls}:count_errors.append('Invoke/entry identity joins')
  for row in rows:
   actual=[r for r in entries if r['attemptId']==row['attemptId']]
   if len(actual)!=row['InvokeCalls']:count_errors.append('per-attempt dispatch')
  if len(observed)!=20 or {r['executionRequestId'] for r in observed}!={r['executionRequestId'] for r in entries}:count_errors.append('backend observation identities')
  write(out/'backend-records.json',records);write(out/'sanitized-Invoke-receipts.json',allcalls)
  green=all(r['passed'] for r in rows) and not count_errors
  report={'schema':'lambda-parity-jwt-local/v1','green':green,'AWSCalls':0,'gatewayExpectations':len(rows),'expectationPasses':sum(r['passed'] for r in rows),'InvokeCalls':len(allcalls),'backendEntries':len(entries),'backendCompletions':len(done),'backendReceivedRecords':len(observed),'JWKSFetches':sum(len(s.calls) for s in jwks_servers),'gatewayZipSha256':pins,'errors':count_errors,'rows':rows,'environmentReuse':'one actual process per side; warm sequential composition','credentialStorage':'tokens/private keys remain in memory; event credentials and raw SDK bytes excluded from reports'}
  write(out/'report.json',report);print(json.dumps({k:v for k,v in report.items() if k!='rows'}));return 0 if green else 1
 except BaseException as error:
  write(out/'failure.json',{'type':type(error).__name__,'reason':str(error)});write(out/'partial-results.json',rows);raise
 finally:
  for rt in reversed(runtimes):cleanup.append(rt.close())
  for bridge in bridges:bridge.close()
  for server in jwks_servers:server.close()
  write(out/'cleanup.json',cleanup)
  leaks=[]
  for path in out.rglob('*'):
   if path.is_file() and path.suffix not in ['.zip'] and path.name!='bootstrap':
    raw=path.read_bytes()
    if any(t.encode() in raw for t in secret_values):leaks.append(str(path.relative_to(out)))
  write(out/'credential-privacy.json',{'passed':not leaks,'filesWithSyntheticTokenBytes':leaks,'realCredentialsUsed':False})
  assert not leaks,'synthetic token bytes leaked; see credential-privacy.json'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path);p.add_argument('--fabric',type=Path,default=REPO.parent/'light-fabric-light-lambda');p.add_argument('--java-zip',type=Path,default=CANDIDATE/'java-native-proxy-mitigation-candidate.zip');p.add_argument('--candidate-manifest',type=Path,default=CANDIDATE/'candidate-manifest.json');p.add_argument('--backend-zip',type=Path,default=CANDIDATE/'aws-scope-final/backend-bootstrap.zip');return run(p.parse_args())
if __name__=='__main__':raise SystemExit(main())
