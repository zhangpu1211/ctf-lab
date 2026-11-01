"""只调用纯函数的场景契约与参数负测，不启动网络/虚拟机。"""
import copy
import json
from pathlib import Path
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_scenario as scenario

CAPS = scenario.REQUIRED_CAPABILITIES
INSTANCE = "12345678-1234-4234-8234-123456789abc"


def candidate():
    """合成清单：哈希、硬件均非 Wintermute 实机证据。"""
    result = {"schema": 1, "scenario_id": "wintermute", "required_capabilities": sorted(CAPS), "assets": {}, "networks": {}, "nodes": {}, "policy": {"internet": False, "host_forwards": [], "guest_management_nic": False}, "lifecycle": {"start_order": ["neuromancer", "straylight", "kali"], "stop_order": ["kali", "straylight", "neuromancer"], "startup_timeout_seconds": 180, "shutdown_timeout_seconds": 120, "failure": "preserve", "reset": "stopped-atomic-preserve"}, "checks": {key: [] for key in ("boot", "address", "service", "isolation")}}
    for net, octet, leases in [("outer", 243, {"kali/outer0": 10, "straylight/outer0": 20}), ("inner", 244, {"straylight/inner0": 20, "neuromancer/inner0": 30})]:
        prefix = f"192.168.{octet}"
        result["networks"][net] = {"cidr": prefix + ".0/24", "server": prefix + ".1", "pool": [prefix + ".100", prefix + ".150"], "leases": {key: f"{prefix}.{ip}" for key, ip in leases.items()}, "uplink": "none", "gateway": None, "dns": []}
    for index, (node, nics) in enumerate(scenario.TOPOLOGY.items()):
        result["assets"][node] = {"sha256": str(index) * 64, "source": "synthetic-fixture", "license": "test-only", "profile": node, "hardware_verified": False}
        arm = node == "kali"
        result["nodes"][node] = {"asset": node, "architecture": "aarch64" if arm else "x86_64", "firmware": "uefi" if arm else "bios", "disk_bus": "virtio" if arm else "ide", "cpus": 2, "memory_mb": 1024, "interfaces": [{"id": nic, "network": net, "model": "virtio-net-pci" if arm else "e1000", "pci_slot": 5 + i, "mac": "derived"} for i, (nic, net) in enumerate(nics)], "depends_on": [], "shutdown": "acpi"}
    return result


class ScenarioTests(unittest.TestCase):
    def test_json_duplicate_keys_and_constants(self):
        self.assertEqual(scenario.parse_manifest(json.dumps(candidate()), available_capabilities=CAPS), candidate())
        for text in ('{"schema":1,"schema":1}', '{"policy":{"internet":false,"internet":true}}', '{"schema":NaN}', 'invalid'):
            with self.subTest(text=text), self.assertRaises(scenario.ScenarioError):
                scenario.parse_manifest(text, available_capabilities=CAPS)

    def test_copy_and_fail_closed_capabilities(self):
        manifest = candidate()
        with self.assertRaises(scenario.ScenarioError):
            scenario.validate_manifest(manifest)
        for missing in CAPS:
            with self.subTest(missing=missing), self.assertRaises(scenario.ScenarioError):
                scenario.validate_manifest(manifest, available_capabilities=CAPS - {missing})
        validated = scenario.validate_manifest(manifest, available_capabilities=CAPS)
        validated["policy"]["internet"] = True
        self.assertFalse(manifest["policy"]["internet"])

    def test_reject_unsafe_and_malformed_fields(self):
        mutations = [
            lambda m: m.update(qemu_args=["-netdev", "user"]),
            lambda m: m.update(schema=True),
            lambda m: m["assets"]["kali"].update(path="/tmp/base"),
            lambda m: m["assets"]["kali"].update(source="/tmp/base"),
            lambda m: m["assets"]["kali"].update(sha256="bad"),
            lambda m: m["policy"].update(internet=True),
            lambda m: m["policy"].update(internet=0),
            lambda m: m["policy"].update(host_forwards=[22]),
            lambda m: m["policy"].update(guest_management_nic=True),
            lambda m: m["networks"]["inner"].update(cidr="192.168.243.0/24"),
            lambda m: m["networks"]["inner"].update(cidr="127.0.0.0/24"),
            lambda m: m["networks"]["inner"].update(gateway="192.168.244.1"),
            lambda m: m["networks"]["inner"].update(dns=["8.8.8.8"]),
            lambda m: m["networks"]["inner"].update(uplink="lan"),
            lambda m: m["networks"]["inner"].update(server="192.168.244.0"),
            lambda m: m["networks"]["inner"].update(pool=["192.168.244.1", "192.168.244.100"]),
            lambda m: m["networks"]["inner"]["leases"].update({"neuromancer/inner0": "192.168.244.20"}),
            lambda m: m["networks"]["inner"]["leases"].update({"neuromancer/inner0": "192.168.244.100"}),
            lambda m: m["networks"]["inner"]["leases"].update({"other/inner0": "192.168.244.50"}),
            lambda m: m["nodes"]["straylight"]["interfaces"].reverse(),
            lambda m: m["nodes"]["straylight"]["interfaces"][1].update(pci_slot=5),
            lambda m: m["nodes"]["kali"]["interfaces"][0].update(network="other/outer"),
            lambda m: m["nodes"]["kali"]["interfaces"].append(copy.deepcopy(m["nodes"]["kali"]["interfaces"][0])),
            lambda m: m["nodes"]["kali"].update(cpus=True),
            lambda m: m["nodes"]["kali"].update(memory_mb=8193),
            lambda m: m["nodes"]["kali"].update(firmware="bios"),
            lambda m: m["nodes"]["kali"].update(depends_on=["missing"]),
            lambda m: (m["nodes"]["kali"].update(depends_on=["straylight"]), m["nodes"]["straylight"].update(depends_on=["kali"])),
            lambda m: m["lifecycle"].update(reset="force"),
            lambda m: m["checks"].update(service=[{"port": 80}]),
        ]
        for index, mutate in enumerate(mutations):
            manifest = candidate()
            mutate(manifest)
            with self.subTest(index=index), self.assertRaises(scenario.ScenarioError):
                scenario.validate_manifest(manifest, available_capabilities=CAPS)
        for bad in [None, [], {}, {"schema": 1}]:
            with self.assertRaises(scenario.ScenarioError):
                scenario.validate_manifest(bad, available_capabilities=CAPS)

    def test_mac_and_instance_namespace(self):
        manifest = candidate()
        first = scenario.instance_plan(manifest, INSTANCE, available_capabilities=CAPS)
        self.assertEqual(first, scenario.instance_plan(manifest, INSTANCE, available_capabilities=CAPS))
        second = scenario.instance_plan(manifest, "22345678-1234-4234-8234-123456789abc", available_capabilities=CAPS)
        def macs(plan):
            return {nic["mac"] for node in plan["manifest"]["nodes"].values() for nic in node["interfaces"]}
        self.assertEqual(len(macs(first)), 4)
        self.assertFalse(macs(first) & macs(second))
        self.assertNotEqual(first["namespace"], second["namespace"])
        self.assertEqual(manifest, candidate())
        manifest["nodes"]["kali"]["interfaces"][0]["mac"] = "02:00:00:00:00:01"
        manifest["nodes"]["straylight"]["interfaces"][0]["mac"] = "02:00:00:00:00:01"
        with self.assertRaises(scenario.ScenarioError):
            scenario.validate_manifest(manifest, available_capabilities=CAPS)

    def command(self, node="straylight", **overrides):
        kwargs = dict(generation=1, state_root="/state", socket_root="/s", network_ports={"outer": 12001, "inner": 12002}, qemu_binary="/bin/qemu", available_capabilities=CAPS)
        if node == "kali":
            kwargs["firmware_code"] = "/firmware/code.fd"
        kwargs.update(overrides)
        return scenario.qemu_command(candidate(), INSTANCE, node, **kwargs)

    def test_pure_parameters_and_topology(self):
        with mock.patch("socket.socket", side_effect=AssertionError("禁止网络")), mock.patch("subprocess.Popen", side_effect=AssertionError("禁止进程")), mock.patch("builtins.open", side_effect=AssertionError("禁止文件 IO")):
            for node, count in [("kali", 1), ("straylight", 2), ("neuromancer", 1)]:
                command = self.command(node)
                self.assertEqual(command.count("-netdev"), count)
                joined = " ".join(command)
                for forbidden in ("hostfwd", "user,id", "tap,", "bridge,", "mgmt", "virtserialport", "virtfs", "port=", "listen="):
                    self.assertNotIn(forbidden, joined)
                self.assertIn("disable-copy-paste=on", joined)
                self.assertIn("disable-agent-file-xfer=on", joined)
                self.assertIn("-net none", joined)
                self.assertIn(f"scenarios/{INSTANCE}/generations/1/nodes/{node}/overlay.qcow2", joined)
            command = self.command()
            nets = [command[i + 1] for i, flag in enumerate(command) if flag == "-netdev"]
            self.assertEqual(nets, ["socket,id=nic0,connect=127.0.0.1:12001", "socket,id=nic1,connect=127.0.0.1:12002"])
            self.assertNotEqual(self.command(generation=2), command)

    def test_headless_omits_spice_and_keeps_qmp(self):
        with mock.patch("socket.socket", side_effect=AssertionError("禁止网络")), mock.patch("subprocess.Popen", side_effect=AssertionError("禁止进程")), mock.patch("builtins.open", side_effect=AssertionError("禁止文件 IO")):
            command = self.command(include_spice=False)
            joined = " ".join(command)
            self.assertNotIn("-spice", joined)
            self.assertIn("-qmp", joined)
            self.assertIn("usb-kbd", joined)
            self.assertEqual(command.count("-netdev"), 2)
        with self.assertRaises(scenario.ScenarioError):
            self.command(include_spice="no")

    def test_runtime_injection_and_invalid_bindings(self):
        for kwargs in [dict(state_root="/tmp/a,hostfwd=x"), dict(state_root="relative"), dict(socket_root="/tmp/../s"), dict(socket_root="/" + "s" * 100), dict(qemu_binary="/bin/qemu\nother"), dict(network_ports={"outer": 12001, "inner": 12001}), dict(network_ports={"outer": True, "inner": 12002}), dict(generation=0), dict(firmware_code="/unexpected")]:
            with self.subTest(kwargs=kwargs), self.assertRaises(scenario.ScenarioError):
                self.command(**kwargs)
        with self.assertRaises(scenario.ScenarioError):
            self.command("kali", firmware_code=None)
        with self.assertRaises(scenario.ScenarioError):
            scenario.instance_plan(candidate(), "../../other", available_capabilities=CAPS)


class DesignDocManifestTests(unittest.TestCase):
    """设计文档内嵌的场景清单必须始终通过当前 schema；防止文档随实现演进而腐化。"""

    def test_design_doc_manifest_blocks_validate(self):
        doc = Path(__file__).resolve().parents[2] / "docs" / "ctflab-wintermute-scenario-design.md"
        if not doc.exists():
            self.skipTest("设计文档不在仓库内；跳过文档清单守卫")
        text = doc.read_text(encoding="utf-8")
        blocks = re.findall(r"```json\n(.*?)\n```", text, re.S)
        self.assertTrue(blocks, "设计文档缺少内嵌清单")
        for index, block in enumerate(blocks):
            with self.subTest(block=index):
                manifest = scenario.parse_manifest(block, available_capabilities=CAPS)
                self.assertEqual(manifest["scenario_id"], "wintermute")
                self.assertFalse(manifest["policy"]["internet"])
                self.assertTrue(all(value == [] for value in manifest["checks"].values()))


if __name__ == "__main__":
    unittest.main()
