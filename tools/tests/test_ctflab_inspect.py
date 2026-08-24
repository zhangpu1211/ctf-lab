#!/usr/bin/env python3
"""CTFLab 镜像只读探测的回归测试。"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
import uuid


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from ctflab_inspect import (  # noqa: E402
    infer_architecture,
    infer_disk,
    parse_ovf,
    profile_from_report,
    read_descriptor_hints,
    read_partition_hints,
)


class InspectionTests(unittest.TestCase):
    def test_vmdk_descriptor_detects_ide(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disk.vmdk"
            path.write_text('# Disk DescriptorFile\ncreateType="streamOptimized"\nddb.adapterType="ide"\n', encoding="ascii")
            hints = read_descriptor_hints(path)
        self.assertEqual(hints["adapter_type"], "ide")
        self.assertEqual(hints["create_type"], "streamOptimized")

    def test_mbr_partition_implies_legacy_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disk.raw"
            data = bytearray(2 * 1024 * 1024)
            data[0] = 0xFA
            data[446 + 4] = 0x83
            data[510:512] = b"\x55\xaa"
            path.write_bytes(data)
            hints = read_partition_hints(path)
        self.assertEqual(hints["scheme"], "mbr")
        self.assertTrue(hints["mbr_boot_code"])
        self.assertEqual(hints["partition_types"], ["0x83"])

    def test_gpt_efi_partition_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disk.raw"
            data = bytearray(2 * 1024 * 1024)
            data[446 + 4] = 0xEE
            data[510:512] = b"\x55\xaa"
            data[512:520] = b"EFI PART"
            data[1024:1040] = uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b").bytes_le
            path.write_bytes(data)
            hints = read_partition_hints(path)
        self.assertEqual(hints["scheme"], "gpt")
        self.assertTrue(hints["efi_system_partition"])

    def test_ovf_uses_controller_attached_to_disk(self) -> None:
        xml = """<?xml version="1.0"?>
        <Envelope xmlns="urn:ovf" xmlns:rasd="urn:rasd">
          <Item><rasd:InstanceID>3</rasd:InstanceID><rasd:ResourceSubType>AHCI</rasd:ResourceSubType><rasd:ResourceType>20</rasd:ResourceType></Item>
          <Item><rasd:InstanceID>4</rasd:InstanceID><rasd:ResourceSubType>lsilogic</rasd:ResourceSubType><rasd:ResourceType>6</rasd:ResourceType></Item>
          <Item><rasd:Parent>4</rasd:Parent><rasd:ResourceType>17</rasd:ResourceType></Item>
        </Envelope>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "machine.ovf"
            path.write_text(xml, encoding="utf-8")
            ovf = parse_ovf(path)
        bus, controller, confidence, _reason = infer_disk("x86_64", {}, ovf)
        self.assertEqual((bus, controller, confidence), ("scsi", "lsi53c895a", "medium"))

    def test_arm_override_forces_safe_virt_defaults(self) -> None:
        report = {
            "candidate": {
                "architecture": "x86_64",
                "firmware": "bios",
                "machine": "pc",
                "memory_mb": 2048,
                "cpus": 2,
                "disk_bus": "ide",
                "disk_controller": None,
                "network_adapter": "e1000",
            },
            "source_sha256": "0" * 64,
            "confidence": {},
            "warnings": [],
        }
        profile = profile_from_report(
            report,
            profile_id="arm-test",
            name="ARM Test",
            lab_ip="192.168.242.30",
            mac="52:54:00:24:00:30",
            overrides={"architecture": "aarch64"},
        )
        self.assertEqual(profile["guest"]["firmware"], "uefi")
        self.assertEqual(profile["disk"]["bus"], "virtio")
        self.assertEqual(profile["network"]["adapter"], "virtio-net-pci")

    def test_architecture_fallback_is_explicitly_low_confidence(self) -> None:
        architecture, confidence, _reason = infer_architecture("mystery-disk")
        self.assertEqual(architecture, "x86_64")
        self.assertEqual(confidence, "low")


if __name__ == "__main__":
    unittest.main()
