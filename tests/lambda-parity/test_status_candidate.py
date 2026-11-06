import argparse,hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import integration
class StatusCandidatePins(unittest.TestCase):
 def candidate(self,root):
  accepted=root/'accepted.zip';candidate=root/'candidate.zip'
  for f,b in [(accepted,b'old'),(candidate,b'new')]:
   with zipfile.ZipFile(f,'w') as z:z.writestr('bootstrap',b'unchanged');z.writestr('lambda-native',b)
  pins={'java':integration.digest(accepted),'rust':'unchanged'}
  value={'schema':'parity-local-candidate/v1','acceptedZipSha256':pins['java'],'zip':str(candidate),'zipSha256':integration.digest(candidate),'binarySha256':hashlib.sha256(b'new').hexdigest(),'approvedPatchSha256':'0e1483723185d6210712c0d121e545ed7d7ae1f2a95090c34a412aeae60b5d96','baseCandidateZipSha256':'923ea10b515c85a904336345a1b71d5138a6f0a1612b2785ca32ecfa89a7728d','approvedPatchChain':['f9f14577063c94b5784daee4d7252897fc6baf1d71148bf48aed0e872a4a37fa','0e1483723185d6210712c0d121e545ed7d7ae1f2a95090c34a412aeae60b5d96']}
  return accepted,candidate,pins,value
 def check(self,mutate=None):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);accepted,candidate,pins,value=self.candidate(root)
   if mutate:mutate(value)
   manifest=root/'manifest.json';manifest.write_text(json.dumps(value));args=argparse.Namespace(candidate_manifest=manifest,java_zip=candidate)
   with patch.object(integration,'JAVA_ZIP',accepted),patch.object(integration,'PINNED',pins):return integration.candidate_pins(args),pins,value
 def test_explicit_chain_accepts_new_candidate_and_preserves_default_pins(self):
  result,pins,value=self.check();self.assertEqual(result,dict(pins,java=value['zipSha256']))
 def test_missing_original_patch_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'provenance drift'):self.check(lambda v:v.update(approvedPatchChain=[v['approvedPatchSha256']]))
 def test_unpinned_base_candidate_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'provenance drift'):self.check(lambda v:v.update(baseCandidateZipSha256='wrong'))
if __name__=='__main__':unittest.main()
