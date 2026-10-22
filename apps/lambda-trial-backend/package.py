#!/usr/bin/env python3
"""Package a compiled x86_64 musl backend; never uploads or calls AWS."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
data = args.binary.read_bytes()
if data[:4] != b'\x7fELF' or data[4:6] != b'\x02\x01' or data[18:20] != b'\x3e\x00':
    parser.error('expected a little-endian x86_64 ELF executable')
args.out.mkdir(parents=True, exist_ok=False)
entry = zipfile.ZipInfo('bootstrap', date_time=(1980, 1, 1, 0, 0, 0))
entry.create_system = 3
entry.external_attr = 0o100755 << 16
entry.compress_type = zipfile.ZIP_DEFLATED
archive = args.out / 'bootstrap.zip'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
    output.writestr(entry, data)
with zipfile.ZipFile(archive) as output:
    assert output.namelist() == ['bootstrap']
    assert output.read('bootstrap') == data
    assert (output.getinfo('bootstrap').external_attr >> 16) & 0o777 == 0o755
manifest = {
    'binarySha256': hashlib.sha256(data).hexdigest(),
    'zipSha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
    'target': 'x86_64-unknown-linux-musl',
    'runtime': 'provided.al2023', 'handler': 'bootstrap',
    'qualification': 'separate synthetic backend; not the qualified gateway ZIP',
}
(args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest))
