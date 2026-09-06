#!/usr/bin/env python3
"""CTFLab 用户态二层交换机的回归测试。"""

from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from ctflab_network import (  # noqa: E402
    DHCPServer,
    FrameRateLimiter,
    LearningSwitch,
    PcapWriter,
    mac_bytes,
)


def ethernet_frame(destination: str, source: str, payload: bytes = b"test") -> bytes:
    return mac_bytes(destination) + mac_bytes(source) + b"\x08\x00" + payload


class LearningSwitchTests(unittest.TestCase):
    def test_broadcast_and_unknown_unicast_are_flooded(self) -> None:
        switch = LearningSwitch()
        first, second, third = object(), object(), object()
        peers = [first, second, third]

        broadcast = ethernet_frame("ff:ff:ff:ff:ff:ff", "52:54:00:00:00:01")
        self.assertEqual(switch.forwarding_targets(first, broadcast, peers), [second, third])

        unknown = ethernet_frame("52:54:00:00:00:99", "52:54:00:00:00:01")
        self.assertEqual(switch.forwarding_targets(first, unknown, peers), [second, third])

    def test_known_unicast_uses_only_learned_port(self) -> None:
        switch = LearningSwitch()
        first, second, third = object(), object(), object()
        peers = [first, second, third]
        first_mac = "52:54:00:00:00:01"
        second_mac = "52:54:00:00:00:02"

        switch.forwarding_targets(first, ethernet_frame("ff:ff:ff:ff:ff:ff", first_mac), peers)
        targets = switch.forwarding_targets(second, ethernet_frame(first_mac, second_mac), peers)
        self.assertEqual(targets, [first])
        self.assertEqual(switch.learned_macs(), [first_mac, second_mac])

        switch.forget(first)
        self.assertEqual(switch.forwarding_targets(second, ethernet_frame(first_mac, second_mac), peers), [first, third])


class RateLimiterTests(unittest.TestCase):
    def test_limit_resets_after_one_second(self) -> None:
        limiter = FrameRateLimiter(2)
        peer = object()
        self.assertTrue(limiter.allow(peer, now=10.0))
        self.assertTrue(limiter.allow(peer, now=10.2))
        self.assertFalse(limiter.allow(peer, now=10.9))
        self.assertTrue(limiter.allow(peer, now=11.0))


class PcapTests(unittest.TestCase):
    def test_writer_creates_ethernet_pcap(self) -> None:
        frame = ethernet_frame("ff:ff:ff:ff:ff:ff", "52:54:00:00:00:01")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "traffic.pcap"
            writer = PcapWriter(path)
            writer.write(frame, timestamp=1_700_000_000.25)
            writer.close()
            data = path.read_bytes()

        magic, major, minor, _zone, _accuracy, snaplen, linktype = struct.unpack("<IHHIIII", data[:24])
        seconds, microseconds, captured_length, original_length = struct.unpack("<IIII", data[24:40])
        self.assertEqual((magic, major, minor), (0xA1B2C3D4, 2, 4))
        self.assertEqual((snaplen, linktype), (65535, 1))
        self.assertEqual((seconds, microseconds), (1_700_000_000, 250_000))
        self.assertEqual((captured_length, original_length), (len(frame), len(frame)))
        self.assertEqual(data[40:], frame)

    def test_server_state_exposes_switch_counters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "network.json"
            server = DHCPServer(23499, {}, state_path, max_frames_per_second=1234)
            server.frames_received = 7
            server.frames_forwarded = 4
            server.frames_dropped_rate_limit = 2
            server.write_state()
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(state["rate_limit_frames_per_second"], 1234)
        self.assertEqual(state["counters"]["received"], 7)
        self.assertEqual(state["counters"]["forwarded"], 4)
        self.assertEqual(state["counters"]["dropped_rate_limit"], 2)


if __name__ == "__main__":
    unittest.main()
