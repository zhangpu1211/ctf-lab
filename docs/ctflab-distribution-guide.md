# CTFLab 镜像制作与分发指南

> 2026-10-11 整理。当前使用与发布状态见[当前状态](ctflab-current-status.md)；历史测量见[2026-09-16 分发链验证](verification-distribution-2026-09-16.md)，历史基盘文件名与旧构建路径不再作为操作入口。

## 1. 完整分发的含义

接收者使用 Apple Silicon Mac、macOS 26.0+，获得 App ZIP 和一个完整镜像包，选择镜像包目录后校验、导入缺失节点，再选中启动。App 与镜像分别交付；软件不包含虚拟磁盘。

当前统一镜像库为 `/Users/pufei/Downloads/CTFLab-Library`。已处理的三节点包位于 `02-已处理`，软件位于 `03-软件`；原始输入位于 `01-待处理`。接收者可复制到任意路径。GUI 只读所选目录顶层，不递归找全库的分发清单。

一份已制作镜像包应包含：

- 磁盘与配套 NVRAM（UEFI 时按 profile/清单配对）；
- DISTRIBUTION.json、SHA256SUMS 和人读说明；
- 与接收端匹配的 profile：架构、固件、白名单控制器、网卡、服务和网络边界；
- 原始来源、许可、校验、实际验收范围，不包含公开密码或私人数据。

当前三节点包使用内置 profile。DISTRIBUTION.json 只登记文件，不自动安装任意自定义硬件配置。需要随包分发自定义 profile 时，使用下文的目录式内容包（schema 2）：配置随包提供并受白名单校验，导入不依赖 App 内置配置。仅有 QCOW2 不构成完整适配。

## 2b. 目录式内容包（schema 2）：自定义 profile 随包分发

适用场景：把"配置 + 基盘 + 必要固件 + 使用说明"作为一个自包含目录交付，接收者一条命令完成校验和导入，无需手工复制 YAML。

### 制作

```bash
./tools/ctflab dist make-pack --out /path/to/内容包目录 \
  --pack-id my-course-pack --name "课程包显示名" --version 1.0.0 \
  --profile /path/to/my-node.yaml --base /path/to/base.qcow2 \
  --nvram /path/to/uefi-vars.fd --doc /path/to/说明.md
./tools/ctflab dist verify --dir /path/to/内容包目录 --conflicts
```

`--nvram` 与 `--doc` 可选；`--doc` 可重复给出多个说明文件。

约束（制作前自查，导入端同样强制）：

- 节点配置 YAML 按 `tools/ctflab_profiles/*.yaml` 的 schema 编写，文件名必须是 `<id>.yaml`；
- 内容包只允许四类角色：`base`（基盘）、`nvram`（UEFI 变量模板）、`profile`（节点配置）、`doc`（md/txt/pdf/png/jpg 说明）；不接受脚本、钩子或任意 QEMU 参数；
- 包必须自包含：每个 base/nvram 引用的 profile 必须随包带 YAML；配置 id 不得与内置课程同名；
- 配置不得声明联网（`internet: true`）或非 `lab` 网段；端口映射只到 127.0.0.1（运行器本身强制）；
- `requires_runner`（默认 `>=当前版本`）声明最低运行器要求，接收端版本不足时拒绝导入；
- 清单登记每个文件的大小与 SHA-256；文件平铺在包目录内，不允许子目录、绝对路径或符号链接；
- 配置/清单中的 `verification` 段是制作者声明，仅供参考；它不会也不应被写成接收方已验收。

### 接收者导入

```bash
ctflab dist install --dir /path/to/内容包目录
ctflab run smoke-mini
```

- 导入前整体校验：缺件、哈希/大小不符、非法配置、版本不满足时**不做任何导入**并逐项报错；
- 配置以排他方式装入用户状态目录（默认 `~/Library/Application Support/CTFLab/profiles`）：内置同名一律拒绝；已有同名候选且内容不同默认不覆盖，需要人工决定；内容相同则幂等跳过；
- 导入后配置、基盘、说明都由状态目录管理；内容包目录移走或删除后已导入节点仍可启动；
- 导入失败或取消会回滚本轮写入（半安装配置、说明副本、包记录），已完成的节点如实保留；原包不被修改；
- GUI：选中内容包目录后同样先校验（显示节点、资源需求、冲突与声明），导入按钮走同一条 `dist install`。

### 与三节点分发目录的关系

旧 `DISTRIBUTION.json`（schema 1，无 `pack` 对象）行为不变：profile 仍须接收端已存在，逐节点 `import --manifest`。两种格式共存；`dist verify` 同时兼容，`dist install` 只接受 schema 2 内容包。

## 2. 制作已处理包

源码维护环境，在已导入并完成对应验收的基盘上生成全新目录：

```bash
./tools/ctflab dist prepare --profile kali-arm64 --out /path/to/new-distribution
./tools/ctflab dist prepare --profile smoke --out /path/to/new-distribution
./tools/ctflab dist prepare --profile basic-pentesting-2 --out /path/to/new-distribution
./tools/ctflab dist verify --dir /path/to/new-distribution
```

缺省来源为该 profile 当前登记基盘；更换来源需显式指定。不要硬编码已清理的旧 base 文件名。

QCOW2 默认压缩。转换需结构 check、虚拟容量一致及非严格 compare 内容一致：压缩可能改变块分配布局，不能把严格分配布局比较用于内容等价判断；非严格 compare 不负责拒绝尺寸不同，因此容量单独核对。内容等价不代表磁盘启动、服务或网络验收通过。

UEFI 基盘应随附已配对的 NVRAM 模板；不能把不同安装实例的变量文件混用。镜像原件只读，修改在可恢复副本上完成。

## 3. 接收者使用

推荐图形流程见[使用教程](ctflab-student-distribution-tutorial.md)。命令行排障入口：

```bash
/path/to/CTFLab.app/Contents/Resources/bin/ctflab-cli dist verify --dir /path/to/new-distribution
/path/to/CTFLab.app/Contents/Resources/bin/ctflab-cli import smoke /path/to/new-distribution/smoke-base.qcow2 --manifest /path/to/new-distribution/DISTRIBUTION.json
/path/to/CTFLab.app/Contents/Resources/bin/ctflab-cli run smoke
```

下载后在分发目录中检查 SHA256SUMS。缺文件或哈希不一致应重新下载，不能绕过清单。导入独立基盘与运行 overlay，原分发包保持不变；重复导入不应静默信任被改写的已登记基盘。

## 4. 多个已处理靶场如何存放

当前三节点清单仍在 `02-已处理` 顶层。以后新制作的包放在其独立子目录，例如 `02-已处理/课程B`，接收者选择该子目录，不选择包的上级根目录。不要把未登记镜像任意混入已有清单；普通文件扫描会触发候选导入，并不继承现有包的硬件设置。

本库的 WebServer 原始 OVA 与未完整验收的派生副本均已按用户要求删除，库外课程资料原件未动。以后重新制作需取得来源并重新识别、转换、验收，不将旧 DHCP/PXE 候选事件视作磁盘引导成功。

## 5. 完整性、许可与迁移

- 分发哈希只证明字节完整；来源原盘哈希、导出盘哈希、E2E 后可写盘哈希不得混用。
- 基盘包含私密历史、凭据、SSH 资料时，清理后重新验收；不在公开说明中放口令。
- 项目代码 MIT；App 第三方文本/SBOM/源码要约按实际包校验。第三方靶机再分发权限是独立问题。
- App 当前 ad-hoc、未公证；接收者可能需系统手动放行。不得描述为 Developer ID 正式签名。
- 镜像、日志、PCAP、凭据不进 Git；公共 Release 仅发合规软件产物。
- 镜像库可以整目录迁移，运行进度不在库内。保留进度需正常关机后独立备份状态及 NVRAM，不能复制运行盘冒充一致备份。
- 跨 Mac 与最低 macOS 实机验收未覆盖时明确标记，不承诺任意机器保证可用。
