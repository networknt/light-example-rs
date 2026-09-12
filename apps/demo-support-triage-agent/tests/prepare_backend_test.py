import importlib.util
import json
from pathlib import Path
import unittest
import uuid
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare', ROOT/'scripts/prepare-backend.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class Preparation(unittest.TestCase):
    def fixture(self):
        return {'runtimePolicy.envTag':'demo', 'a2aPolicy.bindings': [{'agentRef':'support-triage','backendKind':'EXTERNAL_SIDECAR',
            'bindingId':str(uuid.uuid4()),'publicationId':str(uuid.uuid4()),'policyDigest':'sha256:'+'a'*64,
            'allowedSkillIds':['support-triage'],'backendTransport':{'origin':'http://127.0.0.1:9010/',
            'audience':'support-triage-backend','contextKeyFile':'/run/secrets/triage-context-key',
            'dataBoundaryDigest':'sha256:'+'b'*64,'capabilities':{'contractVersion':'light-a2a-backend/v1',
            'streaming':False,'cancellation':False,'statusReconciliation':True,
            'acceptedContentModes':['text/plain'],'maximumArtifactBytes':65536}}}]}

    def test_identity_is_taken_from_selected_publication(self):
        values=self.fixture();binding=values['a2aPolicy.bindings'][0]
        for raw in (values['a2aPolicy.bindings'],json.dumps(values['a2aPolicy.bindings'])):
            config=prepare.prepare({'a2aPolicy.bindings':raw,'runtimePolicy.envTag':'demo'},'support-triage',str(uuid.uuid4()))
            self.assertEqual(config['bindingId'],binding['bindingId'])
            self.assertEqual(config['publicationId'],binding['publicationId'])
            self.assertEqual(config['policyDigest'],binding['policyDigest'])

    def test_rejects_remote_or_incompatible_capabilities(self):
        values=self.fixture();values['a2aPolicy.bindings'][0]['backendKind']='REMOTE_A2A'
        with self.assertRaises(ValueError):prepare.prepare(values,'support-triage',str(uuid.uuid4()))
        values=self.fixture();values['a2aPolicy.bindings'][0]['backendTransport']['capabilities']['streaming']=True
        with self.assertRaises(ValueError):prepare.prepare(values,'support-triage',str(uuid.uuid4()))

    def test_export_forms_preserve_non_dev_identity(self):
        raw=self.fixture()
        qualified={'a2a.'+key:value for key,value in raw.items()}
        for values in (raw,qualified):
            self.assertEqual(prepare.prepare(values,'support-triage',str(uuid.uuid4()))['environment'],'demo')
        with self.assertRaisesRegex(ValueError,'mix'):
            prepare.prepare(raw | qualified,'support-triage',str(uuid.uuid4()))

    def test_missing_or_invalid_environment_is_an_operator_error(self):
        for value in (None,'', '  ',12,[],{}):
            values=self.fixture();values['runtimePolicy.envTag']=value
            with self.assertRaisesRegex(ValueError,'envTag'):
                prepare.prepare(values,'support-triage',str(uuid.uuid4()))
        values=self.fixture();del values['runtimePolicy.envTag']
        with self.assertRaisesRegex(ValueError,'envTag'):
            prepare.prepare(values,'support-triage',str(uuid.uuid4()))

    def test_compose_keeps_namespace_and_secret_boundaries(self):
        services=yaml.safe_load((ROOT/'deploy/compose.yml').read_text())['services']
        backend=services['support-triage-backend'];sidecar=services['light-a2a'];network=services['triage-network']
        self.assertNotIn('depends_on',network)
        self.assertEqual(backend['network_mode'],'service:triage-network')
        self.assertEqual(sidecar['network_mode'],'service:triage-network')
        self.assertEqual(sidecar['depends_on']['support-triage-backend']['condition'],'service_healthy')
        self.assertNotIn('9010',str(network.get('ports')))
        self.assertNotIn('ports',backend)
        self.assertNotIn('ports',sidecar)
        self.assertNotIn('volumes',network)
        backend_secrets=[mount for mount in backend['volumes'] if 'SECRETS_DIR' in mount]
        self.assertEqual(len(backend_secrets),1)
        self.assertTrue(backend_secrets[0].endswith('/triage-context-key:/run/secrets/triage-context-key:ro'))
        self.assertTrue(any(mount.endswith(':/run/secrets:ro') for mount in sidecar['volumes']))
        self.assertTrue(all('profiles' not in service for service in services.values()))

if __name__=='__main__':unittest.main()
