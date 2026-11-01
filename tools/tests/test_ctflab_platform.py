"""平台策略、错误组合及旧 Mac 调用入口的无 VM 回归。"""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab
import ctflab_platform as policy
import ctflab_scenario as scenario
from test_ctflab_scenario import candidate, CAPS, INSTANCE


class PlatformPolicyTests(unittest.TestCase):
    def test_aliases_and_immutable_host(self):
        self.assertEqual(policy.HostPlatform("Darwin", "ARM64"), policy.MACOS_ARM64)
        self.assertEqual(policy.HostPlatform("Windows", "AMD64"), policy.HostPlatform("windows", "x64"))
        with self.assertRaises(AttributeError):
            policy.MACOS_ARM64.system = "windows"

    def test_native_candidates_are_not_execution_evidence(self):
        cases = [("Darwin", "arm64", "aarch64", "hvf", "host"),
                 ("Windows", "AMD64", "x86_64", "whpx", None),
                 ("Linux", "x86_64", "x86_64", "kvm", "host")]
        for system, arch, guest, accel, cpu in cases:
            with self.subTest(system=system):
                result = policy.plan_execution(policy.HostPlatform(system, arch), guest)
                self.assertEqual((result.accelerator, result.cpu), (accel, cpu))
                self.assertFalse(result.emulated)
                self.assertFalse(result.report()["runtime_verified"])
                self.assertTrue(result.report()["requires_runtime_probe"])
                if system != "Darwin":
                    self.assertEqual(result.policy_status, "candidate-only")

    def test_cross_arch_requires_explicit_emulation_and_never_satisfies_hardware(self):
        with self.assertRaises(policy.PlatformPolicyError):
            policy.plan_execution(policy.MACOS_ARM64, "x86_64")
        result = policy.plan_execution(policy.MACOS_ARM64, "x86_64", allow_emulation=True)
        self.assertEqual(result.compute_arguments(), ["-accel", "tcg,thread=multi", "-cpu", "max"])
        with self.assertRaises(policy.PlatformPolicyError):
            policy.plan_execution(policy.MACOS_ARM64, "x86_64", allow_emulation=True, require_hardware=True)

    def test_native_does_not_silently_choose_emulation(self):
        host = policy.HostPlatform("Windows", "AMD64")
        self.assertEqual(policy.plan_execution(host, "x64", allow_emulation=True).accelerator, "whpx")
        with self.assertRaises(policy.PlatformPolicyError):
            policy.plan_execution(host, "x64", acceleration="tcg")
        result = policy.plan_execution(host, "x64", acceleration="tcg", allow_emulation=True)
        self.assertEqual(result.accelerator, "tcg")
        self.assertEqual(result.policy_status, "candidate-only")
        with self.assertRaises(policy.PlatformPolicyError):
            policy.plan_execution(host, "x64", acceleration="tcg", allow_emulation=True, require_hardware=True)

    def test_unsupported_hosts_and_guests_are_rejected(self):
        for system, arch, guest in [("Windows", "arm64", "aarch64"),
                                   ("Darwin", "x64", "x64"), ("Linux", "arm64", "aarch64"),
                                   ("Windows", "x64", "arm64"), ("Linux", "x64", "arm64")]:
            with self.subTest(system=system, arch=arch, guest=guest), self.assertRaises(policy.PlatformPolicyError):
                policy.plan_execution(policy.HostPlatform(system, arch), guest, allow_emulation=True)

    def test_malformed_values_and_argument_injection_are_rejected(self):
        for value in (None, True, [], "i386", "x64 -netdev user", "x86_64\n", "aarch64,accel=tcg"):
            with self.subTest(value=value), self.assertRaises(policy.PlatformPolicyError):
                policy.plan_execution(policy.MACOS_ARM64, value)
        for options in ({"allow_emulation": "false"}, {"require_hardware": 1},
                        {"acceleration": "whpx,tcg"}, {"acceleration": []}):
            with self.subTest(options=options), self.assertRaises(policy.PlatformPolicyError):
                policy.plan_execution(policy.MACOS_ARM64, "arm64", **options)
        with self.assertRaises(policy.PlatformPolicyError):
            policy.plan_execution({"system": "windows"}, "x64")
        for value in (None, [], "FreeBSD", "Windows\n"):
            with self.assertRaises(policy.PlatformPolicyError):
                policy.HostPlatform(value, "x64")

    def test_planning_has_no_io_or_implicit_host_detection(self):
        with mock.patch("builtins.open", side_effect=AssertionError("文件 IO")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("进程")), \
             mock.patch("socket.socket", side_effect=AssertionError("网络")), \
             mock.patch("platform.system", side_effect=AssertionError("隐式宿主")):
            self.assertEqual(policy.macos_execution_plan("arm64").compute_arguments(),
                             ["-accel", "hvf", "-cpu", "host"])
            result = policy.plan_execution(policy.HostPlatform("Windows", "x64"), "x64")
            self.assertEqual(result.compute_arguments(), ["-accel", "whpx"])
            self.assertEqual(result.qemu_binary_name, "qemu-system-x86_64.exe")

    def test_standalone_module_does_not_import_posix_runner(self):
        # 独立解释器禁用 POSIX 依赖；这只是导入边界测试，不冒充 Windows 实机。
        code = """
import sys
sys.path.insert(0, sys.argv[1])
sys.modules['fcntl'] = None
import ctflab_platform as p
assert 'ctflab' not in sys.modules
assert p.plan_execution(p.HostPlatform('Windows', 'AMD64'), 'x64').accelerator == 'whpx'
"""
        result = subprocess.run([sys.executable, "-I", "-c", code, str(Path(policy.__file__).parent)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_read_only_plan_cli_marks_candidate(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(policy.main(["--host-system", "Windows", "--host-architecture", "AMD64",
                                          "--guest-architecture", "x64"]), 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report["kind"], "parameter-plan")
        self.assertEqual(report["policy_status"], "candidate-only")
        self.assertFalse(report["runtime_verified"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            policy.main(["--host-system", "Windows", "--host-architecture", "ARM64",
                         "--guest-architecture", "x64"])
        self.assertEqual(raised.exception.code, 2)


class MacIntegrationTests(unittest.TestCase):
    def test_all_three_builders_use_shared_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = ctflab.LabManager(root)
            for arch, accel in [("aarch64", "hvf"), ("x86_64", "tcg,thread=multi")]:
                with self.subTest(arch=arch), \
                     mock.patch("ctflab.which_any", return_value="/runtime/qemu"), \
                     mock.patch.object(manager, "ensure_uefi_vars", return_value=(root/"code", root/"vars")), \
                     mock.patch("ctflab.macos_execution_plan", wraps=policy.macos_execution_plan) as select:
                    cmd, _ = manager.qemu_command("fixture", {"guest": {"architecture": arch}}, root/"disk", 23400, True)
                    select.assert_called_once_with(arch)
                    self.assertEqual(cmd[cmd.index("-accel")+1], accel)
            with mock.patch("ctflab.which_any", return_value="/runtime/qemu"), \
                 mock.patch("ctflab.find_firmware", return_value=root/"code"), \
                 mock.patch("ctflab.macos_execution_plan", wraps=policy.macos_execution_plan) as select:
                cmd = manager.installer_command("fixture", {}, root/"iso", root/"disk", root/"vars", root/"qmp",
                                                unattended=False, headless=True)
                select.assert_called_once_with("aarch64")
                self.assertEqual(cmd[cmd.index("-accel")+1], "hvf")
        with mock.patch("ctflab_scenario.macos_execution_plan", wraps=policy.macos_execution_plan) as select:
            scenario.qemu_command(candidate(), INSTANCE, "straylight", generation=1,
                                  state_root="/state", socket_root="/s", network_ports={"outer":12001,"inner":12002},
                                  qemu_binary="/runtime/qemu", available_capabilities=CAPS)
            select.assert_called_once_with("x86_64")

    def test_bad_guest_rejected_before_firmware_or_socket_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ctflab.LabManager(Path(directory))
            with mock.patch.object(manager, "ensure_uefi_vars", side_effect=AssertionError("固件写入")), \
                 mock.patch.object(manager, "_qmp_socket", side_effect=AssertionError("端点变更")), \
                 self.assertRaises(ctflab.CTFLabError):
                manager.qemu_command("bad", {"guest": {"architecture": "mips"}}, Path(directory)/"disk", 23400, True)


if __name__ == "__main__":
    unittest.main()
