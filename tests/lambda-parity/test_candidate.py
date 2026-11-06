import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import integration


class CandidateSelection(unittest.TestCase):
    def test_absent_manifest_preserves_accepted_pins(self):
        self.assertEqual(integration.candidate_pins(argparse.Namespace()), integration.PINNED)

    def test_candidate_is_explicit_hashed_and_keeps_accepted_bootstrap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            accepted, candidate = root / 'accepted.zip', root / 'candidate.zip'
            for path, binary in [(accepted, b'old'), (candidate, b'new')]:
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.writestr('bootstrap', b'unchanged startup')
                    archive.writestr('lambda-native', binary)
            pins = {'java': integration.digest(accepted), 'rust': 'unchanged-rust'}
            manifest = root / 'manifest.json'
            value = {'schema': 'parity-local-candidate/v1', 'acceptedZipSha256': pins['java'],
                     'approvedPatchSha256': 'f9f14577063c94b5784daee4d7252897fc6baf1d71148bf48aed0e872a4a37fa',
                     'zip': str(candidate), 'zipSha256': integration.digest(candidate),
                     'binarySha256': hashlib.sha256(b'new').hexdigest()}
            manifest.write_text(json.dumps(value))
            args = argparse.Namespace(candidate_manifest=manifest, java_zip=candidate)
            with patch.object(integration, 'JAVA_ZIP', accepted), patch.object(integration, 'PINNED', pins):
                self.assertEqual(integration.candidate_pins(args), dict(pins, java=value['zipSha256']))
                self.assertEqual(integration.PINNED, pins)
                value['approvedPatchSha256'] = 'unapproved'
                manifest.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, 'drift'):
                    integration.candidate_pins(args)
                value['approvedPatchSha256'] = 'f9f14577063c94b5784daee4d7252897fc6baf1d71148bf48aed0e872a4a37fa'
                value['binarySha256'] = 'wrong'
                manifest.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, 'native binary drift'):
                    integration.candidate_pins(args)


if __name__ == '__main__':
    unittest.main()
