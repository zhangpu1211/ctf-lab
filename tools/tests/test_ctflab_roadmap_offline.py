"""拓扑、草稿、离线课程和Windows证据汇总的边界验证。"""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_topology as topology
import ctflab_evidence_course as course
import ctflab_windows_evidence as evidence
from ctflab_scenario_v2 import instance_plan
from test_ctflab_scenario_v2 import sample


class TopologyTests(unittest.TestCase):
    def setUp(self):
        self.manifest = sample()
        self.instance = str(uuid.uuid4())
        self.now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        self.observation = {'instance_uuid': self.instance, 'generation': 1,
                            'plan_sha256': instance_plan(self.manifest, self.instance)['plan_sha256'],
                            'node': 'client', 'timestamp': '2026-10-23T00:00:00Z', 'state': 'guest-ready',
                            'addresses': {'eth0': '10.80.0.11'}, 'evidence_ref': 'probe-one'}

    def test_design_does_not_promote_address_or_runtime(self):
        view = topology.projection(self.manifest, self.instance)
        self.assertTrue(all(n['state'] == 'unknown' for n in view['nodes']))
        self.assertTrue(all(i['observed_address'] is None for n in view['nodes'] for i in n['interfaces']))
        self.assertFalse(view['runtime_verified'])
        self.assertIn('设计地址', topology.render(view))

    def test_fresh_and_stale_observation(self):
        view = topology.projection(self.manifest, self.instance, observations=[self.observation], now=self.now)
        self.assertEqual(view['nodes'][-1]['interfaces'][0]['observed_address'], '10.80.0.11')
        self.observation['timestamp'] = '2026-10-22T23:00:00Z'
        view = topology.projection(self.manifest, self.instance, observations=[self.observation], now=self.now)
        self.assertEqual(view['nodes'][-1]['state'], 'unknown')
        self.assertIsNone(view['nodes'][-1]['interfaces'][0]['observed_address'])

    def test_cross_generation_future_duplicate_rejected(self):
        for key, value in [('generation', 2), ('plan_sha256', 'f'*64), ('timestamp', '2026-10-24T00:00:00Z')]:
            obs = dict(self.observation, **{key: value})
            with self.assertRaises(ValueError):
                topology.projection(self.manifest, self.instance, observations=[obs], now=self.now)
        with self.assertRaises(ValueError):
            topology.projection(self.manifest, self.instance, observations=[self.observation]*2, now=self.now)

    def test_matrix_does_not_infer_router_or_run_probes(self):
        report = topology.network_checks(self.manifest, self.instance)
        check = next(c for c in report['checks'] if c['source'] == 'client' and c['destination'] == 'server')
        self.assertEqual(check['expected'], 'deny')
        self.assertTrue(any(c['family'] == 'ipv6' and c['destination'] == 'host' for c in report['checks']))
        self.assertTrue(all(c['result'] == 'not-run' for c in report['checks']))

    def test_draft_diff_validates_and_never_changes_original(self):
        proposed = copy.deepcopy(self.manifest)
        proposed['nodes']['client']['memory_mb'] = 1024
        result = topology.draft_diff(self.manifest, proposed, self.instance)
        self.assertEqual(result['changes'][0]['path'], '/nodes/client/memory_mb')
        self.assertEqual(self.manifest['nodes']['client']['memory_mb'], 512)
        self.assertFalse(result['applied'])
        proposed['policy']['internet'] = True
        with self.assertRaises(ValueError):
            topology.draft_diff(self.manifest, proposed, self.instance)

    def acceptance_for(self, proposed, *, result='passed'):
        diff = topology.draft_diff(self.manifest, proposed, self.instance)
        return {'schema': 1, 'kind': 'scenario-acceptance', 'scenario_id': proposed['scenario_id'],
                'manifest_sha256': topology.canonical_digest(proposed),
                'next_plan_sha256': diff['next_plan_sha256'], 'next_generation': diff['next_generation'],
                'result': result, 'evidence_ref': 'scenario-acceptance-run-1',
                'recorded_at': '2026-10-31T10:00:00+00:00'}

    def test_publish_qualification_binds_exact_digest_and_refuses_bad_graphs(self):
        proposed = copy.deepcopy(self.manifest)
        proposed['nodes']['client']['memory_mb'] = 1024
        acceptance = self.acceptance_for(proposed)
        record = topology.publish_qualification(self.manifest, proposed, self.instance, acceptance=acceptance)
        self.assertFalse(record['applied']); self.assertTrue(record['requires_new_generation'])
        self.assertFalse(record['runtime_verified']); self.assertFalse(record['automatic_replay'])
        self.assertEqual(record['next_generation'], 2)
        self.assertTrue(topology.verify_qualification(record, self.manifest, proposed, self.instance))
        # 摘要变化即失效：改草稿后旧资格拒绝，新草稿也不能复用旧验收记录。
        changed = copy.deepcopy(proposed)
        changed['nodes']['client']['memory_mb'] = 2048
        with self.assertRaises(ValueError):
            topology.verify_qualification(record, self.manifest, changed, self.instance)
        with self.assertRaises(ValueError):
            topology.publish_qualification(self.manifest, changed, self.instance, acceptance=acceptance)
        # 代次与实例绑定；运行中代次不被热改（记录只指向下一代次）。
        with self.assertRaises(ValueError):
            topology.verify_qualification(record, self.manifest, proposed, self.instance, generation=2)
        with self.assertRaises(ValueError):
            topology.verify_qualification(record, self.manifest, proposed, str(uuid.uuid4()))
        # 错误图不可执行：S03拒绝优先于任何验收记录。
        cyclic = copy.deepcopy(proposed)
        cyclic['nodes']['client']['depends_on'] = ['middle']
        cyclic['nodes']['middle']['depends_on'] = ['client']
        with self.assertRaises(ValueError):
            topology.publish_qualification(self.manifest, cyclic, self.instance, acceptance=acceptance)
        for changes in ({'result': 'failed'}, {'manifest_sha256': '0'*64}, {'next_plan_sha256': 'f'*64},
                        {'next_generation': 3}, {'evidence_ref': '-bad'}, {'recorded_at': '2026-10-31T10:00:00'},
                        {'extra': 'x'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                topology.publish_qualification(self.manifest, proposed, self.instance,
                                               acceptance=dict(acceptance, **changes))
        with self.assertRaises(ValueError):
            topology.publish_qualification(self.manifest, proposed, self.instance, acceptance=None)
        # 资格记录被改同样失效。
        for changes in ({'applied': True}, {'runtime_verified': True}, {'automatic_replay': True},
                        {'next_plan_sha256': 'f'*64}, {'manifest_sha256': '0'*64}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                topology.verify_qualification(dict(record, **changes), self.manifest, proposed, self.instance)

    def test_template_gate_cli_publish_verify_and_no_overwrite(self):
        proposed = copy.deepcopy(self.manifest)
        proposed['nodes']['client']['memory_mb'] = 1024
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)/'m.json'; draft = Path(temp)/'d.json'
            acc = Path(temp)/'a.json'; out = Path(temp)/'q.json'
            base.write_text(json.dumps(self.manifest)); draft.write_text(json.dumps(proposed))
            acc.write_text(json.dumps(self.acceptance_for(proposed)))
            argv = [str(base), '--instance', self.instance, '--format', 'publish-qualification',
                    '--proposed', str(draft), '--acceptance', str(acc)]
            self.assertEqual(topology.main(argv + ['--output', str(out)]), 0)
            first = out.read_bytes()
            self.assertIn('executable-template-qualification', first.decode())
            # 已有文件不覆盖；缺验收记录拒绝。
            self.assertEqual(topology.main(argv + ['--output', str(out)]), 2)
            self.assertEqual(out.read_bytes(), first)
            self.assertEqual(topology.main(argv[:5] + ['--proposed', str(draft), '--output', str(out) + '.x']), 2)
            self.assertFalse((Path(temp)/'q.json.x').exists())
            qpath = Path(temp)/'q-saved.json'; qpath.write_bytes(first)
            verify = [str(base), '--instance', self.instance, '--format', 'verify-qualification',
                      '--qualification', str(qpath), '--proposed', str(draft)]
            self.assertEqual(topology.main(verify), 0)
            draft.write_text(json.dumps({**proposed,
                'nodes': {**proposed['nodes'], 'client': {**proposed['nodes']['client'], 'memory_mb': 4096}}}))
            self.assertEqual(topology.main(verify), 2)
            self.assertEqual(topology.main([str(base), '--instance', self.instance, '--format', 'diff',
                                            '--proposed', str(draft)]), 0)

    def test_html_escapes_and_cli_refuses_overwrite(self):
        view = topology.projection(self.manifest, self.instance)
        view['nodes'][0]['state'] = '<script>alert(1)</script>'
        self.assertNotIn('<script>', topology.render(view))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'manifest.json'
            path.write_text(json.dumps(self.manifest))
            before = path.read_bytes()
            self.assertEqual(topology.main([str(path), '--instance', self.instance, '--output', str(path)]), 2)
            self.assertEqual(path.read_bytes(), before)

    def test_offline_cli_isolated_python_from_unrelated_directory(self):
        entry = Path(topology.__file__).with_name('ctflab_offline.py')
        with tempfile.TemporaryDirectory() as temp:
            for command in ('topology', 'evidence-course', 'windows-evidence', 'scenario-plan', 'course-catalog'):
                result = subprocess.run([sys.executable, '-I', '-B', str(entry), command, '--help'],
                                        cwd=temp, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)


class CourseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        course.build(self.root / 'course')
        self.student = self.root / 'student'
        with zipfile.ZipFile(self.root / 'course/C05-student.zip') as archive:
            archive.extractall(self.student)  # 只解压本测试刚生成的可信固定文件。

    def test_deterministic_separate_answers_and_integrity(self):
        first = (self.root / 'course/C05-student.zip').read_bytes()
        course.build(self.root / 'second')
        self.assertEqual(first, (self.root / 'second/C05-student.zip').read_bytes())
        self.assertFalse(any('教师' in p.name for p in self.student.rglob('*')))
        self.assertTrue(course.verify(self.student)['integrity_verified'])
        self.assertFalse(course.verify(self.student)['classroom_verified'])
        verifier = self.student / 'verify.py'
        self.assertNotIn('TEACHER', verifier.read_text())
        self.assertNotIn('预设事实', verifier.read_text())
        result = subprocess.run([sys.executable, '-I', '-B', str(verifier)], cwd=self.root,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['integrity_verified'])

    def test_tampering_extra_and_missing_evidence(self):
        target = self.student / 'evidence/web-access.log'
        original = target.read_bytes()
        target.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            course.verify(self.student)
        target.write_bytes(original)
        (self.student / 'unlisted.txt').write_text('extra')
        with self.assertRaises(ValueError):
            course.verify(self.student)

    def test_path_escape_and_symlink_rejected(self):
        manifest_path = self.student / 'MANIFEST.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files']['../outside'] = {'sha256': 'a'*64, 'bytes': 1}
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            course.verify(self.student)

    def test_cross_log_references_and_expected_config_change(self):
        events = [json.loads(line) for line in (self.student / 'evidence/auth-events.jsonl').read_text().splitlines()]
        self.assertEqual(events[2]['session_label'], events[3]['session_label'])
        self.assertEqual(events[3]['request'], 'r05')
        audit = (self.student / 'evidence/change-audit.csv').read_text()
        self.assertIn('r05,training-admin,app.maintenance,false,true,applied', audit)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'config.json').write_text(json.dumps({'instance_uuid': str(uuid.uuid4()), 'generation': 1}))
        (self.root / 'host.json').write_text(json.dumps({'system': 'Windows', 'version': '10.0.12345', 'machine': 'AMD64', 'python': '3.10.20'}))
        (self.root / 'result.json').write_text(json.dumps({'state': 'exited', 'returncode': 0, 'source_unchanged': True,
            'shutdown_guest_event': True, 'stderr_complete': True, 'g0_passed': False, 'graceful_stop_verified': False,
            'control_failure': None, 'private': 'private-secret'}))
        (self.root / 'qemu-stderr.log').write_text('private-secret\nwarning\n')

    def test_summary_hashes_without_private_contents_or_pass_promotion(self):
        report = evidence.summary(self.root)
        self.assertTrue(report['required_artifacts_complete'])
        self.assertNotIn('private-secret', json.dumps(report))
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertFalse(report['g0_passed'])
        self.assertIsNone(report['terminal_reopened_user_statement'])

    def test_missing_invalid_and_duplicate_json_remain_incomplete(self):
        (self.root / 'host.json').unlink()
        (self.root / 'result.json').write_text('{"state":"exited","state":"failed"}')
        report = evidence.summary(self.root)
        self.assertFalse(report['required_artifacts_complete'])
        self.assertIn('result.json', report['invalid'])
        self.assertIn('host.json', report['missing'])

    def test_export_never_overwrites_original_and_package_mismatch(self):
        before = (self.root / 'result.json').read_bytes()
        self.assertEqual(evidence.main(['--run', str(self.root), '--output', str(self.root / 'result.json')]), 2)
        self.assertEqual((self.root / 'result.json').read_bytes(), before)
        (self.root / 'kit.zip').write_bytes(b'not-the-expected-kit')
        report = evidence.summary(self.root, self.root / 'kit.zip', True)
        self.assertFalse(report['kit']['matches_control_r1'])
        self.assertTrue(report['terminal_reopened_user_statement'])


if __name__ == '__main__':
    unittest.main()
