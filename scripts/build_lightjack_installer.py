"""Build the separate Lightjack C3 loader and S3 installer; never flash hardware.

Lightjack additions, 2026-10-21. SPDX-License-Identifier: MIT.
Run in an activated ESP-IDF v6.1 environment with C3 and S3 tools installed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

IDF_COMMIT = 'fff9895c82d744c7237be8847347bdd1b07c6643'
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='Dedicated build directory outside this source checkout')
    args = parser.parse_args()
    sdk = Path(os.environ.get('IDF_PATH', '')).resolve()
    if not (sdk / 'tools/idf.py').is_file():
        parser.error('Activate the pinned ESP-IDF environment first')
    actual = subprocess.check_output(['git', '-C', str(sdk), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != IDF_COMMIT:
        parser.error('ESP-IDF checkout does not match the pinned v6.1 commit')
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error('Build output must be outside the source checkout')
    marker = output / 'lightjack-build.json'
    expected = {'source': str(ROOT), 'idf_commit': IDF_COMMIT}
    if output.exists():
        if not marker.is_file() or json.loads(marker.read_text()) != expected:
            parser.error('Existing output is not this project\'s dedicated build directory')
    else:
        output.mkdir(parents=True)
        marker.write_text(json.dumps(expected, indent=2) + '\n', encoding='utf-8')

    def build(profile, *definitions):
        build_dir = output / profile
        subprocess.run([sys.executable, str(sdk / 'tools/idf.py'),
                        '-C', str(ROOT / 'src' / ('lightjack-' + profile)),
                        '-B', str(build_dir), '-D', 'SDKCONFIG=' + str(build_dir / 'sdkconfig'),
                        *definitions, 'build'], check=True)

    build('loader')
    loader = output / 'loader/wyze_loader.bin'
    if not 0 < loader.stat().st_size <= 0x1e0000:
        raise ValueError('Loader image does not fit the bulb OTA slot')
    payload = output / 'payload/payload.bin'
    payload.parent.mkdir(exist_ok=True)
    shutil.copyfile(loader, payload)
    if loader.read_bytes() != payload.read_bytes():
        raise ValueError('Loader payload copy differs from the completed build')
    build('installer', '-D', 'LIGHTJACK_LOADER_PAYLOAD=' + str(payload))
    installer = output / 'installer/lightjack_installer.bin'
    if not 0 < installer.stat().st_size <= 0x300000:
        raise ValueError('Installer image does not fit its separate S3 application slot')
    embedded = installer.read_bytes()
    if embedded.count(payload.read_bytes()) != 1:
        raise ValueError('S3 image does not contain exactly one matching C3 loader payload')
    artifacts = {}
    for name in ('loader/wyze_loader.bin', 'installer/bootloader/bootloader.bin',
                 'installer/partition_table/partition-table.bin', 'installer/lightjack_installer.bin'):
        data = (output / name).read_bytes()
        artifacts[name] = {'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    evidence = {'idf_commit': IDF_COMMIT, 'hardware_tested': False,
                'embedded_loader_matches': True, 'artifacts': artifacts}
    (output / 'build-results.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
