import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_qmp_protocol import Session, ProtocolError

class ProtocolTests(unittest.TestCase):
    def ready(self):
        s=Session();s.feed(b'{"QMP":{"version":{},"capabilities":[]}}\r\n')
        req=json.loads(s.request('qmp_capabilities'))
        s.feed(json.dumps({'return':{},'id':req['id']}).encode()+b'\n')
        return s
    def test_fragment_and_handshake(self):
        s=Session();self.assertEqual(s.feed(b'{"QMP":'),[])
        s.feed(b'{"version":{},"capabilities":[]}}\n')
        self.assertEqual(s.state,'negotiate')
        with self.assertRaises(ProtocolError):s.request('system_powerdown')
    def test_events_do_not_complete_request(self):
        s=self.ready();req=json.loads(s.request('system_powerdown'))
        s.feed(b'{"event":"SHUTDOWN"}\n')
        self.assertIsNotNone(s.pending)
        s.feed(json.dumps({'return':{},'id':req['id']}).encode()+b'\n')
        self.assertIsNone(s.pending)
    def test_old_response_not_accepted(self):
        s=self.ready();s.request('query-status')
        self.assertEqual(s.feed(b'{"return":{},"id":"old"}\n')[0]['kind'],'unmatched')
        self.assertIsNotNone(s.pending)
    def test_forbidden_commands(self):
        s=self.ready()
        for command in ('quit','human-monitor-command','block-commit'):
            with self.assertRaises(ProtocolError):s.request(command)
    def test_invalid_closes(self):
        for raw in (b'{"event":"a","event":"b"}\n',b'[]\n',b'{"return":NaN}\n',b'\xff\n'):
            s=self.ready()
            with self.assertRaises(ProtocolError):s.feed(raw)
            self.assertEqual(s.state,'closed')
    def test_bounded_and_no_replay(self):
        s=self.ready();s.request('system_powerdown')
        with self.assertRaises(ProtocolError):s.request('system_powerdown')
        with self.assertRaises(ProtocolError):s.feed(b'x'*65537)
        self.assertIsNone(s.pending)
        with self.assertRaises(ProtocolError):s.request('query-status')
