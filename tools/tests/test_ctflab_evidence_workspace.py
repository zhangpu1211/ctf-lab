"""C05实际独立学生工具、只读快照、调查副本与教师复盘；全为新临时材料。"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_evidence_course as course
import ctflab_evidence_workspace as workspace


class EvidenceWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve(); self.pack = self.root/'pack'
        course.build(self.pack); self.student = self.root/'student'
        with zipfile.ZipFile(self.pack/'C05-student.zip') as archive:
            archive.extractall(self.student)  # 本轮刚生成的固定可信样本；不是通用解压器。
        self.pin = (self.pack/'student-manifest.sha256').read_text().strip()
        self.destination = self.root/'investigation'

    def fingerprints(self, root):
        return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mode)
                for p in root.rglob('*') if p.is_file()}

    def prepare(self):return workspace.prepare(self.student, self.destination, self.pin)

    def test_new_readonly_original_writable_work_and_source_modes_unchanged(self):
        before = self.fingerprints(self.student); result = self.prepare()
        self.assertTrue(result['original_readonly_verified']); self.assertFalse(result['tamperproof'])
        self.assertTrue(result['source_rechecked']); self.assertFalse(result['source_modified'])
        self.assertFalse(result['classroom_verified']); self.assertFalse(result['publisher_identity_verified'])
        self.assertEqual(before, self.fingerprints(self.student))
        self.assertEqual(course.verify(self.destination/'work')['files'], result['files'])
        self.assertTrue((self.destination/'work/evidence/web-access.log').stat().st_mode & 0o200)
        self.assertFalse((self.destination/'original/evidence/web-access.log').stat().st_mode & 0o200)

    def test_external_manifest_pin_required_before_creating(self):
        for value in ('b'*64, '', None, 'A'*64):
            with self.subTest(pin=value), self.assertRaises((ValueError, TypeError)):
                workspace.prepare(self.student, self.destination, value)
            self.assertFalse(self.destination.exists())

    def test_changed_source_refused_before_creation(self):
        (self.student/'evidence/web-access.log').write_text('changed')
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.destination.exists())

    def test_existing_destination_preserved_and_never_reused(self):
        self.destination.mkdir(); marker = self.destination/'existing'; marker.write_text('keep')
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(marker.read_text(), 'keep')

    def test_nested_destination_never_changes_original(self):
        before = self.fingerprints(self.student)
        with self.assertRaises(ValueError):workspace.prepare(self.student, self.student/'new', self.pin)
        self.assertEqual(before, self.fingerprints(self.student)); self.assertFalse((self.student/'new').exists())

    def test_source_or_destination_links_refused(self):
        link = self.root/'alias'; link.symlink_to(self.student, target_is_directory=True)
        with self.assertRaises(ValueError):workspace.prepare(link, self.destination, self.pin)
        self.destination.symlink_to(self.root/'uncreated', target_is_directory=True)
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse((self.root/'uncreated').exists())

    def test_reparse_marker_is_refused_before_source_file_read(self):
        original = Path.lstat
        def observe(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == self.student/'evidence':
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info
        with patch.object(Path, 'lstat', observe), self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.destination.exists())

    def test_source_changes_during_copy_leaves_partial_without_success_receipt(self):
        original = workspace.new_file; modified = False
        def change(path, raw):
            nonlocal modified
            result = original(path, raw)
            if not modified:
                modified = True; (self.student/'evidence/web-access.log').write_text('changed concurrently')
            return result
        with patch.object(workspace, 'new_file', side_effect=change), self.assertRaises(ValueError):self.prepare()
        self.assertTrue(self.destination.exists()); self.assertFalse((self.destination/'WORKSPACE.json').exists())

    def test_writable_original_or_changed_original_is_not_verified(self):
        self.prepare(); path = self.destination/'original/evidence/web-access.log'
        os.chmod(path, 0o600)
        with self.assertRaises(ValueError):workspace.inspect_workspace(self.destination, self.pin)
        path.write_text('changed'); os.chmod(path, 0o400)
        with self.assertRaises(ValueError):workspace.inspect_workspace(self.destination, self.pin)

    @unittest.skipIf(os.name == 'nt', 'Windows目录只读不是POSIX权限；原生另验')
    def test_writable_original_directory_is_not_verified(self):
        self.prepare(); os.chmod(self.destination/'original/evidence', 0o700)
        with self.assertRaises(ValueError):workspace.inspect_workspace(self.destination, self.pin)

    def test_work_notes_and_reports_do_not_modify_original_or_claim_report_checked(self):
        self.prepare(); original = self.fingerprints(self.destination/'original')
        (self.destination/'work/evidence/web-access.log').write_text('my annotated copy')
        (self.destination/'reports/调查报告.md').write_text('r05引用，因果仍需独立验证')
        result = workspace.inspect_workspace(self.destination, self.pin)
        self.assertFalse(result['working_copy_checked']); self.assertFalse(result['reports_checked'])
        self.assertEqual(original, self.fingerprints(self.destination/'original'))

    def test_later_inspect_never_claims_unobserved_source_is_unchanged(self):
        self.prepare(); (self.student/'evidence/web-access.log').write_text('later source changed')
        result = workspace.inspect_workspace(self.destination, self.pin)
        self.assertTrue(result['original_readonly_verified'])
        self.assertFalse(result['source_rechecked']); self.assertNotIn('source_modified', result)

    def test_partial_write_preserved_without_complete_receipt_or_replay(self):
        original = workspace.new_file; count = 0
        def fail(path, raw):
            nonlocal count
            count += 1
            if count == 3:raise OSError('本轮受控中断')
            return original(path, raw)
        with patch.object(workspace, 'new_file', side_effect=fail), self.assertRaises(OSError):self.prepare()
        self.assertTrue(self.destination.exists()); self.assertFalse((self.destination/'WORKSPACE.json').exists())
        with self.assertRaises(ValueError):self.prepare()
        self.assertTrue(course.verify(self.student)['integrity_verified'])

    def test_standalone_student_tool_runs_isolated_without_teacher_or_project_imports(self):
        script = self.student/'workspace.py'; raw = script.read_text()
        self.assertNotIn('TEACHER', raw); self.assertNotIn('import ctflab', raw)
        self.assertNotIn('逐条证据复盘示例', raw)
        result = subprocess.run([sys.executable, '-I', '-B', str(script), 'prepare', str(self.destination),
                                 '--manifest-sha256', self.pin], cwd=self.root, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['original_readonly_verified'])
        result = subprocess.run([sys.executable, '-I', '-B', str(script), 'inspect', str(self.destination),
                                 '--manifest-sha256', self.pin], cwd=self.root, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_teacher_replay_separate_and_bound_to_exact_student_manifest(self):
        with zipfile.ZipFile(self.pack/'C05-teacher.zip') as archive:
            self.assertEqual(archive.read('student-manifest.sha256').decode().strip(), self.pin)
            report = archive.read('逐条证据复盘.md').decode()
        for expected in ('web-access.log第6行', 'auth-events.jsonl第4行', 'change-audit.csv第2行',
                         'synthetic-session-a', '不能确认', '复验普通首页'):
            self.assertIn(expected, report)
        for path in self.student.rglob('*'):
            if path.is_file():self.assertNotIn('C05逐条证据复盘示例'.encode(), path.read_bytes())

    def test_project_cli_missing_prepare_parameters_preserves_source(self):
        self.assertEqual(course.main(['prepare', str(self.student), '--manifest-sha256', self.pin]), 2)
        self.assertFalse(self.destination.exists()); self.assertTrue(course.verify(self.student)['integrity_verified'])


if __name__ == '__main__':unittest.main()
