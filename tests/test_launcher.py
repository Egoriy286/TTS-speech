import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile

import launcher


class LauncherTests(unittest.TestCase):
    def test_incomplete_or_missing_model_files_are_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'models' / 'test-model'
            folder.mkdir(parents=True)
            (folder / 'weights.bin').write_bytes(b'123')
            project = {'qwen': {'model_dir': 'test-model', 'required_files': ['config.json', 'vocab.json']}}
            with patch.multiple(launcher, ROOT=root, PROJECTS=project, SIZES={'test-model': {'weights.bin': 4}}):
                self.assertFalse(launcher.weights_ready('qwen'))
                (folder / 'weights.bin').write_bytes(b'1234')
                (folder / 'config.json').write_text('{}')
                self.assertFalse(launcher.weights_ready('qwen'))
                (folder / 'vocab.json').write_text('{}')
                self.assertTrue(launcher.weights_ready('qwen'))

    def test_source_archive_preserves_files_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'source.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('repo-revision/src/example.py', 'print(42)')
            launcher.extract_source(archive, root / 'source')
            self.assertEqual((root / 'source/src/example.py').read_text(), 'print(42)')
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('repo-revision/../escaped.txt', 'bad')
            with self.assertRaises(ValueError):
                launcher.extract_source(archive, root / 'source')
            self.assertFalse((root / 'escaped.txt').exists())

    def test_local_menu_and_cross_origin_protection(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, 'ROOT', Path(directory)):
            server = launcher.http.server.ThreadingHTTPServer(('127.0.0.1', 0), launcher.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f'http://127.0.0.1:{server.server_port}'
            try:
                with urllib.request.urlopen(url + '/state') as response:
                    self.assertEqual(json.load(response)['product'], 'TTS-speech')
                request = urllib.request.Request(url + '/start', data=b'{"engine":"recorder"}', headers={'Origin': 'https://unrelated.example', 'Content-Type': 'application/json'})
                with urllib.request.urlopen(url) as response:
                    self.assertIn('Записать мой голос', response.read().decode('utf-8'))
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request)
                self.assertEqual(error.exception.code, 403)
                request = urllib.request.Request(url + '/start', data=b'{"engine":"unknown"}', headers={'Content-Type': 'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request)
                self.assertEqual(error.exception.code, 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
