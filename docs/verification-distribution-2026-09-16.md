# CTFLab 分发链验证记录：压缩基盘与可校验导入（2026-09-16）

结论只使用四类状态标签：**已验证** / **部分验证** / **未验证** / **后续任务**。

## 0. 结论摘要

- **已验证**：`ctflab dist prepare/verify`（路线 A：网盘/资料区）在本机真实基盘上跑通：
  三个 profile 生成压缩基盘 + Kali 的 UEFI NVRAM 模板，逐条登记哈希并生成
  `DISTRIBUTION.json`/`SHA256SUMS`/`README.md`；`dist verify` 通过（4 个文件），
  篡改任一字节即被检出（退出码 2）。
- **已验证**：`ctflab import --manifest/--expect-sha256/--nvram` 的来源校验链：用分发目录
  真实导入 smoke 基盘，校验通过并把证据写进 `image.json.source_verification`；把
  `basic-pentesting-2` 的基盘当 smoke 导入时**被拒绝**并打印期望值与实际值，且不写任何状态。
- **发现并修复 1 个缺陷**：压缩产物的内容校验最初用 `qemu-img compare -s`（严格模式），
  它对压缩后重排的块分配布局报 `block status mismatch` 误报；改为"容量显式核对 +
  非严格 `qemu-img compare`（宾客可见内容）"，并加单元测试锁定语义（见 §3）。
- **未验证/后续任务**：学生侧大文件下载体验（网盘限速、分卷重组）未实测；断点续传与镜像
  缓存未实现；VulnHub 靶盘的再分发条款未逐个确认；Kali 的压缩基盘未再跑一遍完整 E2E
  （内容等价由 `qemu-img compare` 证明，Kali E2E 29/29 见 6.3B 记录）。

## 1. 交付物

| 项目 | 值 |
|---|---|
| 新模块 | `tools/ctflab_dist.py`（压缩、清单合并、复核；zstd 压缩 qcow2） |
| 新命令 | `ctflab dist prepare --profile <id> --out <dir>`、`ctflab dist verify --dir <dir>` |
| 导入校验 | `ctflab import <profile> <file> --expect-sha256 <hex> \| --manifest DISTRIBUTION.json [--nvram <fd>]` |
| 文档 | `docs/ctflab-distribution-guide.md`（老师/学生步骤、网盘注意、安全清单） |
| 测试 | `tools/tests/test_ctflab_distribution.py`（18 项：清单合并、压缩参数与内容校验、篡改检测、导入校验与冲突拒绝、幂等重复导入） |

## 2. 真实分发目录（本机实测）

命令：`dist prepare` × 3（同一 `--out`）→ `dist verify`。

| 文件 | 原始基盘 | 压缩产物 | SHA-256 前缀 | 内容校验 |
|---|---|---|---|---|
| `kali-arm64-base.qcow2` | 19.15GB | **7.55GB**（2.5x） | `5e6ad48b941a…` | compare-equal |
| `kali-arm64-uefi-vars.fd` | 64MB | 64MB | `8639a3fb43dd…`（与登记值一致） | 原样复制 |
| `basic-pentesting-2-base.qcow2` | 1.45GB | 1.34GB | `f3fe2a8a4345…` | compare-equal |
| `smoke-base.qcow2` | 0.27GB | 0.26GB | `7620acabaf1b…` | compare-equal |

- 每个基盘条目带 `source_base_sha256`，与既有验证记录一致（kali `ca1034606a82…`、
  smoke `f0da1da7a932…`、bp2 `87bb1dc71760…`），用于老师确认分发的是验证过的那份；
- 压缩是确定性的：两次独立生成的产物哈希一致（`7620acab…`/`f3fe2a8a…`/`5e6ad48b…`）；
- 篡改检测：改动 `smoke-base.qcow2` 一个字节后 `dist verify` 报
  `SHA-256 不一致（清单 7620acab…，实际 5799f031…）`，退出码 2；重新 `prepare` 后恢复通过；
- smoke/bp2 压缩率低（约 1.05x 与 1.08x）：这两个基盘本身已接近最优；Kali 桌面镜像收益最大。

学生侧流程（真实执行，`--state-dir` 指向全新目录）：

```
$ ctflab import smoke .../smoke-base.qcow2 --manifest .../DISTRIBUTION.json
导入完成：smoke
来源校验：通过（manifest；期望 7620acabaf1b…）

$ ctflab import smoke .../basic-pentesting-2-base.qcow2 --manifest .../DISTRIBUTION.json
错误：来源镜像 SHA-256 与期望值不一致，拒绝导入（请重新下载，不要跳过校验）：
  期望：7620acabaf1b646ff69dba276dc72b55e8d56f768330c996dbea358f31a925d9
  实际：f3fe2a8a43455cf39f02fc4c0396d4405d6f0a5ccab0e7798fa323e5dd09d8f5
（退出码 2；未写入任何导入状态）
```

## 3. 发现的缺陷与修复

- **严格模式 compare 不适用于压缩产物**：`qemu-img compare -s` 除内容外还比较块的分配状态；
  `convert -c` 会重排分配布局，因此对任何压缩产物必然报
  `Strict mode: Offset … block status mismatch!`（实测 smoke 基盘）。修复：先 `qemu-img check`，
  再用 `qemu-img info` **显式核对容量**（非严格 compare 对容量不一致只警告不报错），最后用
  非严格 `qemu-img compare` 比较宾客可见内容；单元测试分别锁定"内容不一致必须拒绝"与
  "容量不一致必须拒绝"两条语义，另一个测试断言 compare 调用**不得**含 `-s`。

## 4. 范围与限制（不得跨类宣称）

- **下载体验未验证**：本机是文件系统拷贝，网盘限速、断点续传、分卷重组的真实体验未测试；
  指南给出分卷方案（`split` + 重组后重新校验），但本期不宣称"学生下载一次必成功"。
- **Kali 压缩基盘未跑完整 E2E**：内容等价由 `qemu-img compare` 证明；Kali ARM64 + UEFI 的
  29/29 验收是在未压缩基盘上完成的（6.3B 记录）。导入路径（`--manifest` + 自动 NVRAM 模板）
  在 smoke 上真实跑通、NVRAM 附加与校验由单元测试覆盖。
- **第三方镜像条款**：VulnHub 等靶盘能否随课程资料区再分发，需逐个确认；指南给出"改为学生
  自行下载 + `--expect-sha256`"的替代路径。
- **未实现**：断点续传、镜像缓存、内容索引签名（Phase 4 其余项）。

## 5. 复现命令

```bash
python3 -m unittest discover -s tools/tests          # 331 项

python3 tools/ctflab.py dist prepare --profile kali-arm64 --out <dist>
python3 tools/ctflab.py dist prepare --profile smoke --out <dist>
python3 tools/ctflab.py dist prepare --profile basic-pentesting-2 --out <dist>
python3 tools/ctflab.py dist verify --dir <dist>

python3 tools/ctflab.py --state-dir <fresh> import smoke <dist>/smoke-base.qcow2 \
  --manifest <dist>/DISTRIBUTION.json
```
