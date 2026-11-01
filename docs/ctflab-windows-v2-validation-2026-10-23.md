# V2 Windows 运行时清单验证入口

本轮推进W01完整运行时登记的前置切片。现有r4基础验证和固定QEMU帮助查询已有用户回传；Smoke冷启动仍待回传。此工具只读取用户指定的QEMU安装目录，记录其中全部普通文件的相对名称、大小和SHA-256，不执行二进制、不启动VM、不修改系统功能/网络，不读取镜像或个人目录。

## 使用

解压 `output/windows-v2-20261023/CTFLab-Windows-V2-inventory-r1.zip` 到新目录，在普通PowerShell中进入该目录：

```powershell
python -B -m unittest discover -s tools/tests -v
python -B tools/ctflab_runtime_inventory.py --root 'C:\Program Files\qemu' --output .\runtime-before.json
```

确认指定的是QEMU安装目录，不要指定磁盘根、用户目录或整个CTFLab镜像库。工具要求根下存在qemu-system-x86_64.exe。报告必须写在安装目录外，现有文件不会覆盖；再次运行时使用新文件名。

完成前轮Smoke实验后，可重新采集比较：

```powershell
python -B tools/ctflab_runtime_inventory.py --root 'C:\Program Files\qemu' --compare .\runtime-before.json --output .\runtime-after.json
```

退出码0表示采集成功（比较模式下文件一致），2表示新增/删除/变化，1表示检查失败。差异逐项留在comparison；不得在变化后继续沿用原清单认定构建一致。

报告不包含安装根绝对路径、用户名、设备名或序列号，但包含所选安装目录内的相对文件名和系统/Python版本，分享前仍应预览。若误选有私人材料的目录，不分享报告，改用正确目录重新采集。

## 证据边界

安装目录清单不是依赖闭包：目录外系统DLL、实际加载模块、Python环境完整性、固件选择、来源/许可证与签名仍需补充。components_complete、dependency_closure_verified、source_verified、g0_passed始终false，不因文件存在或哈希一致提升。报告的host只说明采集设备，不是运行时目标或支持承诺。

拒绝符号链接、重解析点、硬链接及非普通文件，限制条目数和总大小，检查采集前后文件身份/大小/时间及目录集合。用于静止、可信安装目录的复核；不能抵御同用户恶意并发替换，不把这份检查当作后续启动的授权或原子锁。启动前仍应核验实际运行时并建立进程绑定。安装/更新进行中应等完成后重新采集。

首次本机测试发现macOS临时目录父路径是系统符号链接，正向夹具被严格路径检查拒绝。修正测试夹具为实际临时路径，保留生产拒绝策略；不是放宽Windows链接检查。最终8项合成测试通过，涵盖稳定目录、差异、链接、采集中变化、限额、清单篡改和输出保护。Windows原生运行尚未验证。

## V2下一步

回传清单前先查看其中相对文件名；另回传Smoke结果：是否看到登录提示、正常关机是否退出，以及该轮result.json和必要错误文本（遮盖私有路径）。这不是要求重做已通过的r4基础检查。

基于完整清单选择受保护控制与监督实现，再进行控制重连、监督异常、端口归属、正常关机与恢复实测。未知状态保留现场，不自动操作旧PID。不以本轮目录采集或无网络Smoke替代G0，更不推进到公开G1。
