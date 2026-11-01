"""当前操作入口与历史记录分离，防止旧路径/显示策略回流。"""
from pathlib import Path
import re
import shlex
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs'
sys.path.insert(0, str(ROOT / 'tools'))
import ctflab

class CurrentDocumentationTests(unittest.TestCase):
    def test_current_entrypoints_do_not_reference_retired_builds(self):
        for name in ('ctflab-current-status.md', 'ctflab-student-distribution-tutorial.md',
                     'ctflab-distribution-guide.md'):
            text = (DOCS / name).read_text()
            for old in ('ctflab-app-build-macos15-auto-final2', 'base-80718f780e3b-installed',
                        '04-软件', '05-说明', 'ctflab-dist-spice-release-20260916'):
                self.assertNotIn(old, text, name)

    def test_current_status_separates_release_source_and_assets(self):
        text = (DOCS / 'ctflab-current-status.md').read_text()
        for phrase in ('0.1.1-preview', 'macOS 26', '尚未重新打包', '不含运行进度',
                       '01-待处理', '02-已处理', '03-软件', '多主机', 'Docker'):
            self.assertIn(phrase, text)

    def test_student_flow_is_selected_node_and_spice_auto(self):
        text = (DOCS / 'ctflab-student-distribution-tutorial.md').read_text()
        for phrase in ('顶层', '选中', 'SPICE', '退化', '不静默回退', 'macOS 26.0+', 'TCG'):
            self.assertIn(phrase, text)
        self.assertNotIn('Kali 图形窗口默认使用 Cocoa', text)

    def test_distribution_does_not_install_arbitrary_profile(self):
        text = (DOCS / 'ctflab-distribution-guide.md').read_text()
        self.assertIn('不自动安装任意自定义硬件配置', text)
        self.assertIn('仅有 QCOW2 不构成完整适配', text)
        self.assertIn('子目录', text)

    def test_verification_records_are_dated_snapshots(self):
        records = list(DOCS.glob('verification-*.md'))
        self.assertGreater(len(records), 15)
        for path in records:
            text = path.read_text()
            self.assertIn('历史验收快照', text, path.name)
            self.assertIn('不替代当前软件状态', text, path.name)

    def test_relative_markdown_links_resolve(self):
        for path in [ROOT / 'README.md', *DOCS.glob('*.md')]:
            for target in re.findall(r'(?<!!)\[[^\]]*\]\(([^\s)]+)\)', path.read_text()):
                if ':' in target or target.startswith(('/', '#')):
                    continue
                self.assertTrue((path.parent / target.split('#', 1)[0]).exists(),
                                f'{path.name}: {target}')

    def test_student_cli_variable_examples_parse(self):
        commands = []
        parser = ctflab.build_parser()
        for line in (DOCS / 'ctflab-student-distribution-tutorial.md').read_text().splitlines():
            if line.startswith('"$CLI" '):
                tokens = shlex.split(line)[1:]
                parser.parse_args(tokens)
                commands.append(tokens)
        self.assertGreaterEqual(len(commands), 10)

if __name__ == '__main__':
    unittest.main()
