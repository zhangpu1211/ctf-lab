#!/usr/bin/env python3
"""用户候选 profile：必须放在状态目录而非 App/源码内置目录。"""

from __future__ import annotations

import argparse
import copy
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402


REPORT = {
    "source_sha256": "a" * 64,
    "candidate": {
        "architecture": "x86_64", "firmware": "bios", "machine": "pc",
        "memory_mb": 1024, "cpus": 1, "disk_bus": "scsi",
        "disk_controller": "lsi53c895a", "network_adapter": "pcnet",
    },
    "confidence": {
        "architecture": {"level": "high", "reason": "test"},
        "firmware": {"level": "high", "reason": "test"},
        "disk": {"level": "high", "reason": "test"},
        "network": {"level": "medium", "reason": "test"},
    },
    "warnings": ["尚未进行冷启动验证"],
}


class UserProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.profile_dir = self.root / "profiles"
        self.manager = ctflab.LabManager(self.root / "state")
        self.env = mock.patch.dict(os.environ, {"CTFLAB_PROFILE_DIR": str(self.profile_dir)})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def args(self, *, profile_id: str = "legacy-box", no_import: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            id=profile_id, source="/input/legacy-box.ova", name="Legacy Box",
            architecture="x86_64", firmware="auto", disk_bus="auto", disk_controller=None,
            network_adapter="auto", memory_mb=None, cpus=None, lab_ip=None, no_import=no_import,
        )

    def test_onboard_writes_candidate_only_to_user_profile_dir(self) -> None:
        with mock.patch.object(ctflab, "inspect_image", return_value=copy.deepcopy(REPORT)), \
             mock.patch.object(self.manager, "import_image", return_value={"base_path": "/derived/base.qcow2"}):
            self.assertEqual(ctflab.cmd_onboard(self.manager, self.args()), 0)

        candidate = self.profile_dir / "legacy-box.yaml"
        self.assertTrue(candidate.is_file())
        self.assertNotEqual(candidate.parent, ctflab.BUILTIN_PROFILE_DIR)
        self.assertIn("legacy-box", ctflab.available_profiles())
        self.assertEqual(ctflab.profile_path("legacy-box"), candidate)
        self.assertEqual(ctflab.load_profile("legacy-box")["guest"]["architecture"], "x86_64")
        self.assertFalse(list(self.profile_dir.glob(".*.yaml")), "发布后不保留临时 profile 文件")

    def test_existing_candidate_is_never_overwritten(self) -> None:
        self.profile_dir.mkdir(parents=True)
        candidate = self.profile_dir / "legacy-box.yaml"
        original = "id: legacy-box\n"
        candidate.write_text(original, encoding="utf-8")
        with self.assertRaises(ctflab.CTFLabError) as raised:
            ctflab.cmd_onboard(self.manager, self.args())
        self.assertIn("已存在", str(raised.exception))
        self.assertEqual(candidate.read_text(encoding="utf-8"), original)

    def test_builtin_profiles_remain_preferred_and_user_collision_is_not_usable(self) -> None:
        self.profile_dir.mkdir(parents=True)
        collision = self.profile_dir / "smoke.yaml"
        collision.write_text("id: smoke\n", encoding="utf-8")
        self.assertEqual(ctflab.profile_path("smoke"), ctflab.BUILTIN_PROFILE_DIR / "smoke.yaml")
        self.assertEqual(ctflab.available_profiles().count("smoke"), 1)

    def test_parser_sees_user_profile_when_environment_is_set_before_start(self) -> None:
        self.profile_dir.mkdir(parents=True)
        profile = ctflab.profile_from_report(
            copy.deepcopy(REPORT), profile_id="legacy-box", name="Legacy Box",
            lab_ip="192.168.242.230", mac="52:54:00:aa:bb:cc")
        import yaml
        (self.profile_dir / "legacy-box.yaml").write_text(
            yaml.safe_dump(profile, allow_unicode=True), encoding="utf-8")
        parsed = ctflab.build_parser().parse_args(["run", "legacy-box"])
        self.assertEqual(parsed.profiles, ["legacy-box"])


if __name__ == "__main__":
    unittest.main()
