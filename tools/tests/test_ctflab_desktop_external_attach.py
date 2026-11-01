"""桌面桥接外部攻击机动作测试：登记/预览/清除/材料；不操作VM、不启动中转。"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ctflab_desktop_bridge as bridge
from ctflab_desktop_bridge import record
orig_record = bridge.record
from ctflab_contract import ContractError
from ctflab_external_attach import AttachStore, classify_guest_identity, validate_registration


def registration():
    return {'schema': 1, 'kind': 'kali-l2-v1', 'name': '教室Kali',
            'node_uuid': str(uuid.uuid4()), 'machine_uuid': str(uuid.uuid4()),
            'vendor': 'VMware, Inc.', 'product': 'VMware Virtual Platform',
            'ssh': {'host': '127.0.0.1', 'port': 22, 'user': 'ctflab_attach',
                    'identity': '/Users/student/.ssh/ctflab_kali'},
            'assistant_sha256': 'a' * 64}


class StubStore:
    def __init__(self, manifest):
        import copy
        from test_ctflab_external_attach_acceptance import plan
        base = plan()['manifest']
        base['networks'] = copy.deepcopy(manifest['networks'])
        network = next(iter(base['networks']))
        subnet = base['networks'][network]['cidr'].rsplit('.', 1)[0]
        for i, node in enumerate(base['nodes'].values()):
            node['interfaces'][0].update(network=network, address=f'{subnet}.{20+i}')
        self.config = {'manifest': base}

    def locked(self):
        from contextlib import nullcontext
        return nullcontext()

    def snapshot(self):
        return {'active_generation': 2}


MANIFEST = {
    'networks': {
        'lab0': {'cidr': '192.168.50.0/24', 'uplink': 'none',
                 'external': {'schema': 1, 'address': '192.168.50.9', 'mac': '02:aa:bb:cc:dd:ee'}},
        'plain': {'cidr': '192.168.60.0/24', 'uplink': 'none'},
    },
    'nodes': {},
}


class ExternalAttachBridgeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store = StubStore(MANIFEST)
        self.instance = str(uuid.uuid4())

    def test_status_reports_slot_and_unregistered_binding(self):
        report = bridge.external_attach_dispatch(self.root, self.store, self.instance,
                                                 'external-attach-status', {'action': 'external-attach-status'})
        self.assertEqual(report['state'], 'external-attach-status')
        self.assertFalse(report['binding_valid'])
        self.assertIsNone(report['binding'])
        self.assertEqual([slot['network'] for slot in report['slots']], ['lab0'])
        self.assertFalse(report['connect_supported'])

    def test_save_requires_reserved_network_and_valid_registration(self):
        value = {'action': 'external-attach-save', 'registration': registration(),
                 'network': 'plain'}
        with self.assertRaises(ContractError):
            bridge.external_attach_dispatch(self.root, self.store, self.instance,
                                            'external-attach-save', value)
        value['network'] = 'lab0'
        result = bridge.external_attach_dispatch(self.root, self.store, self.instance,
                                                 'external-attach-save', value)
        self.assertEqual(result['state'], 'external-attach-saved')
        binding = result['binding']
        self.assertEqual(binding['network_id'], 'lab0')
        self.assertEqual(binding['generation'], 2)
        self.assertEqual(binding['attachment']['address'], '192.168.50.9')
        saved = json.loads((self.root / 'external-attach' / f'{self.instance}.json').read_text())
        self.assertEqual(saved['registration']['name'], '教室Kali')
        status = bridge.external_attach_dispatch(self.root, self.store, self.instance,
                                                 'external-attach-status', {'action': 'external-attach-status'})
        self.assertTrue(status['binding_valid'])

    def test_save_rejects_spoofed_registration_fields(self):
        value = {'action': 'external-attach-save',
                 'registration': {**registration(), 'assistant_sha256': 'nope'},
                 'network': 'lab0'}
        with self.assertRaises(ContractError):
            bridge.external_attach_dispatch(self.root, self.store, self.instance,
                                            'external-attach-save', value)

    def test_clear_removes_binding(self):
        bridge.external_attach_dispatch(self.root, self.store, self.instance,
                                        'external-attach-save',
                                        {'action': 'external-attach-save',
                                         'registration': registration(), 'network': 'lab0'})
        result = bridge.external_attach_dispatch(self.root, self.store, self.instance,
                                                 'external-attach-clear', {'action': 'external-attach-clear'})
        self.assertEqual(result['state'], 'external-attach-cleared')
        status = bridge.external_attach_dispatch(self.root, self.store, self.instance,
                                                 'external-attach-status', {'action': 'external-attach-status'})
        self.assertFalse(status['binding_valid'])

    def test_materials_written_to_new_directory_only(self):
        destination = self.root / 'kali-materials'
        result = bridge.external_attach_dispatch(self.root, self.store, self.instance,
                                                 'external-attach-materials',
                                                 {'action': 'external-attach-materials',
                                                  'destination': str(destination)})
        self.assertEqual(result['state'], 'external-attach-materials')
        self.assertTrue((destination / 'ctflab-kali-attach').is_file())
        with self.assertRaises(ContractError):
            bridge.external_attach_dispatch(self.root, self.store, self.instance,
                                            'external-attach-materials',
                                            {'action': 'external-attach-materials',
                                             'destination': str(destination)})


class IdentityPolicyTests(unittest.TestCase):
    def test_recognized_families(self):
        from ctflab_external_attach import classify_guest_identity
        cases = {('VMware, Inc.', 'VMware Virtual Platform'): 'vmware',
                 ('Parallels International GmbH', 'Parallels Virtual Platform'): 'parallels',
                 ('Parallels International GmbH.', 'Parallels ARM Virtual Machine'): 'parallels',
                 ('QEMU', 'Standard PC (Q35 + ICH9, 2009)'): 'utm-qemu',
                 ('innotek GmbH', 'VirtualBox'): 'virtualbox',
                 ('Microsoft Corporation', 'Virtual Machine'): 'hyperv'}
        for (vendor, product), family in cases.items():
            self.assertEqual(classify_guest_identity(vendor, product), family)

    def test_unknown_vendor_rejected_without_bypass(self):
        from ctflab_external_attach import classify_guest_identity
        with self.assertRaises(ContractError):
            classify_guest_identity('MyCloud Inc.', 'Custom VM')
        with self.assertRaises(ContractError):
            classify_guest_identity('VMware, Inc.', 'Totally Not VMware')

    def test_registration_rejects_unknown_and_accepts_parallels(self):
        value = registration()
        value['vendor'] = 'Parallels International GmbH'
        value['product'] = 'Parallels Virtual Platform'
        self.assertEqual(validate_registration(value)['identity_family'], 'parallels')
        with self.assertRaises(ContractError):
            validate_registration({**registration(), 'vendor': 'Acme', 'product': 'Box'})


SESSION_MANIFEST = {
    'networks': {
        'outer': {'cidr': '10.80.0.0/24', 'uplink': 'none',
                  'external': {'schema': 1, 'address': '10.80.0.9', 'mac': '02:aa:bb:cc:dd:0e'}},
        'plain': {'cidr': '10.81.0.0/24', 'uplink': 'none'},
    },
    'nodes': {},
}


class SessionChainTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.store = StubStore(SESSION_MANIFEST)
        self.instance = str(uuid.uuid4())
        # profile带outer预留口：连接前置条件之一
        record(self.root/'runtime-profile.json',
               {'networks': {'outer': {'client': 40010, 'external': 40011}, 'plain': 40012}})
        # 设计§4.3持久批准：连接路径统一按用户账本核验；测试用独立账本目录。
        from ctflab_external_attach import approve_assistant
        self.ledger = self.root/'approvals'
        self.approval_manifest = {'schema': 1, 'kind': 'ctflab-kali-attach-materials',
                                  'files': {'ctflab-kali-attach': registration()['assistant_sha256']}}
        env = patch.dict('os.environ', {'CTFLAB_EXTERNAL_ATTACH_APPROVALS': str(self.ledger)})
        env.start(); self.addCleanup(env.stop)

    def approve_registration(self, value):
        from ctflab_external_attach import approve_assistant
        approve_assistant(value, self.approval_manifest, self.ledger)

    def connect_ssh(self):
        import tempfile
        ssh_root = Path(tempfile.mkdtemp()).resolve()
        identity = ssh_root/'kali-key'; identity.write_bytes(b'key'); identity.chmod(0o600)
        known = ssh_root/'known_hosts'; known.write_bytes(b''); known.chmod(0o600)
        binary = ssh_root/'ssh'; binary.write_bytes(b''); binary.chmod(0o755)
        return {'schema': 1, 'host': '127.0.0.1', 'port': 22, 'user': 'ctflab_attach',
                'ssh': str(binary), 'identity': str(identity), 'known_hosts': str(known),
                'known_hosts_sha256': hashlib.sha256(b'').hexdigest(),
                'server_uuid': self.registration_node}

    def dispatch(self, value):
        return bridge.external_attach_dispatch(self.root, self.store, self.instance,
                                               value['action'], value)

    def setUp_registration_without_approval(self):
        self.registration_node = str(uuid.uuid4())
        self.saved_registration = {**registration(), 'node_uuid': self.registration_node}
        self.dispatch({'action': 'external-attach-save',
                       'registration': self.saved_registration,
                       'network': 'outer'})

    def setUp_registration(self):
        self.setUp_registration_without_approval()
        self.approve_current_registration()

    def approve_current_registration(self):
        self.approve_registration(self.saved_registration)

    def test_connect_supported_requires_binding_and_reserved_port(self):
        status = self.dispatch({'action': 'external-attach-status'})
        self.assertFalse(status['connect_supported'])  # 未登记
        self.setUp_registration()
        status = self.dispatch({'action': 'external-attach-status'})
        self.assertTrue(status['connect_supported'])
        self.assertEqual(status['slots'][0]['reserved_port'], 40011)

    def test_connect_requires_persistent_assistant_approval(self):
        self.setUp_registration_without_approval()
        # 未批准（账本无该节点+机器+摘要组合）：桌面连接同样按identity-unknown拒绝。
        with patch.object(bridge, 'launch') as launch:
            with self.assertRaises(ContractError) as error:
                self.dispatch({'action': 'external-attach-connect',
                               'ssh_config': self.connect_ssh_path()})
            self.assertEqual(error.exception.code, 'identity-unknown')
            launch.assert_not_called()
        # CLI批准同一材料清单后即可连接；摘要不符的登记仍拒绝。
        self.approve_current_registration()
        with patch.object(bridge, 'launch', return_value=type('P', (), {'pid': 424242})()):
            self.assertEqual(self.dispatch({'action': 'external-attach-connect',
                                            'ssh_config': self.connect_ssh_path()})['state'],
                             'relay-requested')

    def test_connect_spawns_worker_and_disconnect_marks_detached(self):
        self.setUp_registration()
        spawned = []
        recorded = []
        real_launch = bridge.launch
        try:
            def fake_launch(root, action, **kwargs):
                spawned.append((action, kwargs.get('session')))
                return type('P', (), {'pid': 424242})()
            bridge.launch = fake_launch
            bridge.record = lambda path, value: (recorded.append(Path(path).name),
                                                 orig_record(path, value))
            result = self.dispatch({'action': 'external-attach-connect',
                                    'ssh_config': self.connect_ssh_path()})
            self.assertEqual(result['state'], 'relay-requested')
            self.assertEqual(spawned, [('external-relay', result['session_uuid'])])
            with patch.object(bridge, 'observe_relay_process', return_value=True):
                status = self.dispatch({'action': 'external-attach-status'})
            self.assertEqual(status['session']['state'], 'connecting')
            # 再次连接被拒：已有进行中的会话
            with self.assertRaises(ContractError):
                self.dispatch({'action': 'external-attach-connect',
                               'ssh_config': self.connect_ssh_path()})
            # 断开：观察器报告进程存活→终止并落disconnected
            alive = {'value': True}
            def flaky_observer(session):
                return alive['value']
            def fake_kill(pid, sig):
                attach = AttachStore(self.root, self.instance, generation=2, network_id='outer')
                fresh = attach.load()
                fresh['session'].update(state='disconnected', report={'reason':'completed', 'transport_closed':True})
                attach.save(fresh)
                alive['value'] = False
            with patch.object(bridge, 'observe_relay_process', flaky_observer), \
                 patch.object(bridge.os, 'kill', fake_kill), \
                 patch('time.sleep', lambda *_: None):
                detached = self.dispatch({'action': 'external-attach-disconnect'})
            self.assertEqual(detached['state'], 'relay-detached')
            self.assertTrue(detached['terminated_by_user'])
            status = self.dispatch({'action': 'external-attach-status'})
            self.assertEqual(status['session']['state'], 'disconnected')
            # 断开后可再次连接
            result2 = self.dispatch({'action': 'external-attach-connect',
                                     'ssh_config': self.connect_ssh_path()})
            self.assertEqual(result2['state'], 'relay-requested')
        finally:
            bridge.launch = real_launch
            bridge.record = orig_record

    def test_unconfirmed_termination_stays_unknown_not_disconnected(self):
        """核验复现：kill失败或进程仍存活时不得落disconnected。"""
        self.setUp_registration()
        real_launch = bridge.launch
        try:
            bridge.launch = lambda root, action, **k: type('P', (), {'pid': 424242})()
            self.dispatch({'action': 'external-attach-connect',
                           'ssh_config': self.connect_ssh_path()})
            with patch.object(bridge, 'observe_relay_process', return_value=True), \
                 patch.object(bridge.os, 'kill', side_effect=OSError('no-such-process')):
                result = self.dispatch({'action': 'external-attach-disconnect'})
            self.assertEqual(result['state'], 'relay-unknown')
            self.assertFalse(result['terminated_by_user'])
            status = self.dispatch({'action': 'external-attach-status'})
            self.assertEqual(status['session']['state'], 'unknown')
            self.assertIn('terminate-failed', status['session'].get('disconnect_failure', ''))
            with patch.object(bridge, 'observe_relay_process', return_value=True), \
                 patch.object(bridge.os, 'kill', lambda *a, **k: None):
                still = self.dispatch({'action': 'external-attach-disconnect'})
            self.assertEqual(still['state'], 'relay-unknown')
            self.assertEqual(still['note'], '终止未证实；保留unknown与恢复入口，请核对进程后重试或显式清除。')
        finally:
            bridge.launch = real_launch

    def test_connect_requires_ssh_config_server_binding(self):
        self.setUp_registration()
        import json as _json
        path = self.root/'bad-ssh.json'
        config = self.connect_ssh()
        config['server_uuid'] = str(uuid.uuid4())  # 与登记node_uuid不一致
        path.write_text(_json.dumps(config)); path.chmod(0o600)
        with self.assertRaises(ContractError):
            self.dispatch({'action': 'external-attach-connect', 'ssh_config': str(path)})

    def test_dead_worker_without_report_marks_unknown_and_allows_clear(self):
        self.setUp_registration()
        real_launch = bridge.launch
        try:
            bridge.launch = lambda root, action, **k: type('P', (), {'pid': 424242})()
            self.dispatch({'action': 'external-attach-connect',
                           'ssh_config': self.connect_ssh_path()})
            with patch.object(bridge, 'observe_relay_process', return_value=False):
                status = self.dispatch({'action': 'external-attach-status'})
                self.assertEqual(status['session']['state'], 'unknown')
                cleared = self.dispatch({'action': 'external-attach-clear'})
            self.assertEqual(cleared['state'], 'external-attach-cleared')
            self.assertFalse(self.dispatch({'action': 'external-attach-status'})['binding_valid'])
        finally:
            bridge.launch = real_launch

    def test_prepare_exports_bound_setup_and_connect_reuses_exact_session(self):
        self.setUp_registration()
        result = self.dispatch({'action': 'external-attach-materials',
                                'destination': str(self.root/'materials-bound')})
        prepared = result['manifest']['prepared']
        status = self.dispatch({'action': 'external-attach-status'})
        binding = status['binding']
        self.assertEqual(binding['prepared'], prepared)
        for text in (prepared['session_uuid'], self.instance, '--generation 2',
                     '--network-id outer', binding['policy_sha256'], '--address 10.80.0.9'):
            self.assertIn(text, prepared['setup_command'])
        from ctflab_external_attach import policy_summary, derive_allowed_macs
        from ctflab_scenario_v2 import instance_plan
        policy = policy_summary(binding['attachment'], derive_allowed_macs(
            instance_plan(self.store.config['manifest'], self.instance), 'outer'))
        self.assertEqual(policy['policy_sha256'], binding['policy_sha256'])
        self.assertTrue(policy['policy']['allowed_macs'])
        with patch.object(bridge, 'launch', return_value=type('P', (), {'pid': 424242})()):
            connected = self.dispatch({'action': 'external-attach-connect',
                                       'ssh_config': self.connect_ssh_path()})
        self.assertEqual(connected['session_uuid'], prepared['session_uuid'])
        self.assertTrue(self.dispatch({'action': 'external-attach-status'})['binding']['prepared']['used'])

    def test_connect_without_prepared_grant_is_refused_before_launch(self):
        self.setUp_registration()
        path = self.root/'ssh.json'
        path.write_text(json.dumps(self.connect_ssh())); path.chmod(0o600)
        with patch.object(bridge, 'launch') as launch, self.assertRaises(ContractError):
            self.dispatch({'action': 'external-attach-connect', 'ssh_config': str(path)})
        launch.assert_not_called()

    def connect_ssh_path(self):
        status = self.dispatch({'action': 'external-attach-status'})
        if status['session']['state'] in ('idle', 'disconnected') and (
                not status['binding'].get('prepared') or status['binding']['prepared'].get('used')):
            self.dispatch({'action': 'external-attach-materials',
                           'destination': str(self.root/f'prepared-materials-{uuid.uuid4()}')})
        import json
        path = self.root/'external-ssh-config.json'
        path.parent.mkdir(mode=0o700, exist_ok=True)
        path.write_text(json.dumps(self.connect_ssh()))
        path.chmod(0o600)
        return str(path)


if __name__ == '__main__':
    unittest.main()
