"""真实子进程/管道/socket：限时读写、停止和收口；不连接SSH或操作VM。"""
import json
import socket
import struct
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctflab_external_attach import FrameChannel, run_relay, policy_summary, _send_frame, authenticate_switch
from ctflab_external_l2 import RecordStream
from test_ctflab_external_attach import attachment


class ProcessPipeTests(unittest.TestCase):
    def channel(self, code, timeout=0.2):
        with patch('ctflab_remote.ssh_arguments', return_value=[sys.executable, '-u', '-c', code]):
            channel = FrameChannel({})
        channel.configure_io(timeout=timeout)
        self.addCleanup(channel.close)
        return channel

    def assert_closed(self, channel):
        started = time.monotonic()
        channel.close()
        self.assertLess(time.monotonic()-started, 3)
        self.assertIsNotNone(channel.process.poll())
        self.assertTrue(all(not worker.is_alive() for worker in channel._threads))
        self.assertEqual(channel.readable.fileno(), -1)

    def test_partial_header_times_out_and_closes_workers_and_process(self):
        channel = self.channel("import os,time; os.write(1,b'\\x03\\x00'); time.sleep(60)")
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            channel.receive_record(RecordStream(channel, channel))
        self.assertLess(time.monotonic()-started, 1)
        self.assert_closed(channel)

    def test_header_and_payload_share_one_deadline(self):
        channel = self.channel("import os,time; time.sleep(.2); os.write(1,b'\\x02\\0\\0\\0\\0\\0\\x04'); time.sleep(.4); os.write(1,b'test'); time.sleep(60)", timeout=0.5)
        started = time.monotonic()
        stream = RecordStream(channel, channel)
        with self.assertRaises(TimeoutError):
            channel.receive_record(stream)
        self.assertEqual(stream.expected_sequence, 1, '必须已读完头部，才能证明payload未重置截止时间')
        self.assertLess(time.monotonic()-started, 0.8)

    def test_stop_interrupts_partial_payload(self):
        channel = self.channel("import os,time; os.write(1,b'\\x02\\0\\0\\0\\0\\0\\x04x'); time.sleep(60)", timeout=5)
        stop = threading.Event()
        channel.configure_io(stop=stop.is_set, timeout=5)
        timer = threading.Timer(0.15, stop.set)
        self.addCleanup(timer.cancel)
        timer.start()
        started = time.monotonic()
        with self.assertRaises(InterruptedError):
            channel.receive_record(RecordStream(channel, channel))
        self.assertLess(time.monotonic()-started, 0.8)
        self.assert_closed(channel)

    def test_stalled_pipe_write_times_out_without_unbounded_queue(self):
        channel = self.channel('import time; time.sleep(60)', timeout=0.15)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            channel.write(b'x' * (16 * 1024 * 1024))
        self.assertLess(time.monotonic()-started, 0.8)
        self.assert_closed(channel)

    def test_stop_interrupts_stalled_pipe_write(self):
        channel = self.channel('import time; time.sleep(60)', timeout=5)
        stop = threading.Event()
        channel.configure_io(stop=stop.is_set, timeout=5)
        timer = threading.Timer(0.15, stop.set)
        self.addCleanup(timer.cancel)
        timer.start()
        started = time.monotonic()
        with self.assertRaises(InterruptedError):
            channel.write(b'x' * (16 * 1024 * 1024))
        self.assertLess(time.monotonic()-started, 0.8)
        self.assert_closed(channel)

    def test_full_duplex_large_echo_has_no_loss_or_reordering(self):
        channel = self.channel('import os\nwhile True:\n data=os.read(0,65536)\n if not data: break\n view=memoryview(data)\n while view:\n  count=os.write(1,view)\n  view=view[count:]', timeout=5)
        data = bytes(range(256)) * 4096
        failures = []
        def write():
            try:
                channel.write(data)
            except BaseException as error:
                failures.append(error)
        writer = threading.Thread(target=write)
        writer.start()
        try:
            self.assertEqual(channel.read(len(data)), data)
        finally:
            writer.join(6)
        self.assertFalse(writer.is_alive())
        self.assertEqual(failures, [])
        self.assert_closed(channel)

    def test_pipe_eof_is_distinct_from_timeout(self):
        channel = self.channel("import os; os.write(1,b'x')", timeout=2)
        self.assertEqual(channel.read(1), b'x')
        with self.assertRaises(EOFError):
            channel.read(1)

    def test_session_expiry_interrupts_stalled_read(self):
        channel = self.channel('import time; time.sleep(60)', timeout=5)
        deadline = time.monotonic()+0.15
        channel.configure_io(expired=lambda: time.monotonic() >= deadline, timeout=5)
        with self.assertRaisesRegex(TimeoutError, 'session-expired'):
            channel.read(7)
        self.assert_closed(channel)

    def hub(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        self.addCleanup(listener.close)
        peers = []
        def accept():
            peer, _ = listener.accept()
            peers.append(peer)
        worker = threading.Thread(target=accept)
        worker.start()
        self.addCleanup(lambda: [peer.close() for peer in peers])
        self.addCleanup(lambda: worker.join(1))
        return listener.getsockname()

    def test_production_relay_uses_only_sockets_and_stops_on_partial_record(self):
        registration = {'node_uuid': str(uuid.uuid4()), 'machine_uuid': str(uuid.uuid4()),
                        'assistant_sha256': 'a'*64}
        sid = str(uuid.uuid4())
        code = '''import os,sys,json,struct,time
header=sys.stdin.buffer.read(7)
length=struct.unpack('!BIH',header)[2]
hello=json.loads(sys.stdin.buffer.read(length))
reply=dict(handshake='ctflab-kali-attach/1',session_uuid=hello['session_uuid'],challenge_echo=hello['challenge'],assistant_sha256='a'*64,machine_uuid=MACHINE)
payload=json.dumps(reply).encode()
os.write(1,struct.pack('!BIH',2,0,len(payload))+payload+b'\\x03\\x00')
time.sleep(60)
'''.replace('MACHINE', repr(registration['machine_uuid']))
        channel = self.channel(code, timeout=5)
        stop = threading.Event()
        timers = []
        def ready(_):
            timer = threading.Timer(0.15, stop.set)
            timers.append(timer)
            timer.start()
        import select
        real_select = select.select
        def sockets_only(read, write, error, timeout=None):
            self.assertTrue(all(isinstance(peer, socket.socket) for peer in read+write+error))
            return real_select(read, write, error, timeout)
        started = time.monotonic()
        with patch('select.select', side_effect=sockets_only):
            result = run_relay({}, attachment(), policy_summary(attachment(), ['02:11:22:33:44:55']),
                               'a'*64, sid, self.hub(), backend='hub', channel=channel,
                               registration=registration, stop=stop.is_set, on_ready=ready)
        for timer in timers:
            timer.cancel()
        self.assertEqual(result['reason'], 'completed')
        self.assertLess(time.monotonic()-started, 2)
        self.assert_closed(channel)

    def test_switch_backpressure_is_interruptible(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close); self.addCleanup(b.close)
        a.setblocking(False)
        a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        while True:
            try:
                a.send(b'x'*65536)
            except BlockingIOError:
                break
        stop = threading.Event()
        timer = threading.Timer(.15, stop.set)
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        with self.assertRaises(InterruptedError):
            _send_frame(a, b'x'*60, stop=stop.is_set, timeout=5)
        self.assertLess(time.monotonic()-started, .8)


    def test_close_escalates_and_reaps_own_process(self):
        channel = self.channel("import signal,time,os; signal.signal(signal.SIGTERM,signal.SIG_IGN); os.write(1,b'r'); time.sleep(60)", timeout=2)
        self.assertEqual(channel.read(1), b'r')
        self.assert_closed(channel)

    def test_closed_stdin_reports_pipe_failure_and_reaps(self):
        channel = self.channel('import os,time; os.close(0); time.sleep(60)', timeout=2)
        with self.assertRaises(OSError):
            channel.write(b'x' * (16*1024*1024))
        self.assert_closed(channel)

    def test_auth_partial_response_obeys_stop(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close); self.addCleanup(b.close)
        b.sendall(b'C')
        stop = threading.Event()
        timer = threading.Timer(.15, stop.set)
        self.addCleanup(timer.cancel)
        timer.start()
        started = time.monotonic()
        with self.assertRaises(InterruptedError):
            authenticate_switch(a, str(uuid.uuid4()), 'a'*64, stop=stop.is_set)
        self.assertLess(time.monotonic()-started, .8)

    def test_auth_deadline_covers_drip_feed(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close); self.addCleanup(b.close)
        b.sendall(b'C')
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            authenticate_switch(a, str(uuid.uuid4()), 'a'*64, timeout=.15)
        self.assertLess(time.monotonic()-started, .5)


    def relay_from_hub(self, wire, *, quota=None, max_idle=1):
        registration = {'node_uuid': str(uuid.uuid4()), 'machine_uuid': str(uuid.uuid4()),
                        'assistant_sha256': 'a'*64}
        sid = str(uuid.uuid4())
        code = """import os,sys,json,struct,time
header=sys.stdin.buffer.read(7)
length=struct.unpack('!BIH',header)[2]
hello=json.loads(sys.stdin.buffer.read(length))
reply=dict(handshake='ctflab-kali-attach/1',session_uuid=hello['session_uuid'],challenge_echo=hello['challenge'],assistant_sha256='a'*64,machine_uuid=MACHINE)
payload=json.dumps(reply).encode()
os.write(1,struct.pack('!BIH',2,0,len(payload))+payload)
time.sleep(60)
""".replace('MACHINE', repr(registration['machine_uuid']))
        channel = self.channel(code, timeout=2)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        self.addCleanup(listener.close)
        ready = threading.Event()
        finished = threading.Event()
        stop = threading.Event()
        errors = []
        def serve():
            try:
                peer, _ = listener.accept()
                with peer:
                    ready.wait(2)
                    peer.sendall(wire)
                    finished.wait(3)
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        def on_ready(_):
            ready.set()
            timer = threading.Timer(.6, stop.set)
            self.addCleanup(timer.cancel)
            timer.start()
        try:
            result = run_relay({}, attachment(), policy_summary(attachment(), ['02:11:22:33:44:55']),
                               'a'*64, sid, listener.getsockname(), backend='hub', channel=channel,
                               registration=registration, stop=stop.is_set, on_ready=on_ready,
                               quota=quota, max_idle=max_idle)
        finally:
            finished.set()
            worker.join(3)
        self.assertEqual(errors, [])
        self.assertFalse(worker.is_alive())
        self.assert_closed(channel)
        return result

    def test_partial_hub_frame_cannot_extend_session_indefinitely(self):
        started = time.monotonic()
        result = self.relay_from_hub(struct.pack('!I',60)+b'x', max_idle=.2)
        self.assertEqual(result['reason'], 'partial-frame-timeout')
        self.assertLess(time.monotonic()-started, 1)

    def test_bad_hub_length_closes_instead_of_spinning(self):
        result = self.relay_from_hub(struct.pack('!I',13))
        self.assertEqual(result['reason'], 'bad-frame-length')
        self.assertEqual(result['frames_to_kali'], 0)

    def test_hub_to_kali_direction_consumes_shared_byte_quota(self):
        from ctflab_external_l2 import SessionQuota
        limits = attachment()['limits']
        quota = SessionQuota(limits)
        quota.bytes = quota.limits['max_bytes'] - 20
        frame = (bytes.fromhex('02aabbccddee0211223344550806') +
                 bytes.fromhex('0001080006040002') + bytes.fromhex('021122334455') +
                 socket.inet_aton('192.168.50.20') + bytes.fromhex('02aabbccddee') +
                 socket.inet_aton('192.168.50.9'))
        result = self.relay_from_hub(struct.pack('!I',len(frame))+frame, quota=quota)
        self.assertEqual(result['frames_to_kali'], 0)
        self.assertEqual(result['dropped'], 1)
        self.assertEqual(quota.frames_dropped, 1)


if __name__ == '__main__':
    unittest.main()
