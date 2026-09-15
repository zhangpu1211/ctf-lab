# Vendored 许可证文本来源（不自行撰写，只原样收录）

本目录保存上游组件在 Homebrew keg 中缺失、但随包分发所需的许可证文本。
文件按上游发布物原样收录，未做任何修改。

## dtc / libfdt 1.8.1

- 上游来源：https://mirrors.edge.kernel.org/pub/software/utils/dtc/dtc-1.8.1.tar.xz
  （Homebrew `dtc` formula 的 `downloadLocation`，版本与本机 keg 1.8.1 一致）
- 归档 SHA-256：`23526015a6f1550e0541a53fe7acea1b5a11e3697cdf3a3bdc076abc38f6045d`
  （与 `/opt/homebrew/opt/dtc/sbom.spdx.json` 记录一致，已复核）
- 收录文件与 SHA-256：
  - `GPL`（GPL-2.0 全文）`8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643`
  - `BSD-2-Clause`（libfdt 的 BSD 分支许可全文）`6313108c23efffa36948f8b2cff1560a5935373b527b0e1a837cc77e6ed1bacd`
  - `README.license`（双许可说明）`8a516adc332c25503be9de4a511f9fce45370761a67046811b1c5a5268f2327a`
- 适用组件：随包的 `libfdt.*.dylib`（`KNOWN_LICENSES["dtc"]` = `BSD-2-Clause OR GPL-2.0-or-later`）。
- 覆盖规则：构建时 Homebrew keg 内找不到许可证文本则回退到本目录；回退命中的组件在
  `SBOM.json` 中记为 `license_text_status: "vendored"`。keg 与本目录都没有时构建仍然失败
  （除非显式使用 `--allow-incomplete-license-texts`），不做猜测。

新增上游组件文本时：从对应上游发布物原样复制、在此登记来源与哈希，不要改写文本内容。
