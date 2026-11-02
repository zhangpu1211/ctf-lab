"""可复现的完整Windows控制验收源码包；不含运行时、镜像或用户清单。"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

FILES = (
 'tools/ctflab_windows_control.py','tools/ctflab_windows_smoke.py',
 'tools/ctflab_runtime_inventory.py','tools/ctflab_windows_native.py','tools/ctflab_windows_security.py',
 'tools/ctflab_qmp_protocol.py','tools/ctflab_qmp_transport.py','tools/ctflab_process_supervisor.py',
 'tools/tests/test_ctflab_windows_control.py','tools/tests/test_ctflab_qmp_protocol.py',
 'tools/tests/test_ctflab_qmp_transport.py','tools/tests/test_ctflab_process_supervisor.py',
)

README = '''# Windows 控制验收包（源码）

本包只包含 Windows 控制、QMP、传输和进程监督相关源码与测试，不含运行时、镜像、
证书、日志或安装器。需要 Python 3.10+，在已授权的测试环境中运行：

```powershell
python -B -m unittest discover -s tools/tests -v
```

所有结果仍是候选验证，不表示 Windows 11 实机、WHPX、真实来宾或课程环境已经通过。
不要为通过测试关闭安全功能，也不要操作未授权的虚拟机或网络。
'''


def build(source, destination):
    source=Path(source);destination=Path(destination)
    data={name:(source/name).read_bytes() for name in FILES}
    data['README.md']=README.encode('utf-8')
    manifest={'schema':1,'kind':'windows-control-validation-only','g0_passed':False,
              'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in sorted(data.items())}}
    data['MANIFEST.json']=json.dumps(manifest,sort_keys=True,indent=2).encode()
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,raw in sorted(data.items()):
            info=zipfile.ZipInfo(name,(2026,10,23,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16;archive.writestr(info,raw)
    return hashlib.sha256(destination.read_bytes()).hexdigest()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('destination',type=Path)
    args=parser.parse_args();print(build(Path(__file__).resolve().parents[1],args.destination))
