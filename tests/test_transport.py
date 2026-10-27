"""Exercise the bundled loopback transport without contacting Affinity."""
import io
import json
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from affinity2ui.transport import AffinitySSE


class ImmediateThread:
    def __init__(self, target, **unused):
        self.target = target

    def start(self):
        self.target()


class TransportTests(unittest.TestCase):
    def connect(self, endpoint):
        response = io.BytesIO(('event: endpoint\ndata: '+endpoint+'\n\n').encode())
        response.status = 200
        connection = SimpleNamespace(sock=SimpleNamespace(settimeout=lambda timeout: None),
            request=lambda *args, **kwargs: None, getresponse=lambda: response, close=lambda: None)
        return connection

    def test_connection_is_loopback_only_and_accepts_session_endpoint(self):
        connection = self.connect('/message?sessionId=fixture')
        with patch('affinity2ui.transport.http.client.HTTPConnection', return_value=connection) as http, \
                patch('affinity2ui.transport.threading.Thread', ImmediateThread):
            client = AffinitySSE()
        http.assert_called_once_with('::1', 6767, timeout=5)
        self.assertEqual(client.path, '/message?sessionId=fixture')
        client.close()

    def test_remote_and_unexpected_endpoints_are_rejected(self):
        for endpoint in ('https://example.com/message', '//example.com/message', '/other'):
            with self.subTest(endpoint=endpoint), \
                    patch('affinity2ui.transport.http.client.HTTPConnection', return_value=self.connect(endpoint)), \
                    patch('affinity2ui.transport.threading.Thread', ImmediateThread):
                with self.assertRaisesRegex(RuntimeError, 'unexpected'):
                    AffinitySSE()

    def test_request_matches_id_and_ignores_unsolicited_notifications(self):
        client = AffinitySSE.__new__(AffinitySSE)
        client.events = queue.Queue()
        client.seq = 0
        packets = []
        def post(packet):
            packets.append(packet)
            client.events.put({'jsonrpc':'2.0', 'method':'notifications/progress'})
            client.events.put({'jsonrpc':'2.0', 'id':packet['id'], 'result':{'fixture':True}})
        client.post = post
        self.assertEqual(client.request('tools/list', {'fixture':1})['result'], {'fixture':True})
        self.assertEqual(packets[0], {'jsonrpc':'2.0', 'id':1, 'method':'tools/list', 'params':{'fixture':1}})

    def test_transport_read_error_propagates_instead_of_becoming_a_result(self):
        client = AffinitySSE.__new__(AffinitySSE)
        client.events = queue.Queue();client.seq = 0;client.post = lambda packet: None
        client.events.put(ConnectionError('disconnected'))
        with self.assertRaisesRegex(ConnectionError, 'disconnected'):
            client.request('tools/list')


if __name__ == '__main__':unittest.main()
