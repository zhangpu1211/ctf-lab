#!/usr/bin/env python3
"""目录式内容包（schema 2 分发目录）：格式校验、受控导入、冲突与回滚。

覆盖面：
- 旧 schema 1 分发目录行为不变；`dist install` 只接受内容包；
- 正常导入、重复导入（幂等）、内置/用户同名冲突；
- 非法配置、缺件、哈希/大小不符、未知格式、不兼容版本；
- 路径穿越、目录外引用、不安全符号链接；
- 导入失败/取消后的回滚与并发保护；
- 包内验收声明只作为声明存储，不污染本机验收状态。
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from unittest import mock

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402
import ctflab_dist  # noqa: E402
import ctflab_inspect  # noqa: E402


import hashlib


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fake_run(command, *, capture=True):
    """替身 qemu-img：convert 产出目标文件，其余命令返回 0。"""
    if len(command) > 1 and command[1] == "convert":
        pathlib.Path(command[-1]).write_bytes(b"converted-base")
    return subprocess.CompletedProcess(command, 0, "", "")


VALID_PROFILE = {
    "schema": 1,
    "id": "pack-node",
    "name": "Pack Node",
    "version": "1.0.0",
    "guest": {"architecture": "x86_64", "firmware": "bios", "machine": "pc",
              "memory_mb": 1024, "cpus": 1},
    "disk": {"format": "qcow2", "bus": "ide"},
    "network": {"adapter": "pcnet", "mac": "52:54:00:24:00:77",
                "lab_ip": "192.168.242.77", "segment": "lab", "internet": False,
                "host_forwards": []},
    "readiness": {"timeout_seconds": 90, "checks": ["dhcp"]},
    "verification": {"date": "2026-10-12", "scope": "制作者声明：仅示例",
                     "services": ["示例服务"]},
}


def build_pack(root: pathlib.Path, *, pack_id: str = "sample-pack",
               profile: dict | None = None, base_bytes: bytes = b"pack-base-bytes" * 32,
               nvram_bytes: bytes | None = None, docs: dict[str, bytes] | None = None,
               pack_meta: dict | None = None, requires_runner: str | None = None,
               entries_extra: list[dict] | None = None,
               folder: pathlib.Path | None = None) -> pathlib.Path:
    """手工组装内容包目录（绕过 make_pack 的制作侧校验，便于构造非法样本）。"""
    profile = dict(VALID_PROFILE if profile is None else profile)
    pack_dir = folder or (root / f"{pack_id}-dir")
    pack_dir.mkdir(parents=True, exist_ok=True)
    profile_id = str(profile["id"])
    (pack_dir / f"{profile_id}.yaml").write_bytes(
        ctflab.yaml.safe_dump(profile, allow_unicode=True, sort_keys=False).encode("utf-8"))
    base_name = f"{profile_id}-base.qcow2"
    (pack_dir / base_name).write_bytes(base_bytes)
    entries = [
        {"role": "profile", "profile": profile_id, "file": f"{profile_id}.yaml",
         "size": (pack_dir / f"{profile_id}.yaml").stat().st_size,
         "sha256": ctflab.sha256_file(pack_dir / f"{profile_id}.yaml")},
        {"role": "base", "profile": profile_id, "file": base_name,
         "size": len(base_bytes), "sha256": ctflab.sha256_file(pack_dir / base_name),
         "compression": "none"},
    ]
    if nvram_bytes is not None:
        nvram_name = f"{profile_id}-uefi-vars.fd"
        (pack_dir / nvram_name).write_bytes(nvram_bytes)
        entries.append({"role": "nvram", "profile": profile_id, "file": nvram_name,
                        "size": len(nvram_bytes),
                        "sha256": ctflab.sha256_file(pack_dir / nvram_name),
                        "compression": "none"})
    claims = {}
    if isinstance(profile.get("verification"), dict):
        claims[profile_id] = profile["verification"]
    for name, payload in (docs or {}).items():
        (pack_dir / name).write_bytes(payload)
        entries.append({"role": "doc", "file": name, "size": len(payload),
                        "sha256": sha256_bytes(payload)})
    entries.extend(entries_extra or [])
    manifest = {
        "schema": 2,
        "format": "ctflab-distribution",
        "generated_at": "2026-10-12T00:00:00Z",
        "pack": pack_meta or {"id": pack_id, "name": pack_id, "version": "1.0.0",
                              "requires_runner": requires_runner or ">=0.1.1"},
        "entries": entries,
        **({"claims": claims} if claims else {}),
    }
    (pack_dir / "DISTRIBUTION.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return pack_dir


class PackFormatTests(unittest.TestCase):
    """ctflab_dist 层：解析、路径安全、verify 兼容与扩展。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)

    def test_make_pack_builds_verifiable_directory(self) -> None:
        source_profile = self.root / "pack-node.yaml"
        source_profile.write_bytes(
            ctflab.yaml.safe_dump(VALID_PROFILE, allow_unicode=True).encode("utf-8"))
        base = self.root / "disk.qcow2"
        base.write_bytes(b"base" * 64)
        doc = self.root / "说明.md"
        doc.write_bytes("# 说明".encode("utf-8"))
        result = ctflab_dist.make_pack(self.root / "out", pack_id="my-pack",
                                       profile_yaml=source_profile, base_image=base,
                                       docs=[doc])
        pack_dir = pathlib.Path(result["dir"])
        manifest = ctflab_dist.load_manifest(pack_dir)
        self.assertEqual(manifest["schema"], 2)
        self.assertEqual(manifest["pack"]["id"], "my-pack")
        parsed = ctflab_dist.parse_pack(manifest, runner_version="0.1.1")
        self.assertIn("pack-node", parsed["profiles"])
        self.assertEqual(parsed["claims"]["pack-node"], VALID_PROFILE["verification"])
        report = ctflab_dist.verify_distribution(pack_dir)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["pack"]["nodes"][0]["profile"], "pack-node")
        self.assertIn("ctflab dist install", (pack_dir / "README.md").read_text(encoding="utf-8"))
        sums = (pack_dir / ctflab_dist.SUMS_NAME).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(sums), 3)

    def test_schema1_verify_has_no_pack_section(self) -> None:
        dist_dir = self.root / "dist"
        source = self.root / "base.qcow2"
        source.write_bytes(b"old-style" * 16)
        ctflab_dist.prepare_image_entry(dist_dir, profile_id="smoke", source=source,
                                        qemu_img="qemu-img", compress=False)
        report = ctflab_dist.verify_distribution(dist_dir)
        self.assertTrue(report["ok"])
        self.assertNotIn("pack", report)

    def test_parse_pack_rejects_structural_problems(self) -> None:
        pack_dir = build_pack(self.root)
        manifest = ctflab_dist.load_manifest(pack_dir)

        def rejected(mutate, message_part: str) -> None:
            broken = json.loads(json.dumps(manifest))
            mutate(broken)
            with self.assertRaises(ctflab_dist.DistError) as raised:
                ctflab_dist.parse_pack(broken)
            self.assertIn(message_part, str(raised.exception))

        rejected(lambda m: m.pop("pack"), "缺少 pack 元数据")
        rejected(lambda m: m["pack"].update(id="BAD_ID"), "id 不合法")
        rejected(lambda m: m["pack"].update(version="1.0"), "版本必须形如")
        rejected(lambda m: m["pack"].update(requires_runner="~=1.0"), "requires_runner")
        # 版本约束只在提供当前运行器版本时参与判定
        incompatible = json.loads(json.dumps(manifest))
        incompatible["pack"]["requires_runner"] = ">=99.0.0"
        with self.assertRaises(ctflab_dist.DistError) as raised:
            ctflab_dist.parse_pack(incompatible, runner_version="0.1.1")
        self.assertIn("不满足", str(raised.exception))
        rejected(lambda m: m["entries"].append({"role": "script", "file": "x.sh",
                                                "size": 1, "sha256": "0" * 64}),
                 "不支持的角色")
        rejected(lambda m: m["entries"].append({"role": "doc", "file": "../escape.md",
                                                "size": 1, "sha256": "0" * 64}),
                 "文件名")
        rejected(lambda m: m["entries"].append({"role": "doc", "file": "/etc/passwd",
                                                "size": 1, "sha256": "0" * 64}),
                 "文件名")
        rejected(lambda m: m["entries"].append(dict(m["entries"][1])), "重复登记")
        rejected(lambda m: m["entries"].pop(0), "必须自包含")
        rejected(lambda m: m.update(claims={"ghost": {}}), "claims 引用了包外 profile")
        rejected(lambda m: m["entries"][1].update(size=0), "正整数")

    def test_parse_pack_enforces_runner_version(self) -> None:
        pack_dir = build_pack(self.root, requires_runner=">=99.0.0")
        manifest = ctflab_dist.load_manifest(pack_dir)
        with self.assertRaises(ctflab_dist.DistError) as raised:
            ctflab_dist.parse_pack(manifest, runner_version="0.1.1")
        self.assertIn("99.0.0", str(raised.exception))
        # 满足约束时不报错
        ctflab_dist.parse_pack(manifest, runner_version="99.0.1")

    def test_verify_rejects_symlink_payload(self) -> None:
        outside = self.root / "outside.qcow2"
        outside.write_bytes(b"outside" * 32)
        pack_dir = build_pack(self.root)
        profile_id = VALID_PROFILE["id"]
        base_link = pack_dir / f"{profile_id}-base.qcow2"
        base_link.unlink()
        base_link.symlink_to(outside)
        report = ctflab_dist.verify_distribution(pack_dir)
        self.assertFalse(report["ok"])
        self.assertTrue(any("符号链接" in problem for problem in report["problems"]))

    def test_verify_reports_missing_and_tampered_files(self) -> None:
        pack_dir = build_pack(self.root)
        profile_id = VALID_PROFILE["id"]
        report = ctflab_dist.verify_distribution(pack_dir)
        self.assertTrue(report["ok"])
        (pack_dir / f"{profile_id}-base.qcow2").write_bytes(b"tampered")
        report = ctflab_dist.verify_distribution(pack_dir)
        self.assertFalse(report["ok"])
        self.assertTrue(any("SHA-256 不一致" in p for p in report["problems"]))
        (pack_dir / f"{profile_id}-base.qcow2").unlink()
        report = ctflab_dist.verify_distribution(pack_dir)
        self.assertFalse(report["ok"])
        self.assertTrue(any("文件缺失" in p for p in report["problems"]))

    def test_verify_reports_size_mismatch(self) -> None:
        pack_dir = build_pack(self.root)
        manifest = ctflab_dist.load_manifest(pack_dir)
        manifest["entries"][1]["size"] = manifest["entries"][1]["size"] + 1
        (pack_dir / "DISTRIBUTION.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        report = ctflab_dist.verify_distribution(pack_dir)
        self.assertFalse(report["ok"])
        self.assertTrue(any("大小不一致" in p for p in report["problems"]))

    def test_verify_unknown_manifest_format_is_rejected(self) -> None:
        pack_dir = build_pack(self.root)
        manifest = ctflab_dist.load_manifest(pack_dir)
        manifest["format"] = "other-format"
        (pack_dir / "DISTRIBUTION.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ctflab_dist.DistError):
            ctflab_dist.verify_distribution(pack_dir)

    def test_verify_pack_summary_carries_conflicts(self) -> None:
        pack_dir = build_pack(self.root, docs={"使用说明.md": "# 说明".encode("utf-8")})

        def status(profile_id: str) -> dict:
            if profile_id == "builtin-id":
                return {"kind": "builtin", "sha256": "a" * 64}
            if profile_id == VALID_PROFILE["id"]:
                return {"kind": "user", "sha256": "b" * 64}
            return {"kind": "absent", "sha256": None}

        report = ctflab_dist.verify_distribution(pack_dir, profile_status=status)
        node = report["pack"]["nodes"][0]
        self.assertEqual(node["local"]["kind"], "user")
        self.assertEqual(report["pack"]["docs"], ["使用说明.md"])
        self.assertIn("仅供参考", report["pack"]["claims_note"])

    def test_make_pack_refuses_nonempty_target_and_bad_names(self) -> None:
        source_profile = self.root / "pack-node.yaml"
        source_profile.write_bytes(
            ctflab.yaml.safe_dump(VALID_PROFILE, allow_unicode=True).encode("utf-8"))
        base = self.root / "disk.qcow2"
        base.write_bytes(b"base")
        target = self.root / "out"
        target.mkdir()
        (target / "existing.txt").write_text("keep")
        with self.assertRaises(ctflab_dist.DistError):
            ctflab_dist.make_pack(target, pack_id="my-pack", profile_yaml=source_profile,
                                  base_image=base)
        with self.assertRaises(ctflab_dist.DistError):
            ctflab_dist.make_pack(self.root / "out2", pack_id="BAD", profile_yaml=source_profile,
                                  base_image=base)


class PackInstallTests(unittest.TestCase):
    """manager.install_content_pack：导入事务、冲突、回滚与声明隔离。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.manager = ctflab.LabManager(self.root / "state")
        self.profile_dir = self.root / "profiles"
        self.env = mock.patch.dict(os.environ, {"CTFLAB_PROFILE_DIR": str(self.profile_dir)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.patches = [
            mock.patch.object(ctflab, "qemu_img_path", return_value="/usr/bin/qemu-img"),
            mock.patch.object(ctflab, "qemu_info",
                              return_value={"format": "qcow2", "virtual-size": 1024}),
            mock.patch.object(ctflab, "run_command", side_effect=fake_run),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.pack_dir = build_pack(self.root, docs={"使用说明.md": "# 说明".encode("utf-8")})
        self.profile_id = VALID_PROFILE["id"]

    def _install(self, pack_dir: pathlib.Path | None = None) -> dict:
        return self.manager.install_content_pack(pack_dir or self.pack_dir)

    def test_install_happy_path_registers_pack_and_claims(self) -> None:
        result = self._install()
        self.assertEqual(result["installed"], [self.profile_id])
        self.assertEqual(result["imported"], [self.profile_id])
        yaml_path = self.profile_dir / f"{self.profile_id}.yaml"
        self.assertTrue(yaml_path.is_file())
        self.assertFalse(yaml_path.is_symlink())
        state = self.manager.image_state(self.profile_id)
        self.assertIsNotNone(state)
        self.assertEqual(state["source_verification"]["method"], "content-pack-manifest")
        self.assertEqual(state["content_pack"]["id"], "sample-pack")
        # 声明隔离：claims 只作为声明存储；没有任何“已验证”标记。
        self.assertEqual(state["claims_from_pack"]["manifest"], VALID_PROFILE["verification"])
        self.assertNotIn("verification_status", state)
        docs = self.manager.content_packs_dir / "sample-pack" / "docs" / "使用说明.md"
        self.assertTrue(docs.is_file())
        record = ctflab.read_json(self.manager.content_packs_dir / "sample-pack" / "pack.json")
        self.assertEqual(record["installed_profiles"], [self.profile_id])
        self.assertEqual(record["claims"], {"pack-node": VALID_PROFILE["verification"]})
        status = ctflab._status_report(self.manager)
        entry = next(p for p in status["profiles"] if p["id"] == self.profile_id)
        self.assertEqual(entry["content_pack"]["id"], "sample-pack")
        self.assertTrue(entry["has_pack_claims"])
        self.assertNotIn("verified", json.dumps(entry).lower().replace("has_pack_claims", ""))

    def test_install_with_nvram_attaches_template(self) -> None:
        pack_dir = build_pack(self.root, nvram_bytes=b"nvram-template" * 16, pack_id="nv-pack")
        result = self._install(pack_dir)
        self.assertEqual(result["imported"], [self.profile_id])
        state = self.manager.image_state(self.profile_id)
        # 登记的是状态目录内的模板副本，不再指向原包内部路径。
        registered = pathlib.Path(state["uefi_vars_path"])
        self.assertTrue(str(registered).startswith(str(self.manager.images_dir)),
                        "NVRAM 副本必须位于状态目录内")
        self.assertEqual(state["uefi_vars_sha256"], ctflab.sha256_file(registered))
        self.assertNotIn(str(pack_dir), str(registered))

    def test_reinstall_is_idempotent(self) -> None:
        first = self._install()
        base_before = self.manager.image_state(self.profile_id)["base_sha256"]
        second = self._install()
        self.assertEqual(second["skipped_identical"], [self.profile_id])
        self.assertEqual(second["imported"], [self.profile_id])
        self.assertEqual(self.manager.image_state(self.profile_id)["base_sha256"], base_before)
        docs = list((self.manager.content_packs_dir / "sample-pack" / "docs").iterdir())
        self.assertEqual(len(docs), 1, "重复导入不得堆叠说明文件副本")
        self.assertEqual(first["record"], second["record"])

    def test_builtin_id_conflict_is_refused(self) -> None:
        profile = dict(VALID_PROFILE, id="smoke")
        pack_dir = build_pack(self.root, profile=profile, pack_id="builtin-pack")
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self._install(pack_dir)
        self.assertIn("内置", str(raised.exception))
        self.assertFalse((self.profile_dir / "smoke.yaml").exists())

    def test_user_conflict_different_content_is_refused_without_overwrite(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        existing = self.profile_dir / f"{self.profile_id}.yaml"
        existing.write_text("schema: 1\nid: other\n", encoding="utf-8")
        before = existing.read_bytes()
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self._install()
        message = str(raised.exception)
        self.assertIn("默认不覆盖", message)
        self.assertIn("sha256", message)
        self.assertEqual(existing.read_bytes(), before)
        self.assertIsNone(self.manager.image_state(self.profile_id))

    def test_identical_user_profile_is_skipped_not_overwritten(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        existing = self.profile_dir / f"{self.profile_id}.yaml"
        payload = pathlib.Path(self.pack_dir / f"{self.profile_id}.yaml").read_bytes()
        existing.write_bytes(payload)
        result = self._install()
        self.assertEqual(result["skipped_identical"], [self.profile_id])
        self.assertEqual(existing.read_bytes(), payload)
        self.assertIsNotNone(self.manager.image_state(self.profile_id))

    def test_invalid_profile_variants_are_refused_before_any_write(self) -> None:
        variants = [
            ("联网声明", dict(VALID_PROFILE, network=dict(VALID_PROFILE["network"], internet=True))),
            ("非 lab 网段", dict(VALID_PROFILE, network=dict(VALID_PROFILE["network"], segment="home"))),
            ("未知顶层字段", dict(VALID_PROFILE, qemu_extra={"-usb": True})),
            ("未知网卡", dict(VALID_PROFILE, network=dict(VALID_PROFILE["network"], adapter="vmxnet3"))),
            ("坏端口映射", dict(VALID_PROFILE, network=dict(
                VALID_PROFILE["network"], host_forwards=[{"name": "x", "guest_port": 22, "host_port": "abc"}]))),
            ("越界资源", dict(VALID_PROFILE, guest=dict(VALID_PROFILE["guest"], memory_mb=16))),
        ]
        for label, profile in variants:
            with self.subTest(variant=label):
                pack_dir = build_pack(self.root, profile=profile, pack_id=f"invalid-{abs(hash(label))}")
                before = set(p.name for p in self.profile_dir.glob("*")) if self.profile_dir.exists() else set()
                with self.assertRaises(ctflab.CTFLabError):
                    self._install(pack_dir)
                after = set(p.name for p in self.profile_dir.glob("*")) if self.profile_dir.exists() else set()
                self.assertEqual(before, after, f"{label}：拒绝导入时不得写入配置")
                self.assertIsNone(self.manager.image_state(str(profile["id"])) or None)

    def test_missing_base_file_blocks_everything(self) -> None:
        profile_id = VALID_PROFILE["id"]
        (self.pack_dir / f"{profile_id}-base.qcow2").unlink()
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self._install()
        self.assertIn("未做任何导入", str(raised.exception))
        self.assertFalse(self.profile_dir.exists())
        self.assertIsNone(self.manager.image_state(self.profile_id))

    def test_hash_mismatch_blocks_install(self) -> None:
        profile_id = VALID_PROFILE["id"]
        (self.pack_dir / f"{profile_id}-base.qcow2").write_bytes(b"tampered" * 8)
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self._install()
        self.assertIn("未做任何导入", str(raised.exception))
        self.assertFalse(self.profile_dir.exists())

    def test_incompatible_runner_blocks_install(self) -> None:
        pack_dir = build_pack(self.root, requires_runner=">=99.0.0")
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self._install(pack_dir)
        self.assertIn("99.0.0", str(raised.exception))

    def test_schema1_distribution_is_not_a_content_pack(self) -> None:
        dist_dir = self.root / "dist"
        source = self.root / "base.qcow2"
        source.write_bytes(b"old" * 16)
        ctflab_dist.prepare_image_entry(dist_dir, profile_id="smoke", source=source,
                                        qemu_img="qemu-img", compress=False)
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self.manager.install_content_pack(dist_dir)
        self.assertIn("pack", str(raised.exception))

    def test_import_failure_rolls_back_this_run_and_keeps_pack(self) -> None:
        """配置已装、导入失败：回滚配置/说明/记录；原包完整；修复后可重试。"""
        with mock.patch.object(ctflab, "run_command",
                               side_effect=ctflab.CTFLabError("转换失败：模拟磁盘满")):
            with self.assertRaises(ctflab.CTFLabError):
                self._install()
        # 回滚断言
        self.assertFalse((self.profile_dir / f"{self.profile_id}.yaml").exists(),
                         "导入失败后不得留下半安装配置")
        self.assertFalse((self.manager.content_packs_dir / "sample-pack" / "docs").exists())
        self.assertFalse((self.manager.content_packs_dir / "sample-pack" / "pack.json").exists())
        self.assertIsNone(self.manager.image_state(self.profile_id))
        # 原包完整：校验仍通过，文件未被修改
        report = ctflab_dist.verify_distribution(self.pack_dir)
        self.assertTrue(report["ok"])
        # 修复（换成正常替身）后重试成功
        result = self._install()
        self.assertEqual(result["imported"], [self.profile_id])

    def test_cancelled_import_rolls_back_like_failure(self) -> None:
        cancel_file = self.root / "cancel"
        cancel_file.write_text("cancel", encoding="utf-8")
        with ctflab_inspect.import_session(cancel_file):
            with self.assertRaises(ctflab_inspect.InspectionError):
                self._install()
        self.assertFalse((self.profile_dir / f"{self.profile_id}.yaml").exists())
        self.assertFalse((self.manager.content_packs_dir / "sample-pack" / "pack.json").exists())
        self.assertIsNone(self.manager.image_state(self.profile_id))

    def test_corrupted_nvram_reinstall_preserves_original_registration(self) -> None:
        """NVRAM 提交边界：重装时模板校验/复制失败不得把原登记改回包内路径。

        场景：ARM 包首次安装成功（登记指向状态目录模板副本 A）；重装同 ID 包
        （同配置、同基盘、自洽但模板不同的 NVRAM），但复制阶段失败（如磁盘满/
        IO 错误）。修复后：原登记必须仍指向副本 A，绝不残留包内路径或指向新
        模板；本轮复制出的新模板副本被回滚；既有包记录不受影响。
        """
        if ctflab.find_firmware("edk2-aarch64-code.fd") is None:
            self.skipTest("本机缺少 aarch64 UEFI 固件代码")
        arm = dict(VALID_PROFILE, id="pack-arm",
                   guest=dict(VALID_PROFILE["guest"], architecture="aarch64",
                              firmware="uefi", machine="virt"),
                   disk=dict(VALID_PROFILE["disk"], bus="virtio", controller=None),
                   network=dict(VALID_PROFILE["network"], adapter="virtio-net-pci",
                                mac="52:54:00:24:00:82", lab_ip="192.168.242.82"))
        first_pack = build_pack(self.root, profile=arm, pack_id="arm-pack",
                                nvram_bytes=b"original-vars" * 32)
        self._install(first_pack)
        state = self.manager.image_state("pack-arm")
        original_vars_path = state["uefi_vars_path"]
        original_vars_sha = state["uefi_vars_sha256"]
        self.assertTrue(str(original_vars_path).startswith(str(self.manager.images_dir)))
        self.assertNotIn(str(first_pack), str(original_vars_path))
        incoming_base_sha = ctflab.sha256_file(first_pack / "pack-arm-base.qcow2")

        # 重装包：同 pack id、同配置、同基盘字节 → 全部校验通过，最后在 NVRAM
        # 复制阶段注入 IO 失败（这正是"复制失败"的事务边界）。
        incoming = build_pack(self.root, profile=arm, pack_id="arm-pack",
                              folder=self.root / "arm-pack-incoming",
                              nvram_bytes=b"different-template" * 32,
                              base_bytes=b"pack-base-bytes" * 32)
        self.assertEqual(ctflab.sha256_file(incoming / "pack-arm-base.qcow2"), incoming_base_sha,
                         "重装包基盘应与首轮字节一致，保证失败只发生在 NVRAM 复制")
        real_copy2 = shutil.copy2

        def failing_nvram_copy(source, target, **kwargs):
            if "uefi-vars" in str(target):
                raise OSError("模拟磁盘满： 无法写入 NVRAM 模板")
            return real_copy2(source, target, **kwargs)

        with mock.patch.object(ctflab.shutil, "copy2", side_effect=failing_nvram_copy):
            with self.assertRaises(ctflab.CTFLabError) as raised:
                self._install(incoming)
        self.assertIn("NVRAM", str(raised.exception))

        # 原登记保留：仍指向首次安装的状态副本 A；包内路径与新模板都不得出现。
        after = self.manager.image_state("pack-arm")
        self.assertEqual(after["uefi_vars_path"], original_vars_path,
                         "重装复制失败后原 NVRAM 登记不得被改回包内路径或新副本")
        self.assertEqual(after["uefi_vars_sha256"], original_vars_sha)
        self.assertFalse(str(after["uefi_vars_path"]).startswith(str(incoming)))
        # 原副本文件完好；本轮复制的新模板副本已被回滚。
        self.assertTrue(pathlib.Path(original_vars_path).is_file())
        rolled = self.manager.images_dir / "pack-arm" / "uefi-vars-{}.fd".format(
            ctflab.sha256_file(incoming / "pack-arm-uefi-vars.fd")[:12])
        self.assertFalse(rolled.exists(), "失败重装复制的新模板不得残留")
        # 既有包记录与节点元数据不受影响。
        record = ctflab.read_json(self.manager.content_packs_dir / "arm-pack" / "pack.json")
        self.assertEqual(record["imported_profiles"], ["pack-arm"])

    def test_install_rejects_pack_node_without_base(self) -> None:
        """只有 profile 没有 base 的节点：安装期明确拒绝，不留配置。"""
        pack_dir = build_pack(self.root)
        manifest = json.loads((pack_dir / "DISTRIBUTION.json").read_text(encoding="utf-8"))
        manifest["entries"] = [e for e in manifest["entries"] if e.get("role") != "base"]
        (pack_dir / "DISTRIBUTION.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                                    encoding="utf-8")
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self._install(pack_dir)
        self.assertIn("缺少 base", str(raised.exception))
        self.assertFalse((self.profile_dir / f"{self.profile_id}.yaml").exists())

    def test_partially_installed_nodes_are_kept_on_later_failure(self) -> None:
        """多节点包前一个节点成功、后一个失败：成功节点如实保留并上报。"""
        second = dict(VALID_PROFILE, id="pack-node-2",
                      network=dict(VALID_PROFILE["network"], mac="52:54:00:24:00:78",
                                   lab_ip="192.168.242.78"))
        pack_dir = build_pack(self.root, profile=second, pack_id="multi-pack")
        # 主包先成功导入；再装 multi-pack 时第二个节点的转换失败。
        self._install()

        def failing_second(command, *, capture=True):
            if len(command) > 1 and command[1] == "convert" and "pack-node-2" in command[-1]:
                raise ctflab.CTFLabError("第二个节点转换失败")
            return fake_run(command, capture=capture)

        with mock.patch.object(ctflab, "run_command", side_effect=failing_second):
            with self.assertRaises(ctflab.CTFLabError) as raised:
                self._install(pack_dir)
        self.assertIn("pack-node-2", str(raised.exception))
        # 已成功的 pack-node 保持完整，不受回滚影响。
        self.assertIsNotNone(self.manager.image_state("pack-node"))
        self.assertTrue((self.profile_dir / "pack-node.yaml").exists())
        self.assertIsNone(self.manager.image_state("pack-node-2"))
        self.assertFalse((self.profile_dir / "pack-node-2.yaml").exists())

    def test_same_pack_partial_failure_keeps_committed_node_intact(self) -> None:
        """同一个包内第一节点真实导入成功、第二节点导入失败：第一节点配置/基盘/登记完整。"""
        second = dict(VALID_PROFILE, id="pack-second",
                      network=dict(VALID_PROFILE["network"], mac="52:54:00:24:00:79",
                                   lab_ip="192.168.242.79"))
        pack_dir = build_pack(self.root, pack_id="same-pack")
        # 追加第二节点：配置 + 坏 OVA 基盘（清单哈希与其字节一致，能通过整体校验，
        # 在导入阶段才失败——这正是独立复核 P1 的场景；.ova 后缀触发真实解析）。
        second_yaml = pack_dir / "pack-second.yaml"
        second_yaml.write_text(
            ctflab.yaml.safe_dump(second, allow_unicode=True, sort_keys=False), encoding="utf-8")
        bad_ova = pack_dir / "pack-second.ova"
        bad_ova.write_bytes(b"not-a-tar-archive")
        manifest = json.loads((pack_dir / "DISTRIBUTION.json").read_text(encoding="utf-8"))
        manifest["entries"] += [
            {"role": "profile", "profile": "pack-second", "file": second_yaml.name,
             "size": second_yaml.stat().st_size, "sha256": ctflab.sha256_file(second_yaml)},
            {"role": "base", "profile": "pack-second", "file": bad_ova.name,
             "size": bad_ova.stat().st_size, "sha256": ctflab.sha256_file(bad_ova),
             "compression": "none"},
        ]
        (pack_dir / "DISTRIBUTION.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                                    encoding="utf-8")
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self._install(pack_dir)
        message = str(raised.exception)
        self.assertIn("pack-second", message)
        # 已提交的第一节点：YAML 必须保留且可加载，基盘与登记完整。
        self.assertTrue((self.profile_dir / f"{self.profile_id}.yaml").is_file(),
                        "同包已提交节点的配置不得被回滚删除")
        ctflab.load_profile(self.profile_id)
        state = self.manager.image_state(self.profile_id)
        self.assertIsNotNone(state)
        self.assertTrue(pathlib.Path(state["base_path"]).is_file())
        # 未提交的第二节点：不留半安装配置。
        self.assertFalse((self.profile_dir / "pack-second.yaml").exists())
        self.assertIsNone(self.manager.image_state("pack-second"))
        self.assertIn("保留", message)

    def test_failed_reinstall_preserves_record_and_metadata(self) -> None:
        """重装同 ID 包（说明不同）失败：旧包记录保留，既有节点元数据不被提前改写。"""
        self._install()
        record_path = self.manager.content_packs_dir / "sample-pack" / "pack.json"
        record_before = record_path.read_bytes()
        image_before = self.manager.image_state(self.profile_id)["content_pack"]
        # 同 pack id、同配置、同基盘、不同说明 → 说明冲突预检必须最先拒绝。
        # 注意放在独立目录，避免覆盖原包目录里的同名文件。
        changed = build_pack(self.root, pack_id="sample-pack",
                             folder=self.root / "sample-pack-changed",
                             docs={"使用说明.md": b"# changed doc"})
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self._install(changed)
        self.assertIn("说明文件", str(raised.exception))
        self.assertEqual(record_path.read_bytes(), record_before,
                         "失败重装不得删除或改写既有包记录")
        self.assertEqual(self.manager.image_state(self.profile_id)["content_pack"], image_before,
                         "失败重装不得提前改写既有节点的登记元数据")
        # 恢复一致内容后重试仍然成功。
        result = self._install()
        self.assertEqual(result["skipped_identical"], [self.profile_id])

    def test_nvram_template_is_copied_into_state_and_survives_pack_move(self) -> None:
        """ARM 包导入后登记状态目录内的 NVRAM 副本；原包移走后 ensure_uefi_vars 仍可用。"""
        if ctflab.find_firmware("edk2-aarch64-code.fd") is None:
            self.skipTest("本机缺少 aarch64 UEFI 固件代码")
        arm = dict(VALID_PROFILE, id="pack-arm",
                   guest=dict(VALID_PROFILE["guest"], architecture="aarch64",
                              firmware="uefi", machine="virt"),
                   disk=dict(VALID_PROFILE["disk"], bus="virtio", controller=None),
                   network=dict(VALID_PROFILE["network"], adapter="virtio-net-pci",
                                mac="52:54:00:24:00:81", lab_ip="192.168.242.81"))
        pack_dir = build_pack(self.root, profile=arm, pack_id="arm-pack",
                              nvram_bytes=b"arm-vars-template" * 32)
        self._install(pack_dir)
        state = self.manager.image_state("pack-arm")
        registered = pathlib.Path(state["uefi_vars_path"])
        self.assertTrue(str(registered).startswith(str(self.manager.images_dir)),
                        "登记的 NVRAM 模板必须位于状态目录内")
        self.assertEqual(state["uefi_vars_sha256"], ctflab.sha256_file(registered))
        retained = self.root / "retained-arm-pack"
        pack_dir.rename(retained)
        code_path, runtime_vars = self.manager.ensure_uefi_vars("pack-arm")
        self.assertTrue(code_path.is_file())
        self.assertTrue(runtime_vars.is_file(), "移包后必须仍能取得 NVRAM 模板副本")

    def test_http_path_host_escape_is_rejected(self) -> None:
        """readiness HTTP path 不允许把探测指向 @host 等外部目标（校验层与构造层）。"""
        escape = dict(VALID_PROFILE, readiness={
            "timeout_seconds": 30,
            "checks": [{"type": "http", "port": 80, "path": "@example.invalid/"}]})
        with self.assertRaises(ctflab.CTFLabError):
            ctflab.validate_pack_profile(escape, pathlib.Path("review.yaml"))
        with self.assertRaises(ctflab.CTFLabError):
            ctflab.validate_profile(escape, pathlib.Path("review.yaml"))
        with self.assertRaises(ctflab.CTFLabError):
            ctflab.http_probe_url(12345, "@example.invalid/")
        for bad in ("http://evil.example/", "/a b", "/x@y", "../escape"):
            with self.subTest(bad_path=bad):
                with self.assertRaises(ctflab.CTFLabError):
                    ctflab.http_probe_url(12345, bad)
        # 查询串不改变目标主机，属于合法站内路径。
        self.assertEqual(ctflab.http_probe_url(12345, "/health?probe=1"),
                         "http://127.0.0.1:12345/health?probe=1")
        self.assertEqual(ctflab.http_probe_url(12345, "/status"),
                         "http://127.0.0.1:12345/status")
        # 执行器不跟随重定向离开回环目标。
        handler = ctflab._LoopbackRedirectBlocker()
        with self.assertRaises(urllib.error.URLError):
            handler.redirect_request(None, None, 302, "found",
                                     {}, "http://evil.example/next")

    def test_lab_ip_must_stay_in_lab_subnet(self) -> None:
        """内容包 lab_ip 必须位于声明实验网段 192.168.242.0/24。"""
        outside = dict(VALID_PROFILE, network=dict(VALID_PROFILE["network"], lab_ip="10.42.0.5"))
        with self.assertRaises(ctflab.CTFLabError) as raised:
            ctflab.validate_pack_profile(outside, pathlib.Path("review.yaml"))
        self.assertIn("192.168.242.0/24", str(raised.exception))
        inside = dict(VALID_PROFILE, network=dict(VALID_PROFILE["network"], lab_ip="192.168.242.90"))
        ctflab.validate_pack_profile(inside, pathlib.Path("review.yaml"))
        with self.assertRaises(ctflab.CTFLabError):
            ctflab.validate_pack_profile(
                dict(VALID_PROFILE, network=dict(VALID_PROFILE["network"], lab_ip="not-an-ip")),
                pathlib.Path("review.yaml"))

    def test_concurrent_installs_serialize_on_operation_lock(self) -> None:
        results: list[dict | Exception] = []

        def worker() -> None:
            manager = ctflab.LabManager(self.root / "state")
            try:
                results.append(manager.install_content_pack(self.pack_dir))
            except Exception as error:  # noqa: BLE001
                results.append(error)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        successes = [item for item in results if isinstance(item, dict)]
        self.assertEqual(len(results), 2)
        self.assertTrue(successes, "两个安装都失败说明锁死或互斥过度")
        # 最终状态一致：一份配置、一份登记、一份包记录。
        yaml_count = len(list(self.profile_dir.glob(f"{self.profile_id}.yaml")))
        self.assertEqual(yaml_count, 1)
        state = self.manager.image_state(self.profile_id)
        self.assertIsNotNone(state)
        self.assertTrue((self.manager.content_packs_dir / "sample-pack" / "pack.json").is_file())


if __name__ == "__main__":
    unittest.main()
