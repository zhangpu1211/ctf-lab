"""Kali助手材料生成测试：只验证生成的材料内容与摘要，不安装、不操作网络。"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError
from ctflab_kali_attach import (materials, render_assistant, setup_command, shell_command,
                                teardown_command, ASSISTANT_NAME)


class MaterialTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.destination = Path(self.root.name) / 'kali-materials'

    def test_materials_created_with_matching_manifest(self):
        manifest = materials(self.destination)
        self.assertEqual(manifest['kind'], 'ctflab-kali-attach-materials')
        self.assertEqual(manifest['guest_protocol'], 'ctflab-external-l2-v1')
        for name, digest in manifest['files'].items():
            path = self.destination / name
            self.assertTrue(path.is_file(), name)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, name)
        recorded = json.loads((self.destination / 'manifest.json').read_text())
        self.assertEqual(recorded['files'], manifest['files'])
        assistant = (self.destination / ASSISTANT_NAME)
        self.assertTrue((assistant.stat().st_mode & 0o111) != 0)

    def test_materials_refuse_existing_directory(self):
        materials(self.destination)
        with self.assertRaises(ContractError):
            materials(self.destination)

    def test_assistant_has_no_arbitrary_command_paths(self):
        script = render_assistant()
        # 固定子命令与固定shell；不存在任意命令执行入口。
        for required in ("'setup'", "'attach'", "'shell'", "'teardown'", "'status'",
                         "shell, '-i'", 'setpriv', '--clear-groups', 'SO_PEERCRED',
                         'SCM_RIGHTS', '/dev/net/tun', 'TUNSETIFF'):
            self.assertIn(required, script, required)
        for forbidden in ('os.system', 'shell=True', 'eval(', 'popen('):
            self.assertNotIn(forbidden, script.lower(), forbidden)
        # netns/TAP名从会话UUID派生，不接受用户输入作为接口名。
        self.assertIn("netns_name", script)
        self.assertIn("tap_name", script)
        # client拒绝root；daemon拒绝非root。
        self.assertIn('client不得以root运行', script)
        self.assertIn('daemon必须root运行', script)

    def test_sshd_snippet_forwards_are_disabled_and_forcecommand_fixed(self):
        content = (Path(tempfile.mkdtemp()) / 'x')
        generated = materials(content)
        snippet = (content / 'sshd-ctflab-attach.conf').read_text()
        for required in ('ForceCommand /usr/local/bin/ctflab-kali-attach attach',
                         'AllowTcpForwarding no', 'AllowAgentForwarding no',
                         'X11Forwarding no', 'PermitTunnel no', 'GatewayPorts no'):
            self.assertIn(required, snippet)
        # 会话经数据面握手选择；ForceCommand不得携带%i或会话参数。
        self.assertNotIn('%i', snippet)
        self.assertNotIn('--session', snippet)
        self.assertEqual(generated['generated_for_user'], 'ctflab-attach')


class CommandTests(unittest.TestCase):
    SESSION = '0d1f7e57-7b1e-4c8e-9c8d-2f1a3b4c5d60'

    def test_fixed_commands_embed_validated_parameters_only(self):
        setup = setup_command(self.SESSION, '02:AA:BB:CC:DD:EE', '192.168.50.9', 24)
        self.assertEqual(setup, 'sudo ctflab-kali-attach setup --session '
                                '0d1f7e57-7b1e-4c8e-9c8d-2f1a3b4c5d60 '
                                '--mac 02:aa:bb:cc:dd:ee --address 192.168.50.9 '
                                '--prefix 24 --mtu 1400')
        self.assertEqual(shell_command(self.SESSION),
                         'ctflab-kali-attach shell --session '
                         '0d1f7e57-7b1e-4c8e-9c8d-2f1a3b4c5d60')
        self.assertIn('teardown --session', teardown_command(self.SESSION))

    def test_commands_reject_unshaped_inputs(self):
        with self.assertRaises(ContractError):
            setup_command('short', '02:aa:bb:cc:dd:ee', '192.168.50.9', 24)
        with self.assertRaises(ContractError):
            setup_command(self.SESSION, '06:aa:bb:cc:dd:ee', '192.168.50.9', 24)
        with self.assertRaises(ContractError):
            setup_command(self.SESSION, '02:aa:bb:cc:dd:ee', '192.168.50.9', 31)
        with self.assertRaises(ContractError):
            shell_command('not-a-session; rm -rf /')


if __name__ == '__main__':
    unittest.main()
