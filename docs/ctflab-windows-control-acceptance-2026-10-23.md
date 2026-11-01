# Windows后台控制完整验收入口

本轮把QMP协议、匿名管道、进程身份、持久意图和普通用户私有文件通道接成完整开发验收入口。首版仍固定已核验的QEMU与Smoke基盘，WHPX/SDL、无网络。不接管旧实例，不提供任意参数、强制终止、HMP或磁盘commit。此包不是正式App或全部43项交付。

## 已有证据与本轮新增范围

Smoke原人工冷启动/画面/正常关机和安装目录清单已收到，不要求重跑旧r4或旧Smoke命令。本轮改由独立后台持有QEMU、QMP和日志，验证的是新的控制与监督组合：控制终端关闭后不结束实验，新终端查询、请求正常关机、未知状态留证。SDL窗口不提供重新创建能力；不得把控制客户端重连称为显示重连。

依据：2026-10-23核验[QMP协议](https://www.qemu.org/docs/master/interop/qmp-spec.html)和[Python子进程接口](https://docs.python.org/3.10/library/subprocess.html)。后台使用DETACHED_PROCESS与独立进程组；原生行为仍须当前Windows设备实际验证。

## 一次集中验证

将 `CTFLab-Windows-control-r1.zip` 解压到新目录，把已提交的 `runtime-after-smoke.json` 复制到解压目录。以下命令同时适用于CMD与PowerShell，不需要管理员。假定原基盘仍位于 `C:\CTFLab-Test\Smoke-OVA\smoke-ova-base.qcow2`，QEMU仍位于 `C:\Program Files\qemu`。

先跑本轮新增的完整流程合成测试（使用临时Python子进程，不启动VM）：

```cmd
python -B -m unittest discover -s tools/tests -p "test_ctflab_windows_control.py" -v
python -B -m unittest discover -s tools/tests -p "test_ctflab_qmp*.py" -v
python -B -m unittest discover -s tools/tests -p "test_ctflab_process_supervisor.py" -v
```

然后启动一次新的独立实验：

```cmd
python -B tools/ctflab_windows_control.py start --inventory "runtime-after-smoke.json" --run "C:\CTFLab-Test\Smoke-OVA\w01-control-01"
```

启动前对照清单重新采集安装目录、核验固定QEMU/基盘、WHP和可用空间。创建私有ACL的新状态根、完整独立磁盘副本，再由后台复核后启动；已有状态目录拒绝覆盖。复制期间耐心等待，不重复start。若文件变化，停止并核验，不自行更新可信清单绕过。

启动命令返回仅表示后台已创建。等SDL显示后查询：

```cmd
python -B tools/ctflab_windows_control.py status --run "C:\CTFLab-Test\Smoke-OVA\w01-control-01"
```

后台尚未准备好时稍后再查询，不重新start。看到acknowledged及qemu_status=running只证明QMP报告运行，登录画面仍由人观察。

关闭执行命令的终端，保持SDL窗口不关闭。重新打开终端、进入解压目录，重复status。确认仍可查询后请求正常关机：

```cmd
python -B tools/ctflab_windows_control.py powerdown --run "C:\CTFLab-Test\Smoke-OVA\w01-control-01"
```

acknowledged只表示QMP接受请求。等待SDL自行退出，再查询最终记录：

```cmd
python -B tools/ctflab_windows_control.py recover --run "C:\CTFLab-Test\Smoke-OVA\w01-control-01"
```

正常情况下result包含state=exited、returncode=0、source_unchanged=true、control_failure=null。即使存在SHUTDOWN guest事件，graceful_stop_verified和g0_passed仍保留false，人工画面/操作确认与机器证据分别登记。

若命令超时，保存输出的operation_id；使用相同动作加 `--operation-id "原UUID"` 读取原请求结果，不换ID重发关机。recover只读查询，不重新启动、不终止、不重新连接旧管道。关机60秒仍未退出时保留画面和日志，停止追加控制操作；不要删除目录或手动清除锁。

## 集中回传

回传本轮合成测试总数/失败/跳过、关闭终端后仍可查询的结果、是否出现登录画面、powerdown后是否自行退出，以及本轮目录中的：

- host.json、result.json、exit.json（若有）、failure.json（若有）；
- qemu-stderr.log、worker-console.log；
- 出错请求目录中的request.json/response.json及对应intent/result记录（只在失败时需要）。

不要发送test-disk.qcow2或完整状态目录。binding.json/worker.json含本地程序路径和旧PID，分享前遮盖私人路径，未来不得用这些旧PID直接操作进程。

## 生命周期与失败边界

worker使用原生文件锁保证同根唯一；start.intent在启动副作用前落盘，旧意图阻止自动重启。每条请求绑定实例与代次、操作UUID；先完整写request，再提交ready标记；重复UUID必须内容相同，已执行请求不重放。最多256个请求，超限保留现场。后台经当前普通用户ACL验证文件，只有固定status/powerdown可执行。

进程身份使用PID/创建时间/映像匹配，自有Popen和管道贯穿生命周期。故障后保留磁盘、账本、日志；没有无认证TCP端点。该本地文件通道以当前用户/SYSTEM ACL为边界，不防同用户恶意篡改，不是远程或多用户服务。

控制错误后后台保留句柄等待QEMU真实退出，不自动杀VM。监督器本身异常退出后匿名管道无法重新接管，recover只报告实际身份/未知状态；需要人工处置。此项尚不满足监督器崩溃后恢复控制的完整G0门槛。首次原生运行、其他用户拒绝验证、睡眠/重启/磁盘耗尽、最终安装包仍须分别验收。

stderr最多保存1MiB，超出继续读取并报告截断；事件保留最近128条并记录丢弃数。目录元数据的跨平台断电一致性尚未验收。工作区改动不会更新旧发布App。
