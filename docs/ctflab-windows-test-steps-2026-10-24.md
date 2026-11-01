# Windows 手工测试步骤（2026-10-24）

使用本次 `CTFLab-Windows-Test-20261024-r1.zip`，不是 10 月 23 日旧包。此包只有源码、测试和说明，不含 Python、QEMU、镜像或凭据。Windows 实测由用户执行，结果尚待回传。

## 1. 解压与依赖

解压到 `C:\CTFLab-Test\source-20261024`，确保下方直接有 tools 和 docs 文件夹。以普通用户打开 PowerShell：

```powershell
Set-Location C:\CTFLab-Test\source-20261024
python --version
python -c "import sys,ssl,tkinter; print(sys.executable); print(ssl.OPENSSL_VERSION)"
python -m pip install cryptography==46.0.5
New-Item -ItemType Directory -Path .\test-results -ErrorAction Stop
```

使用 Python 3.10 或更高版本；若已有 test-results，保留它并为本次换一个新目录名。`pip` 命令仅安装证书生成依赖。Python/Tk 缺失则先补环境，不继续启动。

## 2. 先跑无 VM 的原生测试

```powershell
python -B -m unittest discover -s tools/tests -p test_ctflab_windows_native.py -v 2>&1 | Tee-Object test-results\native.log
python -B -m unittest discover -s tools/tests -p test_ctflab_windows_exit_observer.py -v 2>&1 | Tee-Object test-results\exit-observer.log
```

两个测试末尾应为 OK；重点检查 `test_independent_observer_survives_parent_exit` 是 ok，不能是 skipped。它会创建短寿命 Python 子进程和独立观测器，父进程自愿退出，子进程随后以 7 退出；不启动或停止 VM。第一组非 Windows 拒绝测试在 Windows 跳过是正常的。若有 ERROR/FAIL，保留日志并先回传，不继续后续 VM 测试。

## 3. 固定 Smoke 环境检查

本入口沿用已有 Windows 固定构建；文件路径必须是：

- `C:\Program Files\qemu\qemu-system-x86_64.exe`
- `C:\CTFLab-Test\Smoke-OVA\smoke-ova-base.qcow2`

核对哈希：

```powershell
Get-FileHash 'C:\Program Files\qemu\qemu-system-x86_64.exe' -Algorithm SHA256
Get-FileHash 'C:\CTFLab-Test\Smoke-OVA\smoke-ova-base.qcow2' -Algorithm SHA256
```

预期 QEMU：`47d57a6072e0bb3bd98f87926eb129eb1736dfe818c67b3b81ef7ce4edd0b3cd`。
预期基盘：`f9c2edc334c9e2839c1d605d6d870e8f68ad1242f892fe3f96ed75bfaf554052`。

不匹配时停止此流程并反馈，不修改源码里的摘要来绕过检查。需要已有可用 WHPX 环境；本流程不自动修改宿主 Windows 功能。

如果已有可信 `C:\CTFLab-Test\qemu-inventory.json`，继续使用。若没有，针对上述已核对的固定安装目录生成新清单（生成清单不证明整个运行时来源可信）：

```powershell
python -B tools/ctflab_runtime_inventory.py --root 'C:\Program Files\qemu' --output C:\CTFLab-Test\qemu-inventory-20261024.json
```

下方示例用旧清单路径；生成新清单时相应替换 `$inventory`。

## 4. 启动专用新实例、查询与显示

```powershell
$run = 'C:\CTFLab-Test\Smoke-OVA\w01-recovery-20261024-01'
$inventory = 'C:\CTFLab-Test\qemu-inventory.json'
Test-Path $run
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 46101,46102 }
```

Test-Path 必须为 False；最后一条应无结果。目录存在则改成全新的后缀；端口占用则使用另一对空闲端口，不能停止占用者。复制磁盘需要足够空间。

```powershell
python -I -B tools/ctflab_windows_recovery.py start --run $run --inventory $inventory --qmp-port 46101 --vnc-port 46102
Start-Sleep -Seconds 5
python -I -B tools/ctflab_windows_recovery.py status --run $run | Tee-Object test-results\status-before.json
Test-Path "$run\observer-ready.json"
python -I -B tools/ctflab_windows_recovery.py display --run $run
```

启动输出 worker-created 仅代表监督进程创建。成功查询应有 `identity: running` 和 `control_reconnected: true`；observer-ready 应存在。显示窗口内检查真实来宾启动、登录与键鼠；仅有黑屏、UEFI Shell 或进程存在不算通过。登录凭据沿用你自己的靶机资料。

关闭显示窗口后，在同一 PowerShell 执行：

```powershell
python -I -B tools/ctflab_windows_recovery.py recover --run $run | Tee-Object test-results\status-reconnect.json
python -I -B tools/ctflab_windows_recovery.py display --run $run
```

检查来宾会话保留，binding.json 中 PID 与 creation_ticks 未改变；关闭窗口后重连不应产生新启动。此步骤验证客户端/窗口恢复，不等同于监督器故障恢复。

## 5. 对该专用实例正常关机并核对持久退出

完成操作并确认可以关闭该新实例后，再执行：

```powershell
$operation = [guid]::NewGuid().ToString()
$operation | Set-Content test-results\powerdown-operation.txt
python -I -B tools/ctflab_windows_recovery.py powerdown --run $run --operation-id $operation | Tee-Object test-results\powerdown.json
Start-Sleep -Seconds 15
python -I -B tools/ctflab_windows_recovery.py status --run $run | Tee-Object test-results\status-after.json
Test-Path "$run\observer-exit.json"
```

`acknowledged` 不等于已经关机；检查来宾实际退出、observer-exit 的相同身份和退出码。15 秒未退出时继续只读查询，不强杀、不换 operation ID 重发；同一 ID 可以读取原结果。原盘再次计算哈希，应保持第3步值。若仍运行，保留现场并说明，不删除目录。

## 6. 回传哪些结果

先回传 `test-results` 中的日志/JSON，以及“是否显示、能否登录、键鼠是否正常、重连是否保留会话、是否正常关机”。失败时补充 worker-console.log、qemu-stderr.log 和 observer-console.log 的相关报错。不要上传 tls 文件夹、私钥、完整运行目录或镜像；原生日志中的个人路径可先脱敏。

监督器故障注入、不同账户权限拒绝、真实双节点网络矩阵尚未由上述步骤覆盖。第一轮结果回来后再按失败点细化，避免直接按旧 PID 结束进程。

## 7. 通用场景后端源码与测试

实现为 `tools/ctflab_qemu_driver.py`，代次与协调器为 `ctflab_generation_store.py`、`ctflab_scenario_coordinator.py`。先运行无来宾逻辑验证：

```powershell
python -B -m unittest discover -s tools/tests -p test_ctflab_qemu_driver.py -v 2>&1 | Tee-Object test-results\generic-driver.log
```

未设置 CTFLAB_RECOVERY_QEMU 时，真实 QEMU 参数 fixture 会明确跳过。不要在 Windows 设置该变量来运行当前 Mac fixture（它使用 TCG 和本机 qemu-img 路径）。真实多节点测试需要按 `docs/ctflab-production-driver-2026-10-24.md` 准备私有 profile、schema 2 场景和资产映射；不能把此处固定 Smoke 无网卡测试视为通用网络通过。
