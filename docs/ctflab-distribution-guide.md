# CTFLab 基盘分发指南（路线 A：网盘 / 课程资料区）

> 状态：2026-09-16 实现并在真实基盘上验证（见 §6）。适用于"老师把压缩基盘放到网盘或课程
> 资料区，学生下载后用 `CTFLab.app` 导入"的交付方式。签名/公证不在本流程内（学生首次打开
> App 需在"系统设置 → 隐私与安全性"手动放行一次）。

## 1. 要分发的文件

| 文件 | 来源 | 大小（压缩后） | 用途 |
|---|---|---|---|
| `kali-arm64-base.qcow2` | `base-80718f780e3b-installed.qcow2`（本机已导入基盘） | 约 8.3GB | Kali 实验机基盘 |
| `kali-arm64-uefi-vars.fd` | `uefi-vars-80718f780e3b.fd` | 64MB | Kali 的 UEFI NVRAM 模板（**必须与基盘配对**） |
| `smoke-base.qcow2` | `base-b3112d219743-netfix1.qcow2` | 约 0.1GB | Smoke 靶机基盘 |
| `basic-pentesting-2-base.qcow2` | `base-c68a185c1bb3-netfix1.qcow2` | 约 0.8GB | Basic Pentesting 2 基盘 |
| `DISTRIBUTION.json` / `SHA256SUMS` / `README.md` | `ctflab dist prepare` 生成 | 数 KB | 清单与校验 |
| `CTFLab.app` | `app build` 产物（自带 `.sha256` 旁车） | 约 302MB | 运行器（含 QEMU + Python + 可选 SPICE，无需另装） |

压缩产物是**标准 qcow2**（zstd 压缩簇），`qemu-img` 与 CTFLab 都能直接读，学生不需要解包。

## 2. 老师：生成分发目录

```bash
# 每个 profile 一次；同一 --out 目录会自动合并清单
python3 tools/ctflab.py dist prepare --profile kali-arm64 --out ~/Downloads/ctflab-dist
python3 tools/ctflab.py dist prepare --profile smoke      --out ~/Downloads/ctflab-dist
python3 tools/ctflab.py dist prepare --profile basic-pentesting-2 --out ~/Downloads/ctflab-dist

# 上传前复核（逐文件大小与 SHA-256 与清单一致）
python3 tools/ctflab.py dist verify --dir ~/Downloads/ctflab-dist
```

要点：

- `--source` 缺省取该 profile **当前已导入的基盘**（即验证记录里那份）；需要换来源时显式指定；
- aarch64 profile 必须登记 UEFI NVRAM 模板（缺省取 `image.json` 里登记的 `uefi_vars_path`，
  或用 `--nvram` 指定）；确实不要时用 `--no-nvram` 明确跳过——**不推荐**，跳过的是已验证的启动路径；
- 压缩流程自带两道校验：`qemu-img check`（结构）+ 容量一致 + `qemu-img compare`（非严格：
  来宾可见内容逐字节一致）。注意**不能**用严格模式 `-s`：它会比较块的分配布局，而压缩必然重排
  布局，必然误报 `block status mismatch`；反过来非严格模式对容量不一致只警告不报错，所以容量用
  `qemu-img info` 显式核对。任一项不过直接失败，不发布产物。条目的
  `content_verified: qemu-img-compare-equal` 就是这项证据；
- 清单里每个基盘条目带 `source_base_sha256`：它是该 profile 已导入基盘（老师侧原始文件）的哈希，
  用于老师确认"发出去的确实是验证过的那份"；条目里的 `sha256` 才是学生下载要核对的文件哈希；
- 压缩默认开启（`--no-compress` 仅用于小镜像或诊断）。

## 3. 学生：下载与导入

```bash
# 1) 校验下载完整性（与文件同目录执行）
shasum -a 256 -c SHA256SUMS

# 2) 导入：清单会强制核对基盘哈希，并自动套用配套的 NVRAM 模板
CTFLab.app/Contents/Resources/bin/CTFLab import kali-arm64 ~/Downloads/kali-arm64-base.qcow2 \
  --manifest ~/Downloads/DISTRIBUTION.json

# 3) 启动
CTFLab.app/Contents/Resources/bin/CTFLab run kali-arm64
```

- 哈希不一致时导入**直接失败**并打印期望值与实际值：重新下载，不要绕过；
- 没有清单也可以导入（`--expect-sha256 <哈希>` 手工指定，或不校验、仅记录 `source_sha256`）；
  校验结果会写进 `image.json` 的 `source_verification` 字段，便于事后审计；
- 重复导入同一文件是幂等的：不会覆盖已验证的基盘，只更新校验记录；
- 学生侧拿到的保证链条：下载哈希与清单一致（传输完整） + 该清单由老师在同一份"验证过的基盘"上
  生成且 `content_verified = qemu-img-compare-equal`（内容等价）。学生导入后生成的基盘是重新编码的
  qcow2，文件哈希与老师的原始基盘不同，这是正常的。

## 4. 网盘与资料区的注意事项

- **单文件大小限制**：部分网盘对免费用户限制单文件上传大小（如 4GB）。若受限，用分卷压缩
  （`split -b 3900m kali-arm64-base.qcow2 kali-arm64-base.qcow2.part-`），并在 `README.md`
  里注明重组命令（`cat kali-arm64-base.qcow2.part-* > kali-arm64-base.qcow2`）——
  **重组后必须重新 `shasum -a 256` 比对 `SHA256SUMS`**；
- **不要依赖网盘的"秒传/在线预览"**判断文件是否正确，只认本地实测哈希；
- 上传后自己下载一次并跑 `ctflab dist verify`（或 `shasum -a 256 -c`），确认上传没有损坏；
- 资料区建议与 `CTFLab.app` 放在同一层级，并置顶学生步骤（可直接用生成的 `README.md`）。

## 5. 安全与合规

- **分发前清理基盘**：检查 `~/.ssh`、shell 历史、浏览器 profile、代理/凭据文件；确认
  `/etc/ssh` host key 可以被全班共享（教学环境通常可接受，但要有意识地接受）；
- **第三方镜像条款**：Smoke / Basic Pentesting 2 来自 VulnHub 等第三方，再分发条款需逐个确认；
  拿不准就改为"学生自行到原页面下载 + 提供已知哈希"（`--expect-sha256` 同样适用）；
- 镜像与发布包**不得提交进任何 Git 仓库**（沿用既有规则）；课程资料区仅面向本课程学生；
- 来宾口令属于实验机凭据，只用于本地隔离实验网。

## 6. 实现与验证

- 命令：`tools/ctflab.py dist prepare|verify`（模块 `tools/ctflab_dist.py`）；
  导入校验：`ctflab import --expect-sha256/--manifest/--nvram`；
- 单元测试：`tools/tests/test_ctflab_distribution.py`（清单合并、压缩参数、篡改检测、
  导入校验与冲突拒绝、幂等重复导入）；
- 真实测量：Kali 基盘 19.15GB → 8.29GB（zstd，2.3x）；真实分发目录生成 + 复核 + smoke
  基盘的"下载→`--manifest` 导入"全流程已在本机跑通（见验证记录）。
