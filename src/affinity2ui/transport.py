"""Dependency-free MCP SSE transport restricted to Affinity on loopback.

The endpoint is not configurable to an external host.
"""
import http.client
import json
import queue
import threading
import urllib.parse

HOST, PORT = '::1', 6767


class AffinitySSE:
    def __init__(self):
        self.events = queue.Queue()
        self.endpoints = queue.Queue()
        self.seq = 0
        self.conn = http.client.HTTPConnection(HOST, PORT, timeout=5)
        self.conn.request('GET', '/sse', headers={'Accept': 'text/event-stream'})
        self.response = self.conn.getresponse()
        if self.response.status != 200:
            raise RuntimeError(f'SSE HTTP {self.response.status}')
        self.conn.sock.settimeout(None)
        threading.Thread(target=self._read, daemon=True).start()
        self.path = self.endpoints.get(timeout=5)
        url = urllib.parse.urlsplit(self.path)
        if url.scheme or url.netloc or url.path != '/message':
            raise RuntimeError('Affinity returned an unexpected message endpoint')

    def _read(self):
        event, data = 'message', []
        try:
            while line := self.response.readline():
                line = line.decode('utf-8').rstrip('\r\n')
                if not line:
                    if data:
                        body = '\n'.join(data)
                        if event == 'endpoint':
                            self.endpoints.put(body)
                        else:
                            message = json.loads(body)
                            if isinstance(message, dict):
                                self.events.put(message)
                    event, data = 'message', []
                elif line.startswith('event:'):
                    event = line[6:].strip()
                elif line.startswith('data:'):
                    data.append(line[5:].lstrip())
        except Exception as exc:
            self.events.put(exc)
        else:
            self.events.put(ConnectionError('Affinity SSE closed'))

    def post(self, packet):
        conn = http.client.HTTPConnection(HOST, PORT, timeout=30)
        try:
            conn.request('POST', self.path, json.dumps(packet),
                         {'Content-Type': 'application/json'})
            response = conn.getresponse()
            response.read()
            if response.status not in (200, 202):
                raise RuntimeError(f'MCP POST HTTP {response.status}')
        finally:
            conn.close()

    def request(self, method, params=None, notify=False):
        packet = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            packet['params'] = params
        if not notify:
            self.seq += 1
            packet['id'] = self.seq
        self.post(packet)
        if notify:
            return None
        while True:
            message = self.events.get(timeout=120)
            if isinstance(message, Exception):
                raise message
            if message.get('id') == self.seq:
                return message

    def initialize(self):
        result = self.request('initialize', {
            'protocolVersion': '2025-11-25', 'capabilities': {},
            'clientInfo': {'name': 'loom-affinity2ui', 'version': '0.1.1'}})
        if 'error' in result:
            raise RuntimeError(result['error'])
        self.request('notifications/initialized', notify=True)
        return result

    def close(self):
        self.conn.close()

