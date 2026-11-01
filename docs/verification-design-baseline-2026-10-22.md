# 全路线图设计基线验证

> 历史验收快照，不替代当前软件状态。

2026-10-22，正式目录 `/Users/pufei/Downloads/ctf-lab`；分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f62`。本轮仅新增设计、文档入口和白名单，保留既有源码修改。

设计覆盖：与执行台账逐项集合比较，43个ID唯一、无缺漏；设计及台账本地链接存在，`git diff --check`通过。设计给出统一契约、生命周期提交/取消/恢复、Windows控制与监督候选、网络/内容信任边界、各项负测及V0—V5验证顺序。设计完成不表示实现完成。

实际测试：

- `python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_*docs*.py'`：94项，89通过、5条件跳过，0.467秒。
- 使用unittest discover逐个加载 `test_ctflab_{platform,local_contract,local_adapter,scenario_v2,catalog,diagnostics_public,windows_native,windows_security,windows_probe,windows_smoke,windows_kit}.py`，汇总为一个TestSuite执行：115项，110通过、5 Windows原生条件跳过，0.851秒。复跑可对这些文件分别执行 `python3 -B -m unittest discover -s tools/tests -p 文件名`。
- 日志：`output/design-validation-20261022/docs.log`、`output/design-validation-20261022/foundation.log`。文档跳过为既有历史产物缺失条件项，原生跳过不能算Windows通过。没有重跑完整源码回归。

本轮只关闭V0及已有基础模块的V1验证范围。未实现模块的验证、Windows Smoke实测、完整G0、最终包G1、课程、外部/远程/容器运行验收均未完成。前轮用户Windows基础回传保留，不用本轮Mac测试替代。

无本轮真实VM、状态根或常驻测试进程待交接；未检查或操作用户其他实例。没有提交、推送、重新打包App或发布；历史发布版本沿用状态记录v0.1.2-preview.20261015，未查询远端。后续按设计V2入口处理Smoke回传和完整运行时，再推进受保护控制与监督；扩展按各自依赖实施后验证。

2026-10-23现场更正：上述89通过/5跳过对应新增本文件之前的docs.log；上一轮最终docs-final.log实际为88通过、1失败、5跳过，缺少快照标识，本轮复现后补齐。原始失败日志保留，修复后结果见当前状态第70节。
