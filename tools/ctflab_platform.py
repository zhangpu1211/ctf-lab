"""宿主/客体与加速器的纯策略；不探测硬件、不启动进程、不授予执行能力。

Windows/Linux 结果只是候选参数。完整运行仍需平台适配器及独立实机验收；
不能把本模块生成计划或 QEMU 列出后端当成加速器可用的证明。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


class PlatformPolicyError(ValueError):
    """平台组合或显式执行策略不在当前白名单。"""


def normalize_architecture(value: str) -> str:
    aliases = {"arm64": "aarch64", "aarch64": "aarch64",
               "amd64": "x86_64", "x64": "x86_64", "x86_64": "x86_64"}
    if not isinstance(value, str) or value.lower() not in aliases:
        raise PlatformPolicyError("架构必须为 aarch64/arm64 或 x86_64/amd64/x64。")
    return aliases[value.lower()]


@dataclass(frozen=True)
class HostPlatform:
    """调用方提供的目标宿主标签，不等同于现场能力探测结果。"""

    system: str
    architecture: str

    def __post_init__(self):
        systems = {"darwin": "macos", "macos": "macos",
                   "windows": "windows", "linux": "linux"}
        if not isinstance(self.system, str) or self.system.lower() not in systems:
            raise PlatformPolicyError("宿主系统不在 macOS/Windows/Linux 规划范围。")
        object.__setattr__(self, "system", systems[self.system.lower()])
        object.__setattr__(self, "architecture", normalize_architecture(self.architecture))


MACOS_ARM64 = HostPlatform("Darwin", "arm64")


@dataclass(frozen=True)
class ExecutionPlan:
    host: HostPlatform
    guest_architecture: str
    accelerator: str
    cpu: str | None
    qemu_binary_name: str
    emulated: bool
    policy_status: str

    def compute_arguments(self) -> list[str]:
        """仅返回受控 -accel/-cpu 参数，不包含路径、网络、端点或授权。"""
        args = ["-accel", "tcg,thread=multi" if self.accelerator == "tcg" else self.accelerator]
        if self.cpu is not None:
            args += ["-cpu", self.cpu]
        return args

    def report(self) -> dict:
        return dict(asdict(self), kind="parameter-plan", runtime_verified=False,
                    requires_runtime_probe=True, compute_arguments=self.compute_arguments())


def plan_execution(host: HostPlatform, guest_architecture: str, *,
                   acceleration: str = "auto", allow_emulation: bool = False,
                   require_hardware: bool = False) -> ExecutionPlan:
    """纯函数：缺少硬件能力时由未来探针拒绝，禁止自动降级到 TCG。

    auto 仅按架构选候选后端。tcg 需要显式允许；require_hardware 的课程
    永不选择 TCG。Windows ARM64/Mac Intel/Linux ARM64 尚不在首轮矩阵。
    """
    if not isinstance(host, HostPlatform):
        raise PlatformPolicyError("必须传入明确的 HostPlatform。")
    guest = normalize_architecture(guest_architecture)
    if acceleration not in ("auto", "tcg"):
        raise PlatformPolicyError("加速策略仅接受 auto 或显式 tcg，不接受任意 QEMU 参数。")
    if type(allow_emulation) is not bool or type(require_hardware) is not bool:
        raise PlatformPolicyError("模拟许可与硬件要求必须为布尔值。")
    native = {("macos", "aarch64"): "hvf",
              ("windows", "x86_64"): "whpx",
              ("linux", "x86_64"): "kvm"}
    key = (host.system, host.architecture)
    if key not in native:
        raise PlatformPolicyError("该宿主系统/架构组合尚未纳入平台策略。")
    # Windows/Linux ARM 来宾不在首轮课程范围；不能靠 allow_emulation 扩大支持。
    if host.system != "macos" and guest != "x86_64":
        raise PlatformPolicyError("当前 Windows/Linux 候选只允许 x86_64 来宾。")
    accelerator = "tcg" if acceleration == "tcg" or guest != host.architecture else native[key]
    if accelerator == "tcg" and (not allow_emulation or require_hardware):
        raise PlatformPolicyError("该组合需要显式允许 TCG，且课程不得要求硬件加速。")
    # WHPX CPU 型号须由 W01 锁定构建实测；候选先不覆盖 QEMU 默认 CPU。
    cpu = "max" if accelerator == "tcg" else None if accelerator == "whpx" else "host"
    return ExecutionPlan(host, guest, accelerator, cpu,
                         f"qemu-system-{guest}" + (".exe" if host.system == "windows" else ""),
                         accelerator == "tcg",
                         "existing-mac-policy" if host == MACOS_ARM64 and acceleration == "auto"
                         else "candidate-only")


def macos_execution_plan(guest_architecture: str) -> ExecutionPlan:
    """现有 Mac 参数生成入口的兼容策略，保留已声明的 x86 TCG 路径。

    目标宿主明确固定为 Mac ARM64，不能根据开发机平台悄悄改变生成结果。
    Windows/Linux 计划只通过 plan_execution 获取，不接入旧 UNIX/Cocoa 路径。
    """
    return plan_execution(MACOS_ARM64, guest_architecture, allow_emulation=True)


def main(argv=None) -> int:
    """独立的候选计划查看器，可在没有 POSIX 运行器依赖的环境中使用。"""
    import argparse
    import json
    parser = argparse.ArgumentParser(description="只生成平台候选参数，不检查硬件或启动 VM")
    parser.add_argument("--host-system", required=True)
    parser.add_argument("--host-architecture", required=True)
    parser.add_argument("--guest-architecture", required=True)
    parser.add_argument("--acceleration", choices=("auto", "tcg"), default="auto")
    parser.add_argument("--allow-emulation", action="store_true")
    parser.add_argument("--require-hardware", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = plan_execution(HostPlatform(args.host_system, args.host_architecture),
                                args.guest_architecture, acceleration=args.acceleration,
                                allow_emulation=args.allow_emulation,
                                require_hardware=args.require_hardware)
    except PlatformPolicyError as exc:
        parser.error(str(exc))
    print(json.dumps(result.report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
