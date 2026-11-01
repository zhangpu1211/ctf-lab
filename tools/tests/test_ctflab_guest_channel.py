"""客户端/来宾代理的真实消息与账本集成；传输使用内存，不操作VM。"""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_guest_agent import GuestAgent,response,parse_frame
from ctflab_guest_channel import GuestClient
from test_ctflab_guest_policy import envelope
from test_ctflab_guest_agent import FakeBackend


class MemorySocket:
    def __init__(self,agent):self.agent=agent;self.stream=io.BytesIO();self.requests=[];self.corrupt=None
    def makefile(self,*a,**k):return self.stream
    def sendall(self,raw):
        request=parse_frame(raw);self.requests.append(request)
        value=response(self.agent,request,self.agent.dispatch(request))
        if self.corrupt:self.corrupt(value)
        self.stream.seek(0);self.stream.truncate();self.stream.write((canonical(value)+'\n').encode());self.stream.seek(0)
    def close(self):pass


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.definition=envelope();self.backend=FakeBackend()
        self.agent=GuestAgent(Path(self.tmp.name).resolve()/'guest',self.definition,self.backend)
        self.socket=MemorySocket(self.agent)
    def client(self):
        d=self.definition
        definition={k:d[k] for k in ('devices','flows','containers','container_cidr')}
        with patch('ctflab_guest_channel.tcp',return_value=object()),patch('ctflab_guest_channel.wrap_client',return_value=self.socket):
            return GuestClient(46211,Path('/unused'),{},d['plan'],d['node'],definition)
    def test_handshake_and_duplicate_command_preserve_one_effect_sequence(self):
        with self.client() as client:
            op=str(uuid.uuid4());a=client.command('network-apply',op);calls=len(self.backend.calls)
            self.assertEqual(client.command('network-apply',op),a)
            self.assertEqual(len(self.backend.calls),calls)
            self.assertEqual(client.command('operation-status',op)['state'],'completed')
        self.assertEqual(self.socket.requests[0]['action'],'configure')
    def test_wrong_generation_or_reply_operation_refused(self):
        with self.client() as client:
            self.socket.corrupt=lambda value:value.update(generation=2)
            with self.assertRaises(ContractError):client.command('status',str(uuid.uuid4()))
    def test_unknown_command_never_reaches_guest(self):
        with self.client() as client:
            before=len(self.socket.requests)
            with self.assertRaises(ContractError):client.command('shell',str(uuid.uuid4()))
            self.assertEqual(len(self.socket.requests),before)
    def test_lost_response_never_resends(self):
        with self.client() as client:
            def lost(raw):self.socket.requests.append(parse_frame(raw));self.socket.stream.seek(0);self.socket.stream.truncate()
            self.socket.sendall=lost
            before=len(self.socket.requests)
            with self.assertRaises(ContractError):client.command('network-apply',str(uuid.uuid4()))
            self.assertEqual(len(self.socket.requests),before+1)

    def delayed(self,count=1,wrong_generation=False):
        original=self.socket.sendall
        def send(raw):
            original(raw)
            current=self.socket.stream.read();value=json.loads(current)
            stale=dict(value,operation_id=str(uuid.uuid4()),result={'state':'historical-not-used'})
            if wrong_generation:stale['generation']=2
            self.socket.stream.seek(0);self.socket.stream.truncate()
            self.socket.stream.write((canonical(stale)+'\n').encode()*count+current);self.socket.stream.seek(0)
        self.socket.sendall=send

    def test_reconnect_handshake_discards_bound_late_replies_without_resending(self):
        self.delayed(count=8)
        with self.client():pass
        self.assertEqual(len(self.socket.requests),1);self.assertEqual(self.socket.requests[0]['action'],'configure')
        self.assertEqual(self.backend.calls,[])

    def test_handshake_cannot_drain_foreign_binding_or_unbounded_old_replies(self):
        self.delayed(wrong_generation=True)
        with self.assertRaises(ContractError):self.client()
        self.socket=MemorySocket(self.agent);self.delayed(count=9)
        with self.assertRaises(ContractError):self.client()
        self.assertEqual(len(self.socket.requests),1)

    def test_mutating_reply_operation_mismatch_is_never_accepted_or_replayed(self):
        with self.client() as client:
            self.socket.corrupt=lambda value:value.update(operation_id=str(uuid.uuid4()))
            before=len(self.socket.requests)
            with self.assertRaises(ContractError):client.command('network-apply',str(uuid.uuid4()))
            self.assertEqual(len(self.socket.requests),before+1)


if __name__=='__main__':unittest.main()
