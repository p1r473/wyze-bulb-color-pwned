"""Loopback loader fixtures only. No bulb, installer or serial access.

Lightjack additions, 2026-10-21. SPDX-License-Identifier: MIT.
"""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit
import uuid

from backup_loader import backup, FLASH_SIZE, validate_metadata

INFO = {'running': 'ota_1', 'target': 'ota_0', 'mac': '02:00:00:00:00:01',
        'version': 'fixture', 'date': 'test', 'bonus': 'test'}
PARTS = [dict(label=n, offset=o, size=s, type=t, subtype=u) for n, o, s, t, u in [
    ('nvs', 0x9000, 0x4000, 1, 2), ('otadata', 0xd000, 0x2000, 1, 0),
    ('phy_init', 0xf000, 0x1000, 1, 1), ('ota_0', 0x10000, 0x1e0000, 0, 16),
    ('ota_1', 0x1f0000, 0x1e0000, 0, 17), ('mac', 0x3d0000, 0x4000, 1, 2),
    ('iot', 0x3d4000, 0x4000, 1, 2), ('user', 0x3d8000, 0x8000, 1, 2),
    ('factory_nvs', 0x3e0000, 0x6000, 1, 2), ('reserved', 0x3e6000, 0x12000, 1, 254)]]
FLASH = bytes(range(256)) * (FLASH_SIZE // 256)


@contextmanager
def loader(mode='normal'):
    calls = []
    stop = threading.Event()
    dump_count = 0
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args):
            pass
        def do_GET(self):
            nonlocal dump_count
            calls.append(('GET', self.path))
            parsed = urlsplit(self.path)
            if mode == 'redirect':
                self.send_response(302)
                self.send_header('Location', 'http://127.0.0.1:1/unsafe')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if mode == 'trickle':
                try:
                    self.connection.sendall(b'HTTP/1.1 200 OK\r\nX-Fixture: ')
                    for _ in range(50):
                        if stop.wait(0.03):
                            break
                        self.connection.sendall(b'x')
                except OSError:
                    pass
                return
            if parsed.path == '/info':
                data = dict(INFO)
                if mode == 'changed-identity' and dump_count:
                    data['mac'] = '02:00:00:00:00:02'
                body = json.dumps(data).encode()
            elif parsed.path == '/parts':
                body = json.dumps(PARTS).encode()
            elif parsed.path == '/dump':
                dump_count += 1
                query = parse_qs(parsed.query)
                offset, size = int(query['offset'][0], 0), int(query['size'][0], 0)
                body = FLASH[offset:offset + size]
                if mode == 'truncated':
                    body = body[:-1]
                elif mode == 'extra':
                    body += b'x'
                elif mode == 'changed-data' and dump_count > FLASH_SIZE // 0x10000:
                    body = b'x' + body[1:]
            else:
                self.send_error(404)
                return
            try:
                self.send_response(200)
                # Exercise the loader's real transfer framing, not Content-Length.
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                for offset in range(0, len(body), 4096):
                    chunk = body[offset:offset + 4096]
                    self.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                self.wfile.write(b'0\r\n\r\n')
            except OSError:
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02})
    worker.start()
    try:
        yield server.server_port, calls
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        if worker.is_alive():
            raise AssertionError('Fixture server did not stop')


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.output = Path(tempfile.gettempdir()) / 'lightjack-loader-tests' / uuid.uuid4().hex

    def test_two_reads_file_hash_and_get_only(self):
        with loader() as (port, calls):
            result = backup('127.0.0.1', port, self.output, timeout=2)
        self.assertTrue(result['complete'])
        self.assertFalse(result['pristine_factory_backup'])
        self.assertFalse(result['device_authenticated'])
        self.assertEqual((self.output / 'flash.bin').read_bytes(), FLASH)
        self.assertEqual(result['sha256'], hashlib.sha256(FLASH).hexdigest())
        self.assertEqual(result['matching_full_reads'], 2)
        self.assertEqual(len([p for _, p in calls if p.startswith('/dump?')]), 128)
        self.assertTrue(all(method == 'GET' for method, _ in calls))
        self.assertFalse((self.output / 'flash.partial').exists())
        self.assertTrue(json.loads((self.output / 'manifest.json').read_text())['complete'])

    def test_incomplete_reads_and_changed_device_fail(self):
        for mode in ('truncated', 'extra', 'changed-data', 'changed-identity', 'redirect'):
            out = self.output / mode
            with self.subTest(mode=mode), loader(mode) as (port, calls):
                with self.assertRaises((OSError, ValueError)):
                    backup('127.0.0.1', port, out, timeout=2)
                self.assertFalse((out / 'flash.bin').exists())
                self.assertFalse(json.loads((out / 'manifest.json').read_text())['complete'])
                self.assertTrue(all(method == 'GET' for method, _ in calls))

    def test_trickling_headers_have_absolute_timeout(self):
        for settings in ({'timeout': 0.15}, {'timeout': 2, 'total_timeout': 0.15}):
            started = time.monotonic()
            with self.subTest(settings=settings), loader('trickle') as (port, _):
                with self.assertRaises((OSError, ValueError)):
                    backup('127.0.0.1', port, self.output / str(len(settings)), **settings)
            self.assertLess(time.monotonic() - started, 1)

    def test_existing_output_is_not_overwritten(self):
        self.output.mkdir(parents=True)
        sentinel = self.output / 'manifest.json'
        sentinel.write_text('original')
        with self.assertRaises(FileExistsError):
            backup('127.0.0.1', 1, self.output)
        self.assertEqual(sentinel.read_text(), 'original')

    def test_invalid_metadata_rejected(self):
        for info, parts in ((dict(INFO, target='ota_1'), PARTS),
                            (dict(INFO, mac='bad'), PARTS), (INFO, PARTS[:-1]),
                            (INFO, PARTS + [PARTS[0]]),
                            (INFO, [dict(p, offset=0) for p in PARTS])):
            with self.subTest(info=info, count=len(parts)), self.assertRaises(ValueError):
                validate_metadata(info, parts)

    def test_unsafe_inputs_rejected_before_output_creation(self):
        for host in ('example.com', '0.0.0.0', '8.8.8.8', '224.0.0.1'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                backup(host, 80, self.output)
        for timeout in (0, float('nan'), float('inf'), 61):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                backup('127.0.0.1', 80, self.output, timeout=timeout)
        self.assertFalse(self.output.exists())

    def test_output_inside_repo_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            backup('127.0.0.1', 80, Path(__file__).parent / 'private-backup')


if __name__ == '__main__':
    unittest.main(verbosity=2)
