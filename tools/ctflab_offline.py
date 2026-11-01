"""跨平台离线工具统一入口；不导入Mac专用运行器，不提供VM启停。"""
import argparse
import importlib
import sys
from pathlib import Path

if __package__ in (None, ''):
    # Python -I不把脚本目录加入sys.path；固定本文件相邻模块，不依赖工作目录。
    sys.path.insert(0, str(Path(__file__).resolve().parent))

COMMANDS = {
    'scenario-plan': 'ctflab_scenario_v2',
    'course-catalog': 'ctflab_catalog',
    'topology': 'ctflab_topology',
    'evidence-course': 'ctflab_evidence_course',
    'windows-evidence': 'ctflab_windows_evidence',
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in COMMANDS:
        return importlib.import_module(COMMANDS[argv[0]]).main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=sorted(COMMANDS))
    parser.parse_args(argv)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
