"""生成供用户自行运行的 Windows 基础验证包；不含 VM、运行时或凭据。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

FILES = (
    'tools/ctflab_platform.py', 'tools/ctflab_contract.py', 'tools/ctflab_local_service.py',
    'tools/ctflab_windows_probe.py', 'tools/ctflab_windows_native.py',
    'tools/ctflab_windows_security.py', 'tools/ctflab_local_adapter.py',
    'tools/tests/test_ctflab_windows_security.py',
    'tools/ctflab_scenario_v2.py', 'tools/ctflab_catalog.py', 'tools/ctflab_external_attach.py',
    'tools/tests/test_ctflab_windows_native.py', 'tools/tests/test_ctflab_windows_probe.py',
    'tools/tests/test_ctflab_scenario_v2.py', 'tools/tests/test_ctflab_catalog.py',
    'docs/ctflab-windows-prototype-checklist-2026-10-21.md',
)
README = '''# Windows 基础验证包（非运行器发布包）

原生 Intel/AMD 64位 Windows 仍使用 QEMU + WHPX 硬件加速；QEMU 管理虚拟设备和磁盘，
不是默认使用跨架构软件模拟。本项目首版为 Windows 11 x64，32位 Windows 不在范围内。
本包的基础检查不需要先安装 QEMU。

此包只有源码、单元测试与原型清单，不含镜像、QEMU、Python、固件、显示客户端或签名安装器。
不会启动 VM、修改系统功能/路由/防火墙或连接外部服务。需要用户已有 Python 3.10+。
在普通用户 PowerShell 中进入解压目录后运行：

```powershell
python -B -m unittest discover -s tools/tests -v
python -B tools/ctflab_windows_probe.py --native-preflight
python -B tools/ctflab_windows_probe.py --self-test
python -B tools/ctflab_windows_probe.py
```

第一条在 Windows 上会实际查询当前 Python 进程身份、验证临时文件锁；其他测试是合成夹具。
原生预检查只查询 WHP API 是否报告 hypervisor present，不启用系统功能、不创建虚拟机。
全部命令输出的 G0 仍是 false；这些基础结果不代表 QEMU 或课程已经运行通过。
Windows 原生测试还会新建临时私有目录并核验 ACL/契约存储，不修改任何已有目录权限。
不需要管理员权限，不要为通过测试放宽安全功能。

若预检查报告 `not-present`，只表示当前 hypervisor 未运行，不能据此判断 BIOS 设置。
在“启用或关闭 Windows 功能”中核对 Windows 虚拟机监控程序平台
（Windows Hypervisor Platform），按系统提示启用并重启，然后重跑预检查。
依据：https://www.qemu.org/docs/master/system/whpx.html 。仍不通过时回传状态，
不要自动改用 TCG 或关闭系统安全功能。系统功能调整与本包普通用户测试是两个步骤。

r4 修复初始化 SQLite 连接未立即关闭导致 Windows 清理临时目录失败的问题；
加入成功/异常路径的句柄释放回归测试。旧 r3 的失败记录保留，r4 仍须 Windows 复测。

有已核验来源、锁定版本与哈希的 QEMU 后，可按原型清单和驱动文档另行进行固定构建查询；
本包不自动下载或选定运行时。受保护控制、显示、WHPX 冷启动和恢复仍需后续专门验收入口。

回传：Windows 版本/CPU 架构（无需用户名或设备序列号）、Python 版本、测试总数/失败/跳过、
--native-preflight 与 --self-test JSON 结果、此 zip 的 SHA-256。错误堆栈可能含用户名和私人路径，分享前自行检查遮盖。
不要发送完整磁盘、密码、token 或个人目录内容。保留失败，不修改预期结果使测试通过。

MANIFEST.json 提供逐文件哈希，用于传输一致性；它不是发行签名或可信来源认证。
'''


def build(source_root, destination):
    source_root=Path(source_root)
    destination=Path(destination)
    contents={name:(source_root/name).read_bytes() for name in FILES}
    contents['README.md']=README.encode('utf-8')
    manifest={'schema':1,'kind':'windows-foundation-validation-only','g0_passed':False,
              'files':{name:hashlib.sha256(data).hexdigest() for name,data in sorted(contents.items())}}
    contents['MANIFEST.json']=json.dumps(manifest,sort_keys=True,indent=2).encode('utf-8')
    # x 模式不覆盖用户已有验证包；固定时间使相同源码可复现。
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data in sorted(contents.items()):
            item=zipfile.ZipInfo(name,date_time=(2026,10,21,0,0,0))
            item.compress_type=zipfile.ZIP_DEFLATED
            item.external_attr=0o100644<<16
            archive.writestr(item,data)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def main(argv=None):
    parser=argparse.ArgumentParser(description='构建 Windows 基础验证源码包')
    parser.add_argument('destination',type=Path)
    args=parser.parse_args(argv)
    print(build(Path(__file__).resolve().parents[1],args.destination))
    return 0


if __name__=='__main__':raise SystemExit(main())
