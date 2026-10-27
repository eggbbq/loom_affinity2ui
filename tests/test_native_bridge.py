"""Verify packaged SDK requests and failure propagation with an injected MCP client."""
import json
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import patch

from affinity2ui.bridge import NativeAffinity


class ClientFixture:
    def __init__(self):
        self.requests=[];self.closed=False;self.initialized=False
        self.response={'ok':True,'result':{'fixture':True}}

    def initialize(self):self.initialized=True
    def close(self):self.closed=True

    def request(self, method, params):
        self.requests.append((method,params))
        text='__AFFINITY2UI__'+json.dumps(self.response)
        return {'result':{'content':[{'type':'text','text':text}]}}


class NativeBridgeTests(unittest.TestCase):
    def test_already_open_document_uses_bundled_sdk_without_external_scripts(self):
        client=ClientFixture()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'Native.af';path.write_bytes(b'fixture')
            with patch('affinity2ui.bridge.subprocess.run',side_effect=AssertionError('No process expected')):
                with NativeAffinity(client_factory=lambda:client,open_document=False) as adapter:
                    self.assertEqual(adapter.open(path), {'fixture':True})
            self.assertTrue(client.initialized)
            self.assertTrue(client.closed)
            topics=[args['arguments']['filename'] for method,args in client.requests
                    if args['name']=='read_sdk_documentation_topic']
            self.assertIn('document.js',topics)
            scripts=[args['arguments']['script'] for method,args in client.requests if args['name']=='execute_script']
            self.assertEqual(len(scripts),1)
            request=json.loads(scripts[0].splitlines()[0].removeprefix('const REQUEST = ').removesuffix(';'))
            self.assertEqual(request['path'],str(path.resolve()))
            self.assertEqual(request['action'],'inspect')
            self.assertIn('originalSelection',scripts[0])

    def test_native_error_and_timeout_fail_clearly_and_close_client(self):
        for failure in ('native','timeout'):
            with self.subTest(failure=failure):
                client=ClientFixture()
                with NativeAffinity(client_factory=lambda:client,open_document=False) as adapter:
                    if failure=='native':
                        client.response={'ok':False,'error':'Document has unsaved changes'}
                    else:
                        client.request=lambda *args:(_ for _ in ()).throw(queue.Empty())
                    with self.assertRaisesRegex(ValueError, 'unsaved|超时'):
                        adapter.script({'action':'inspect'})
                self.assertTrue(client.closed)


if __name__ == '__main__':unittest.main()
