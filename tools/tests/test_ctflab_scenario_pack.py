"""schema 3 场景内容包合成验证：制作/校验/安装全链路与交叉校验负测。

全部使用字节级合成基盘与 vars 模板；不启动 VM、不触碰真实镜像、网络或用户状态。
"""
import contextlib
import hashlib
import io
import json
import pathlib
import tempfile
import unittest

import test_ctflab_scenario as scenario_fixture
import ctflab
import ctflab_dist

CAPS = scenario_fixture.CAPS


def run_cli(*argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = ctflab.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


class ScenarioPackTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="spp-")
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.manifest = self.build_manifest()
        self.manifest_path = self.root / "wintermute.json"
        self.manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")
        self.vars_path = self.root / "vars.fd"
        self.vars_path.write_bytes(b"synthetic-uefi-vars")
        self.doc_path = self.root / "说明.md"
        self.doc_path.write_text("# 合成说明", encoding="utf-8")

    def build_manifest(self) -> dict:
        manifest = scenario_fixture.candidate()
        for key in manifest["assets"]:
            path = self.root / f"{key}-base.qcow2"
            path.write_bytes(("scenario-pack-base-" + key).encode())
            manifest["assets"][key]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return manifest

    def base_paths(self) -> dict[str, pathlib.Path]:
        return {key: self.root / f"{key}-base.qcow2" for key in self.manifest["assets"]}

    def make_pack(self, out=None, **overrides):
        kwargs = dict(pack_id="wintermute-lab", scenario_manifest=self.manifest_path,
                      bases=self.base_paths(), firmware_vars={"kali": self.vars_path},
                      docs=[self.doc_path])
        kwargs.update(overrides)
        return ctflab_dist.make_scenario_pack(out or self.root / "pack", **kwargs)

    def test_make_and_verify_roundtrip(self):
        result = self.make_pack()
        entries = {entry["file"]: entry["role"] for entry in result["entries"]}
        self.assertEqual(entries["wintermute.json"], "scenario-manifest")
        self.assertEqual(sorted(name for name, role in entries.items() if role == "scenario-base"),
                         ["kali-base.qcow2", "neuromancer-base.qcow2", "straylight-base.qcow2"])
        report = ctflab_dist.verify_distribution(self.root / "pack", runner_version="0.1.2")
        self.assertTrue(report["ok"], report["problems"])
        summary = report["pack"]
        self.assertEqual(summary["scenario"]["id"], "wintermute")
        self.assertTrue(all(asset["shipped"] for asset in summary["scenario"]["assets"]))
        self.assertEqual(summary["scenario"]["firmware_vars"],
                         [{"node": "kali", "file": "kali-uefi-vars.fd"}])
        self.assertEqual(summary["nodes"], [])  # 场景包没有单机 profile 节点
        self.assertEqual(summary["docs"], ["说明.md"])
        readme = (self.root / "pack" / "README.md").read_text(encoding="utf-8")
        self.assertIn("scenario prepare", readme)

    def test_make_rejects_base_hash_mismatch(self):
        tampered = json.loads(json.dumps(self.manifest))
        tampered["assets"]["straylight"]["sha256"] = "b" * 64
        manifest_path = self.root / "tampered.json"
        manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(ctflab_dist.DistError) as raised:
            self.make_pack(scenario_manifest=manifest_path)
        self.assertIn("SHA-256 不一致", str(raised.exception))

    def test_make_rejects_unknown_asset_and_non_uefi_node(self):
        with self.assertRaises(ctflab_dist.DistError) as raised:
            self.make_pack(bases={**self.base_paths(), "ghost": self.root / "ghost.qcow2"})
        self.assertIn("清单外资产", str(raised.exception))
        with self.assertRaises(ctflab_dist.DistError) as raised:
            self.make_pack(firmware_vars={"straylight": self.vars_path})
        self.assertIn("UEFI 节点", str(raised.exception))

    def test_reference_only_pack_marks_missing_assets(self):
        self.make_pack(bases={})
        report = ctflab_dist.verify_distribution(self.root / "pack")
        self.assertTrue(report["ok"], report["problems"])
        assets = {asset["asset"]: asset["shipped"]
                  for asset in report["pack"]["scenario"]["assets"]}
        self.assertEqual(assets, {"kali": False, "neuromancer": False, "straylight": False})
        readme = (self.root / "pack" / "README.md").read_text(encoding="utf-8")
        self.assertIn("未随包资产", readme)

    def test_verify_detects_tampered_and_missing_payload(self):
        self.make_pack()
        pack_dir = self.root / "pack"
        (pack_dir / "kali-base.qcow2").write_bytes(b"tampered")
        report = ctflab_dist.verify_distribution(pack_dir)
        self.assertFalse(report["ok"])
        self.assertTrue(any("SHA-256 不一致" in problem for problem in report["problems"]))
        (pack_dir / "kali-base.qcow2").unlink()
        report = ctflab_dist.verify_distribution(pack_dir)
        self.assertFalse(report["ok"])
        self.assertTrue(any("文件缺失" in problem for problem in report["problems"]))

    def test_parse_cross_checks_against_scenario_manifest(self):
        self.make_pack()
        pack_dir = self.root / "pack"
        manifest = ctflab_dist.load_manifest(pack_dir)
        # 直接解析层：登记哈希与场景清单声明不一致必须拒绝（文件本体是否吻合另由 verify 实测）。
        mutated = json.loads(json.dumps(manifest))
        for entry in mutated["entries"]:
            if entry.get("role") == "scenario-base" and entry.get("asset") == "kali":
                entry["sha256"] = "a" * 64
        with self.assertRaises(ctflab_dist.DistError) as raised:
            ctflab_dist.parse_scenario_pack(pack_dir, mutated)
        self.assertIn("SHA-256 不一致", str(raised.exception))
        # 场景清单条目缺失 / 角色混用 / 重复资产 / 声明越界。
        def rejected(mutate, fragment):
            mutated = json.loads(json.dumps(manifest))
            mutate(mutated)
            with self.assertRaises(ctflab_dist.DistError) as raised:
                ctflab_dist.parse_scenario_pack(pack_dir, mutated)
            self.assertIn(fragment, str(raised.exception))
        rejected(lambda m: m["entries"].pop(next(index for index, entry in enumerate(m["entries"])
                                                if entry["role"] == "scenario-manifest")),
                 "缺少 scenario-manifest")
        rejected(lambda m: m["entries"].append({"role": "profile", "file": "x.yaml", "size": 1,
                                                "sha256": "0" * 64, "profile": "x"}),
                 "不支持的角色")
        rejected(lambda m: m["pack"]["scenario"].update(manifest="nested/wintermute.json"),
                 "不能包含路径")
        rejected(lambda m: m["pack"].update(scenario={"id": "other", "manifest": "wintermute.json"}),
                 "scenario_id 与 pack.scenario.id 不一致")
        rejected(lambda m: m.update(claims={"other-scenario": {}}), "包外场景")
        with self.assertRaises(ctflab_dist.DistError) as raised:
            ctflab_dist.parse_scenario_pack(pack_dir, json.loads(json.dumps(
                {**manifest, "pack": {**manifest["pack"], "requires_runner": ">=99.0.0"}})),
                runner_version="0.1.1")
        self.assertIn("不满足", str(raised.exception))

    def test_cli_make_verify_install_end_to_end(self):
        out = self.root / "cli-pack"
        code, output, errors = run_cli(
            "dist", "make-scenario-pack", "--out", str(out), "--pack-id", "wintermute-lab",
            "--manifest", str(self.manifest_path),
            *[item for key, path in self.base_paths().items() for item in ("--asset", f"{key}={path}")],
            "--firmware-vars", f"kali={self.vars_path}", "--doc", str(self.doc_path))
        self.assertEqual(code, 0, errors)
        self.assertIn("场景内容包已生成", output)
        code, output, errors = run_cli("dist", "verify", "--dir", str(out), "--json")
        self.assertEqual(code, 0, errors)
        report = json.loads(output)
        self.assertTrue(report["ok"])
        self.assertEqual(report["pack"]["scenario"]["id"], "wintermute")
        state = self.root / "state"
        code, output, errors = run_cli("--state-dir", str(state), "dist", "install",
                                       "--dir", str(out), "--json")
        self.assertEqual(code, 0, errors)
        result = json.loads(output)
        scenario = result["scenario"]
        self.assertEqual(sorted(scenario["files"]),
                         ["asset:kali", "asset:neuromancer", "asset:straylight",
                          "manifest", "vars:kali"])
        for path in scenario["files"].values():
            self.assertTrue(pathlib.Path(path).is_file(), path)
        record = json.loads((state / "content-packs" / "wintermute-lab" / "pack.json").read_text())
        self.assertEqual(record["schema"], 3)
        command = scenario["prepare_command"]
        self.assertIn("scenario prepare", command)
        self.assertIn(f"--manifest {scenario['files']['manifest']}", command)
        self.assertIn(f"--asset kali={scenario['files']['asset:kali']}", command)
        self.assertIn(f"--firmware kali=<kali 的 edk2 code 固件路径>,{scenario['files']['vars:kali']}", command)
        self.assertEqual(scenario["missing_assets"], [])
        # 幂等重装：内容一致直接成功。
        code, output, errors = run_cli("--state-dir", str(state), "dist", "install",
                                       "--dir", str(out), "--json")
        self.assertEqual(code, 0, errors)

    def test_install_refuses_conflicting_and_tampered_pack(self):
        out = self.root / "pack"
        self.make_pack(out=out)
        state = self.root / "state"
        code, output, errors = run_cli("--state-dir", str(state), "dist", "install", "--dir", str(out))
        self.assertEqual(code, 0, errors)
        # 篡改包内基盘后重装：整体校验先行拒绝，状态目录不变。
        installed = state / "content-packs" / "wintermute-lab" / "scenario" / "kali-base.qcow2"
        (out / "kali-base.qcow2").write_bytes(b"tampered")
        code, output, errors = run_cli("--state-dir", str(state), "dist", "install", "--dir", str(out))
        self.assertEqual(code, 2)
        self.assertIn("校验失败", errors)
        # 状态目录内同名文件被外部改动后重装：拒绝覆盖。
        (out / "kali-base.qcow2").write_bytes((self.root / "kali-base.qcow2").read_bytes())
        installed.chmod(0o644)
        installed.write_bytes(b"conflict")
        installed.chmod(0o444)
        code, output, errors = run_cli("--state-dir", str(state), "dist", "install", "--dir", str(out))
        self.assertEqual(code, 2)
        self.assertIn("拒绝覆盖", errors)


if __name__ == "__main__":
    unittest.main()
