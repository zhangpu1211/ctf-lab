# CTFLab 0.1.4 双端界面与预览交付（2026-10-30）

## 本轮目标与交付范围

用户确认优先交付稳定操作与恢复、拓扑编辑、诊断导出和Windows安装入口，并要求整体美化、复核Apple设计理念。后续确认暂无Windows原生构建环境，因此本轮交付Mac可执行预览与Windows最新版构建源码材料；不能把Windows源码ZIP标为安装包或已完成双端原生发布。完整AD/Docker课程、真实课堂、G0/G1及稳定版继续单列。

版本统一为0.1.4，预览标签为`v0.1.4-preview.20261030`。旧0.1.3 App、原Mac更新器、镜像和运行数据保留。发布资产中的源码快照对应本轮工作区；未自动提交或推送，标签所指旧Git提交不包含全部新实现。

## 设计复核与实际调整

依据Apple官方[macOS设计](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos/)、[布局](https://developer.apple.com/design/human-interface-guidelines/layout)与[侧栏](https://developer.apple.com/design/human-interface-guidelines/sidebars)要求，采用内容优先、清晰层级、原生导航、系统字体、语义色和可访问交互。这里是项目设计判断，不是Apple认证。

| 对象 | 改动 |
|---|---|
| Mac主窗口 | 原固定460点镜像列改为原生NavigationSplitView，侧栏280—400点可调整并可收起；详情独立滚动，避免长内容挤压入口。 |
| Mac内容层级 | 统一工作台标题、状态副文、材质标签及14点圆角操作面板；列表图文合并为可访问元素，空状态说明下一步。 |
| Windows工作台 | 去除深绿/衬线/装饰箭头，统一系统字体、中性色、蓝色强调、线性图标、卡片与表单；实验、拓扑、模板、远程、版本、诊断共用设计变量。 |
| 外观与辅助功能 | Web工作台支持自动/浅色/深色，保存的只是外观偏好；提供清晰键盘焦点、高对比度、减少透明和减少动态样式。Mac沿用系统外观和原生控件。 |
| 交互边界 | 视觉调整保留原门禁、未知状态、明确重置确认与原请求查询；不会因打开窗口自动启动、停止或重置实验。 |

导航材质与内容层分开。Mac由系统绘制原生侧栏与材质；Windows使用对应视觉语言，不声称实现Apple原生Liquid Glass。外观不是运行/服务/隔离验收的替代。

## 本轮带入的功能

Mac新包纳入0.1.3之后的当前运行源码，包括有界桥接/等待、日志恢复与状态观测、匿名诊断预览保存、缓存/公共存储池相关能力、VMGenID可选绑定和取证工作区模块。具体平台入口与条件仍以各功能文档为准：模块随包并不表示所有功能都有Mac主窗口按钮，或已完成真实来宾测试。

Windows构建材料包含原请求历史恢复、实际事件数组/裁剪后续读修复、准备进度、拓扑编辑、首次私有版本库设置和最新界面。`Build-Windows.ps1`补充暂存返回摘要→探测/构建前后核对，启用PE静态依赖检查，并使用每轮独立Cargo输出目录收集安装器，避免把旧exe误报为新包。它不自动配置系统虚拟化、网络、磁盘或运行VM。

原材料清单中不存在的A01 r3文件引用已移除，准备进度说明按现有代码与日期化证据补齐。r2审计JSON保持历史快照，本轮源码变化不自动更新原审计结论。新版由发布清单逐文件绑定。

## Windows构建入口

本轮没有生成Windows EXE。需要原生Windows x64、Rust1.90工具链/编译依赖、Node及合法固定Python/QEMU来源和清单；离线WebView2安装依赖亦需实际准备。不得通过修改固定摘要绕过来源核验。

在解压源码中的`desktop`目录执行（参数替换为实际已核验目录）：

```powershell
.\Build-Windows.ps1 -PythonRoot 'C:\ctflab-inputs\python' -QemuRoot 'C:\ctflab-inputs\qemu' -QemuInventory 'C:\ctflab-inputs\qemu-inventory.json' -BuildRoot 'C:\ctflab-builds\preview-0.1.4-new'
```

BuildRoot须为源目录与输入运行时之外的全新目录。脚本保留暂存摘要、探测收据、独立编译目录及`installers/`和`installer-results.json`。未签名、未测与失败保留原样；成功构建也不证明安装/卸载、迁移回退、干净机、显示或课程通过。安装器实际生成后再进行原生测试和单独发布，不上传旧候选冒充本版。

## 验证与限制

最终命令、结果和资产摘要见状态第139节与`output/dual-release-20261030/final-evidence.json`。浏览器预览只检查界面，浏览器没有Tauri原生桥接，不能在其中完成实验或远程连接。Mac原生窗口检查与源码/构建验证分开记录。没有本轮真实VM、SSH、Docker、AD、课程课堂、睡眠或长期负载验收。
