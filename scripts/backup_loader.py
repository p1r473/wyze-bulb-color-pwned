"""Read and verify a post-loader Wyze flash snapshot without writing the bulb.

Lightjack additions, 2026-10-21. SPDX-License-Identifier: MIT.
Uses the existing wyze-loader GET /info, /parts and /dump interfaces.
This is not a pristine factory backup or an authenticated device connection.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import http.client
import ipaddress
import json
import math
from pathlib import Path
import re
import socket
import threading
import time

FLASH_SIZE = 0x400000
CHUNK_SIZE = 0x10000
REFERENCE = Path(__file__).resolve().parents[1] / 'src/wyze-loader/partitions_wyze.csv'


def expected_partitions():
    with REFERENCE.open(encoding='utf-8', newline='') as source:
        return {row[0]: (int(row[3], 0), int(row[4], 0)) for row in csv.reader(source)
                if row and not row[0].startswith('#')}


def validate_metadata(info, parts):
    if not isinstance(info, dict) or not isinstance(parts, list):
        raise ValueError('Invalid loader metadata types')
    if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', str(info.get('mac', ''))):
        raise ValueError('Missing loader MAC identity')
    if {info.get('running'), info.get('target')} != {'ota_0', 'ota_1'}:
        raise ValueError('Running and target slots must be distinct Wyze OTA slots')
    observed = {}
    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get('label'), str):
            raise ValueError('Malformed partition metadata')
        label = part['label']
        if label in observed or type(part.get('offset')) is not int or type(part.get('size')) is not int:
            raise ValueError('Duplicate partition or invalid offset/size')
        observed[label] = (part['offset'], part['size'])
        if label in ('ota_0', 'ota_1'):
            if part.get('type') != 0 or part.get('subtype') != (16 if label == 'ota_0' else 17):
                raise ValueError('Unexpected OTA partition type')
    if observed != expected_partitions():
        raise ValueError('Partition map differs from the pinned Wyze 4 MiB layout')


def read_get(host, port, path, limit, timeout, deadline, exact=None):
    request_deadline = min(deadline, time.monotonic() + timeout)
    remaining = request_deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Backup deadline exceeded')
    connection = http.client.HTTPConnection(host, port, timeout=remaining)
    timer = None
    try:
        connection.connect()
        peer = connection.sock
        # A socket idle timeout alone does not bound trickling HTTP headers/body.
        def expire():
            try:
                peer.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            peer.close()
        remaining = request_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Backup request deadline exceeded')
        timer = threading.Timer(remaining, expire)
        timer.daemon = True
        timer.start()
        connection.request('GET', path, headers={'Connection': 'close', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f'Loader GET failed with HTTP {response.status}; redirects are not followed')
        if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
            raise ValueError('Unexpected encoded response')
        data = bytearray()
        while True:
            if time.monotonic() >= request_deadline:
                raise TimeoutError('Backup request deadline exceeded')
            block = response.read1(min(8192, limit + 1 - len(data)))
            if not block:
                break
            data.extend(block)
            if len(data) > limit:
                raise ValueError('Loader response exceeded its size limit')
        if time.monotonic() >= request_deadline:
            raise TimeoutError('Backup request completed after its deadline')
        if exact is not None and len(data) != exact:
            raise ValueError(f'Truncated flash read: expected {exact}, received {len(data)}')
        return bytes(data)
    finally:
        if timer is not None:
            timer.cancel()
            timer.join()
        connection.close()


def backup(host, port, output, *, timeout=15.0, total_timeout=600.0):
    address = ipaddress.IPv4Address(host)
    private_ranges = [ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
    if not address.is_loopback and not any(address in n for n in private_ranges):
        raise ValueError('Use the explicit private IPv4 address of the isolated loader')
    if not 1 <= port <= 65535:
        raise ValueError('Invalid port')
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError('Request timeout must be finite and at most 60 seconds')
    if not math.isfinite(total_timeout) or not 0 < total_timeout <= 1800:
        raise ValueError('Total timeout must be finite and at most 1800 seconds')
    output = Path(output)
    if output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError('Keep private flash backups outside the source repository')
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = output / 'manifest.json'
    manifest = {'complete': False, 'scope': 'post_loader_flash_snapshot',
                'pristine_factory_backup': False, 'device_authenticated': False,
                'flash_size_bytes': FLASH_SIZE, 'host': host, 'port': port}
    def save_manifest():
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    save_manifest()
    deadline = time.monotonic() + total_timeout
    def get_json(path):
        return json.loads(read_get(host, port, path, 16384, timeout, deadline))
    try:
        info, parts = get_json('/info'), get_json('/parts')
        validate_metadata(info, parts)
        manifest.update({'loader_info': info, 'partitions': parts})
        save_manifest()
        partial = output / 'flash.partial'
        hashes = []
        with partial.open('xb') as target:
            for pass_number in range(2):
                digest = hashlib.sha256()
                for offset in range(0, FLASH_SIZE, CHUNK_SIZE):
                    size = min(CHUNK_SIZE, FLASH_SIZE - offset)
                    data = read_get(host, port, f'/dump?offset={offset:#x}&size={size:#x}',
                                    size, timeout, deadline, exact=size)
                    digest.update(data)
                    if pass_number == 0:
                        target.write(data)
                hashes.append(digest.hexdigest())
                if get_json('/info') != info or get_json('/parts') != parts:
                    raise ValueError('Loader identity, slot or partition metadata changed during backup')
        if hashes[0] != hashes[1]:
            raise ValueError('Two complete flash reads differ; snapshot is not verified')
        if partial.stat().st_size != FLASH_SIZE or hashlib.sha256(partial.read_bytes()).hexdigest() != hashes[0]:
            raise ValueError('Saved flash file does not match the downloaded bytes')
        if time.monotonic() >= deadline:
            raise TimeoutError('Backup verification exceeded its deadline')
        manifest.update({'sha256': hashes[0], 'matching_full_reads': 2, 'file': 'flash.bin'})
        partial.rename(output / 'flash.bin')
        manifest['complete'] = True
        save_manifest()
        return manifest
    except BaseException:
        manifest['complete'] = False
        save_manifest()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='192.168.4.1')
    parser.add_argument('--port', type=int, default=80)
    parser.add_argument('--output', type=Path, required=True, help='New private directory outside the repository')
    parser.add_argument('--timeout', type=float, default=15)
    parser.add_argument('--total-timeout', type=float, default=600)
    args = parser.parse_args()
    try:
        result = backup(args.host, args.port, args.output, timeout=args.timeout, total_timeout=args.total_timeout)
    except (OSError, ValueError, http.client.HTTPException) as error:
        print(json.dumps({'complete': False, 'error': str(error)}))
        return 1
    print(json.dumps({'complete': True, 'bytes': result['flash_size_bytes'], 'sha256': result['sha256'],
                      'matching_full_reads': 2, 'pristine_factory_backup': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
