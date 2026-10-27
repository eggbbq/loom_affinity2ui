"""Read-only Affinity source adapter using the packaged loopback transport."""
from importlib.resources import files
import json
from pathlib import Path
import queue
import subprocess
import sys
import time

from .transport import AffinitySSE


class NativeAffinity:
    def __init__(self, *, client_factory=None, open_document=True, application='Affinity', exchange_dir=None):
        self.client_factory = client_factory or AffinitySSE
        self.open_document = open_document
        self.application = application
        self.exchange_dir = Path(exchange_dir).resolve() if exchange_dir else Path.home()/'Desktop'

    def __enter__(self):
        self.client = self.client_factory()
        try:
            self.client.initialize()
            for topic in ('preamble', 'document.js', 'nodes.js', 'story.js', 'paragraphatts.js', 'selections.js'):
                self.call('read_sdk_documentation_topic', {'filename': topic})
        except BaseException:
            self.client.close()
            raise
        return self

    def __exit__(self, *unused):
        self.client.close()

    def call(self, name, arguments):
        try:
            response = self.client.request('tools/call', {'name': name, 'arguments': arguments})
        except queue.Empty as error:
            raise ValueError('Affinity MCP 请求超时') from error
        result = response.get('result', {})
        if response.get('error') or result.get('isError'):
            raise ValueError(f'Affinity MCP failed: {response}')
        return '\n'.join(item.get('text', '') for item in result.get('content', []))

    def script(self, request):
        script = 'const REQUEST = '+json.dumps(request, ensure_ascii=False)+';\n'
        script += files('affinity2ui').joinpath('native.js').read_text(encoding='utf-8')
        output = self.call('execute_script', {'script': script})
        marker = '__AFFINITY2UI__'
        records = [line.split(marker, 1)[1] for line in output.splitlines() if marker in line]
        if len(records) != 1:
            raise ValueError(f'Affinity returned no valid result: {output[:1200]}')
        result = json.loads(records[0])
        if not result['ok']:
            raise ValueError(result['error'])
        return result['result']

    def open(self, path):
        path = Path(path).resolve()
        if self.open_document:
            if sys.platform != 'darwin':
                raise ValueError('自动打开文件仅支持 macOS Affinity；其它平台可自行打开后使用 open_document=False')
            subprocess.run(['open', '-a', self.application, str(path)], check=True)
        deadline = time.monotonic()+20
        while True:
            try:
                return self.script({'path': str(path), 'action': 'inspect'})
            except ValueError as error:
                if 'not open' not in str(error) or time.monotonic() >= deadline:
                    raise
                time.sleep(.25)
