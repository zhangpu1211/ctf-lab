"""验证来宾模式选择：只应用虚拟输出的合法首选模式。"""
import pathlib
import unittest


class DisplayFollowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = (pathlib.Path(__file__).resolve().parents[1] /
                  'guest_fixes/kali-arm64/configure.sh').read_text()
        source = script.split("<<'PYTHON'\n", 1)[1].split('\nPYTHON', 1)[0]
        cls.namespace = {'__name__': 'display_follow_test'}
        exec(compile(source, 'ctflab-display-follow', 'exec'), cls.namespace)

    def changes(self, text):
        return self.namespace['preferred_changes'](text)

    def test_applies_new_preferred_virtual_mode(self):
        self.assertEqual(self.changes('Virtual-1 connected 1280x800+0+0\n'
                                     '   2000x1400 75.00 +\n'
                                     '   1280x800 60.00*\n'),
                         [('Virtual-1', '2000x1400')])

    def test_current_preferred_mode_is_idempotent(self):
        self.assertEqual(self.changes('Virtual-1 connected\n   1600x1200 75.00*+\n'), [])

    def test_ignores_physical_disconnected_and_unbounded_outputs(self):
        for output, mode in [('HDMI-1 connected', '1920x1080'),
                             ('Virtual-1 disconnected', '1920x1080'),
                             ('Virtual-1 connected', '99999x99999'),
                             ('Virtual-1 connected', 'bad;command')]:
            with self.subTest(output=output, mode=mode):
                self.assertEqual(self.changes(f'{output}\n   {mode} 60.00 +\n'), [])

    def test_does_not_mix_adjacent_outputs(self):
        self.assertEqual(self.changes('Virtual-1 connected\n   800x600 60.00 +\n'
                                     'HDMI-1 connected\n   1920x1080 60.00 +\n'),
                         [('Virtual-1', '800x600')])
