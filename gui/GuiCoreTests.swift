// CTFLab 图形入口核心逻辑的单元测试（swiftc 直接编译运行，无需 XCTest）。
//
// 覆盖：状态机门禁、命令拼接（含空格路径）、清单/状态 JSON 解析、哈希失败阻断、
// 导入失败文案、重置确认门禁、分发目录文件识别。

import Foundation

var failureCount = 0
var checkCount = 0

func check(_ condition: Bool, _ name: String) {
    checkCount += 1
    if condition {
        print("ok   \(name)")
    } else {
        failureCount += 1
        print("FAIL \(name)")
    }
}

// MARK: 测试主体（@main 入口，避免 main.swift 命名限制）

func runAll() {

    var state = GuiState()
    check(!state.canImport, "未选择目录时导入禁用")
    check(!state.canStart, "未选择目录时启动禁用")
    check(!state.canReset, "未导入时重置禁用")

    state.distDir = "/tmp/with space/dist"
    check(state.canVerify, "选择目录后可校验")

    let okEntry = DistEntry(file: "kali-arm64-base.qcow2", profile: "kali-arm64", role: "base",
                            size: 100, expectedSize: 100, status: "ok", problem: nil)
    let badEntry = DistEntry(file: "smoke-base.qcow2", profile: "smoke", role: "base",
                             size: 90, expectedSize: 100, status: "sha256-mismatch",
                             problem: "SHA-256 不一致")
    let okReport = DistReport(ok: true, entries: [okEntry], problems: [],
                              summary: DistSummary(total: 1, ok: 1, failed: 0),
                              dir: state.distDir, manifest: "\(state.distDir!)/DISTRIBUTION.json")
    let badReport = DistReport(ok: false, entries: [badEntry], problems: ["smoke-base.qcow2: SHA-256 不一致"],
                               summary: DistSummary(total: 2, ok: 1, failed: 1),
                               dir: state.distDir, manifest: "\(state.distDir!)/DISTRIBUTION.json")

    state.report = badReport
    check(!state.canImport, "校验失败时导入禁用")
    // 启动只看状态目录的导入结果：镜像文件夹未校验不阻塞已导入节点启动。
    state.importedProfileIDs = [LabNode.kali.rawValue]
    state.selectedProfileID = LabNode.kali.rawValue
    check(state.canStart, "校验失败但节点已导入时仍可启动")
    state.importedProfileIDs = []
    state.selectedProfileID = nil
    check(state.report?.entries.first?.isOK == false, "失败条目状态可读")
    check(state.report?.entries.first?.statusText == "哈希不符", "失败状态中文文案")

    state.report = okReport
    // 真实 GUI 会从已校验清单写入本次课程的节点集合；这里显式模拟该步骤。
    state.configuredProfileIDs = Set(LabNode.required.map(\.rawValue))
    check(state.canImport, "校验通过后导入可用")
    check(!state.canStart, "未导入时启动仍禁用")

    state.importedProfileIDs = Set(LabNode.required.map(\.rawValue))
    check(state.allImported, "三个节点全部导入")
    state.selectedProfileID = LabNode.kali.rawValue
    check(state.canStart, "全部导入且未运行时启动可用")
    state.selectedProfileID = LabNode.smoke.rawValue
    check(state.canStartSelected, "可选择一个已导入靶机启动")
    state.selectedProfileID = nil
    check(!state.canStartSelected, "未选择节点时启动禁用")
    state.selectedProfileID = LabNode.kali.rawValue
    check(state.canReset, "全部导入后重置可用")
    check(!state.canStop, "未运行时停止禁用")

    state.runningProfileIDs = Set(LabNode.required.map(\.rawValue))
    check(state.canStop, "运行中停止可用")
    check(!state.canStart, "所选节点均运行时启动禁用")
    state.runningProfileIDs = [LabNode.kali.rawValue]
    state.selectedProfileID = LabNode.smoke.rawValue
    check(state.canStart, "Kali 运行时仍可单独启动 Smoke")
    state.selectedProfileID = LabNode.kali.rawValue
    check(state.canStopSelected, "当前选择的运行节点可停止")

    state.phase = .importing
    check(!state.canImport && !state.canReset && !state.canStop, "执行中所有动作禁用")
    check(state.phase.isBusy, "执行中标记为忙碌")
    state.phase = .idle

    check(state.importProgressText(index: 1, total: 3, profileID: LabNode.smoke.rawValue).contains("2/3"),
          "导入进度文案包含序号")

    // MARK: 命令拼接

    let spaced = CliAction.distVerify(dir: "/Users/student/课程 分发/dist")
    let spacedArgs = spaced.arguments(stateDir: "/Users/student/Library/Application Support/CTFLab")
    check(spacedArgs == ["--state-dir", "/Users/student/Library/Application Support/CTFLab",
                         "dist", "verify", "--dir", "/Users/student/课程 分发/dist", "--json"],
          "含空格路径保持为单个参数")

    let importArgs = CliAction.importNode(
        node: .kali,
        sourcePath: "/tmp/dir with space/kali-arm64-base.qcow2",
        manifestPath: "/tmp/dir with space/DISTRIBUTION.json").arguments()
    check(importArgs == ["import", "kali-arm64", "/tmp/dir with space/kali-arm64-base.qcow2",
                         "--manifest", "/tmp/dir with space/DISTRIBUTION.json"],
          "导入带基盘位置参数与 --manifest，路径含空格仍为单个参数")
    check(importArgs.count == 5, "导入命令参数个数固定（profile/source/--manifest/path）")

    let runArgs = CliAction.run(nodes: [.kali, .smoke]).arguments()
    check(runArgs == ["run", "kali-arm64", "smoke"], "启动所选节点并保持固定顺序")
    let targetOnlyArgs = CliAction.run(nodes: [.basic]).arguments()
    check(targetOnlyArgs == ["run", "basic-pentesting-2"], "可只启动一个靶机")
    let appendedArgs = CliAction.runProfiles(profileIDs: ["webserver", "smoke", "kali-arm64"],
                                               clipboard: false).arguments()
    check(appendedArgs == ["run", "kali-arm64", "smoke", "webserver"], "追加节点按稳定顺序启动")
    check(CliAction.stopProfiles(profileIDs: ["webserver"]).arguments() == ["stop", "webserver"],
          "可停止单个扩展节点")
    check(CliAction.stopAll.arguments() == ["stop", "--all"], "停止使用 stop --all")
    check(CliAction.status.arguments() == ["status", "--json"], "状态查询使用 JSON")
    check(CliAction.health(node: .smoke).arguments() == ["health", "smoke", "--json"], "健康检查按节点 JSON")
    check(CliAction.resetNode(node: .basic).arguments() == ["reset", "basic-pentesting-2"], "重置按节点")
    let inspectArgs = CliAction.inspectImage(sourcePath: "/tmp/legacy image.ova").arguments()
    check(inspectArgs == ["inspect", "/tmp/legacy image.ova", "--json"],
          "x86 向导先调用只读 inspect JSON，含空格路径不拆分")
    let onboardArgs = CliAction.onboardX86(sourcePath: "/tmp/legacy image.ova", profileID: "legacy-image").arguments()
    check(onboardArgs == ["onboard", "/tmp/legacy image.ova", "--id", "legacy-image", "--architecture", "x86_64"],
          "x86 向导只固定架构，不传任意 QEMU 参数")
    check(CliAction.probeProfile(profileID: "legacy-image", matrix: false).arguments()
          == ["probe", "legacy-image"], "首次启动探测不隐式运行矩阵")
    check(CliAction.probeProfile(profileID: "legacy-image", matrix: true).arguments()
          == ["probe", "legacy-image", "--matrix"], "回退矩阵必须由用户显式请求")
    check(CliAction.run(nodes: [.kali, .smoke]).arguments().allSatisfy { !$0.contains(" ") || $0.hasPrefix("/") },
          "参数中不含被拼接的裸命令")

    // MARK: JSON 解析

    let distJSON = """
    {"ok": true, "entries": [{"file": "kali-arm64-base.qcow2", "profile": "kali-arm64",
    "role": "base", "expected_size": 8103198720, "expected_sha256": "abc", "size": 8103198720,
    "sha256": "abc", "status": "ok", "problem": null}], "problems": [],
    "summary": {"total": 1, "ok": 1, "failed": 0}, "dir": "/tmp/d"}
    """
    let decoded = GuiParsing.decodeDistReport(distJSON)
    check(decoded?.ok == true, "解析分发校验 JSON")
    check(decoded?.entries.first?.size == 8103198720, "解析条目大小")
    check(GuiParsing.decodeDistReport("not json") == nil, "非法 JSON 返回 nil")

    let inspectionJSON = """
    {"source_path":"/tmp/legacy image.ova","format":"vmdk","virtual_size":4294967296,
     "source_sha256":"abc","candidate":{"architecture":"x86_64","firmware":"bios","machine":"pc",
     "memory_mb":2048,"cpus":2,"disk_bus":"scsi","disk_controller":"lsi53c895a","network_adapter":"pcnet"},
     "confidence":{"architecture":{"level":"medium","reason":"OVF"},"firmware":{"level":"high","reason":"MBR"},
     "disk":{"level":"medium","reason":"OVF"},"network":{"level":"low","reason":"unknown"}},
     "warnings":["未验证"]}
    """
    let inspection = GuiParsing.decodeInspection(inspectionJSON)
    check(inspection?.candidate.architecture == "x86_64", "解析只读镜像候选架构")
    check(inspection?.candidate.diskController == "lsi53c895a", "解析候选磁盘控制器")
    check(inspection?.confidence.network.level == "low", "解析候选置信度，不把推测当事实")
    check(GuiParsing.decodeInspection("not json") == nil, "非法镜像识别 JSON 返回 nil")
    check(ImageOnboardingRules.suggestedProfileID(sourcePath: "/tmp/Old Vulnerable_Box.ova") == "old-vulnerable-box",
          "从镜像名生成可编辑的安全配置 ID")
    check(ImageOnboardingRules.validProfileID("old-vulnerable-box"), "合法 x86 候选 ID 通过")
    check(!ImageOnboardingRules.validProfileID("Old_Box"), "不安全候选 ID 在 GUI 前置拦截")

    let statusJSON = """
    {"schema": 1, "state_dir": "/tmp/state", "profiles": [
     {"id": "kali-arm64", "name": "Kali", "imported": true, "running": true, "pid": 42,
      "log_path": "/tmp/log", "base_sha256": "aa", "stale_pid": null},
     {"id": "smoke", "imported": false, "running": false}]}
    """
    let status = GuiParsing.decodeStatus(statusJSON)
    check(status?.profiles.count == 2, "解析状态 JSON")
    check(status?.profiles.first?.running == true, "运行状态解析")
    check(status?.profiles.first?.logPath == "/tmp/log", "日志路径解析（snake_case 映射）")
    check(status?.profiles.last?.imported == false, "未导入状态解析")
    check(status?.profiles.first?.boot == nil, "无 boot 字段的旧状态 JSON 仍可解析")

    let bootStatusJSON = """
    {"schema": 1, "state_dir": "/tmp/state", "profiles": [
     {"id": "kali-arm64", "name": "Kali", "imported": true, "running": true, "pid": 42,
      "boot": {"phase": "guest-boot", "phase_label": "系统引导", "overall": "booting",
               "elapsed_seconds": 12, "readiness_timeout_seconds": 240,
               "stages": [{"name": "process", "ok": true, "detail": "PID 42"},
                          {"name": "guest-boot", "ok": true, "detail": "已出现来宾活动信号"},
                          {"name": "display", "ok": false, "detail": "等待显示通道就绪"},
                          {"name": "network", "ok": false, "detail": "健康检查未全部通过"}]}},
     {"id": "smoke", "imported": false, "running": false}]}
    """
    let bootStatus = GuiParsing.decodeStatus(bootStatusJSON)
    let boot = bootStatus?.profiles.first?.boot
    check(boot?.phase == "guest-boot", "启动阶段 phase 解析")
    check(boot?.phaseLabel == "系统引导", "启动阶段中文标签解析")
    check(boot?.overall == "booting", "启动整体状态解析")
    check(boot?.stages?.count == 4, "四阶段列表解析")
    check(boot?.stages?.first { $0.name == "display" }?.ok == false, "显示阶段未就绪解析")
    check(boot?.displayText.contains("系统引导（12s/240s）") == true, "阶段展示文案带计时")
    check(boot?.isTimedOut == false, "booting 不标记超时")

    let timeoutBootJSON = """
    {"schema": 1, "state_dir": "/tmp/state", "profiles": [
     {"id": "kali-arm64", "imported": true, "running": true, "pid": 42,
      "boot": {"phase": "process", "phase_label": "进程启动", "overall": "timeout",
               "elapsed_seconds": 300, "readiness_timeout_seconds": 240,
               "stages": [], "diagnosis": {
                   "message": "启动后 300s（就绪超时 240s）仍未就绪",
                   "failed_checks": ["dhcp", "ssh:22"],
                   "log_path": "/tmp/log", "client_log_path": "/tmp/client-log",
                   "hint": "查看日志；stop 仅作用于该节点。"}}}]}
    """
    let timeoutBoot = GuiParsing.decodeStatus(timeoutBootJSON)?.profiles.first?.boot
    check(timeoutBoot?.isTimedOut == true, "超时整体状态解析")
    check(timeoutBoot?.displayText.contains("超时") == true, "超时展示带标记")
    check(timeoutBoot?.diagnosis?.failedChecks == ["dhcp", "ssh:22"], "超时诊断失败项解析")
    check(timeoutBoot?.diagnosis?.clientLogPath == "/tmp/client-log", "超时诊断客户端日志路径解析")

    // 第 8 项：统一节点状态推导、搜索匹配与显示客户端列。
    func statusProfile(id: String, imported: Bool = true, importState: String? = "registered",
                       running: Bool = false, pid: Int? = nil, stalePid: Int? = nil,
                       bootOverall: String? = nil, bootPhase: String? = nil) -> StatusProfile {
        let boot: BootSummary? = bootOverall.map {
            BootSummary(phase: bootPhase ?? "process", phaseLabel: bootPhase ?? "进程启动",
                        overall: $0, elapsedSeconds: 5, readinessTimeoutSeconds: 240,
                        stages: [], diagnosis: nil)
        }
        return StatusProfile(id: id, name: nil, builtin: false, imported: imported, importState: importState,
                             sourcePath: nil, running: running, pid: pid, logPath: nil, baseSHA256: nil,
                             stalePid: stalePid, boot: boot, spiceClient: nil)
    }
    check(NodeOperationalState.state(for: statusProfile(id: "a", imported: false,
                                                        importState: "not-imported")) == .notImported,
          "未导入节点状态")
    check(NodeOperationalState.state(for: statusProfile(id: "a", imported: false,
                                                        importState: "missing-base")) == .baseMissing,
          "基盘失效节点状态")
    check(NodeOperationalState.state(for: statusProfile(id: "a")) == .stopped, "已导入未运行状态")
    check(NodeOperationalState.state(for: statusProfile(id: "a", running: true, pid: 7,
                                                        bootOverall: "booting")) == .booting,
          "启动中节点状态")
    check(NodeOperationalState.state(for: statusProfile(id: "a", running: true, pid: 7,
                                                        bootOverall: "ready",
                                                        bootPhase: "network")) == .running,
          "运行中节点状态")
    check(NodeOperationalState.state(for: statusProfile(id: "a", running: true,
                                                        bootOverall: "timeout")) == .timedOut,
          "启动超时节点状态")
    check(NodeOperationalState.state(for: statusProfile(id: "a", stalePid: 9)) == .stale,
          "状态残留优先于其他判定")
    check(NodeOperationalState.state(for: statusProfile(id: "a", running: true, pid: 7,
                                                        bootOverall: "timeout")).isProblem,
          "超时状态标记为问题")
    check(NodeOperationalState.detailText(for: statusProfile(id: "a", running: true,
                                                             bootOverall: "booting",
                                                             bootPhase: "display")).contains("display"),
          "启动中详情附带阶段标签")

    check(NodeSearch.matches(statusProfile(id: "kali-arm64", imported: false,
                                           importState: "not-imported"), query: "  "),
          "空搜索匹配全部节点")
    check(NodeSearch.matches(statusProfile(id: "basic-pentesting-2"), query: "BASIC"),
          "搜索按 ID 大小写不敏感匹配")
    check(NodeSearch.matches(statusProfile(id: "x"), query: "x"), "按显示名匹配未知节点")
    check(!NodeSearch.matches(statusProfile(id: "smoke"), query: "kali"), "不匹配的搜索被过滤")
    check(NodeSearch.filter([statusProfile(id: "kali-arm64"), statusProfile(id: "smoke")],
                            query: "kali").count == 1, "过滤结果数量正确")

    let clientJSON = """
    {"schema": 1, "state_dir": "/tmp/state", "profiles": [
     {"id": "kali-arm64", "imported": true, "running": true, "pid": 42,
      "boot": {"phase": "display", "phase_label": "显示连接", "overall": "booting",
               "elapsed_seconds": 6, "readiness_timeout_seconds": 240, "stages": []},
      "spice_client": {"pid": 99, "alive": true, "display_ready": true}},
     {"id": "smoke", "imported": false, "running": false, "spice_client": null}]}
    """
    let clientStatus = GuiParsing.decodeStatus(clientJSON)
    check(clientStatus?.profiles.first?.spiceClient?.displayReady == true, "显示客户端 display_ready 解析")
    check(clientStatus?.profiles.last?.spiceClient == nil, "非 SPICE 节点客户端列为空")
    check(SpiceClientStatus.columnText(clientStatus?.profiles.first?.spiceClient) == "已连接",
          "客户端列文案：已连接")
    check(SpiceClientStatus.columnText(nil) == "—", "客户端列文案：非 SPICE 显示 —")
    let connecting = SpiceClientStatus(pid: 9, alive: true, displayReady: false)
    check(SpiceClientStatus.columnText(connecting) == "连接中", "客户端列文案：连接中")
    let dead = SpiceClientStatus(pid: 9, alive: false, displayReady: false)
    check(SpiceClientStatus.columnText(dead) == "未连接", "客户端列文案：未连接")
    check(SpiceClientStatus.columnText(SpiceClientStatus(pid: 9, alive: false,
                                                       displayReady: true)) == "未连接",
          "客户端已退出时历史就绪不能覆盖未连接")
    let closedDisplayJSON = """
    {"profiles":[{"id":"kali-arm64","imported":true,"running":true,"pid":42,
      "spice_client":{"pid":99,"alive":false,"display_ready":false}}]}
    """
    if let closedProfile = GuiParsing.decodeStatus(closedDisplayJSON)?.profiles.first {
        check(DisplaySessionGuidance.message(for: closedProfile)?.contains("虚拟机仍在运行") == true,
              "显示退出提示保留虚拟机运行事实")
        check(DisplaySessionGuidance.actionTitle(for: closedProfile) == "重新打开显示窗口",
              "显示退出按钮提供恢复而不是重启")
        check(DisplaySessionGuidance.canReconnect(closedProfile), "运行中的 SPICE 节点可显式重连")
        check(DisplaySessionGuidance.loginHelp(for: closedProfile)?.contains("Kali User") == true,
              "Kali 登录说明区分显示名称")
        check(DisplaySessionGuidance.sleepHelp(for: closedProfile)?.contains("不能保证唤醒来宾") == true,
              "重开显示不能被宣称为唤醒来宾")
        check(DisplaySessionGuidance.sleepHelp(for: statusProfile(id: "smoke")) == nil,
              "Kali 睡眠边界不套用其他靶机")
    } else { check(false, "恢复提示测试 JSON 必须成功解码") }
    if let connectedProfile = clientStatus?.profiles.first {
        check(DisplaySessionGuidance.message(for: connectedProfile)?.contains("不代表已登录") == true,
              "已连接不能误报来宾已登录")
        check(DisplaySessionGuidance.actionTitle(for: connectedProfile) == "打开显示窗口",
              "已有客户端保持打开窗口动作")
    }
    check(DisplaySessionGuidance.message(for: statusProfile(id: "a")) == nil,
          "已停止节点不显示仍运行提示")
    check(!DisplaySessionGuidance.canReconnect(statusProfile(id: "a")), "停止或无 SPICE 的节点不提供重连按钮")
    check(DisplaySessionGuidance.loginHelp(for: statusProfile(id: "smoke")) == nil,
          "靶机不展示 Kali 登录说明")

    var library = NodeLibraryPreferences()
    let resourceJSON = """
    {"memory_mb": 2048, "cpus": 2, "cpu_percent": 130.5, "rss_mb": 600.2, "acceleration": "hvf"}
    """
    let resourceStatus = try! JSONDecoder().decode(NodeResourceStatus.self, from: Data(resourceJSON.utf8))
    check(resourceStatus.memoryMB == 2048 && resourceStatus.cpus == 2 && resourceStatus.cpuPercent == 130.5,
          "资源状态解析保留实际配置和多核 CPU 口径")
    let unknownResource = try! JSONDecoder().decode(NodeResourceStatus.self, from: Data("{}".utf8))
    check(unknownResource.rssMB == nil && unknownResource.cpuPercent == nil,
          "资源采样未知不转换为零")
    library.favorites.insert("smoke")
    library.setGroup("  Web 课程  ", for: "smoke")
    check(library.groups["smoke"] == "Web 课程", "分组去首尾空格保留内部空格")
    library.lastUsed["kali-arm64"] = Date(timeIntervalSince1970: 100)
    let savedCourse = NodeCourse(name: "  教学  ", profileIDs: ["smoke", "smoke", "kali-arm64"])
    library.courses.append(savedCourse)
    check(savedCourse.name == "教学" && savedCourse.profileIDs.count == 2, "课程名称与节点去重")
    let libraryData = try! JSONEncoder().encode(library)
    check((try! JSONDecoder().decode(NodeLibraryPreferences.self, from: libraryData)) == library,
          "收藏分组最近记录与课程持久化往返")
    let libraryNodes = [statusProfile(id: "kali-arm64"), statusProfile(id: "smoke")]
    check(library.ordered(libraryNodes, recentFirst: true).first?.id == "smoke", "收藏优先于最近使用")
    library.favorites.removeAll()
    check(library.ordered(libraryNodes, recentFirst: true).first?.id == "kali-arm64", "最近使用优先")
    check((try! CourseLaunchRules.pending(savedCourse, profiles: libraryNodes)).count == 2,
          "课程组合生成已导入待启动节点")
    check((try! CourseLaunchRules.pending(savedCourse, profiles: [statusProfile(id: "kali-arm64", running: true),
                                                               statusProfile(id: "smoke")])) == ["smoke"],
          "课程组合跳过已运行节点")
    do {
        _ = try CourseLaunchRules.pending(savedCourse, profiles: [statusProfile(id: "smoke")])
        check(false, "缺失课程节点必须拒绝")
    } catch { check(true, "缺失课程节点不部分执行") }
    do {
        _ = try CourseLaunchRules.pending(NodeCourse(name: "", profileIDs: ["smoke"]), profiles: libraryNodes)
        check(false, "空名称组合必须拒绝")
    } catch { check(true, "拒绝空名称组合") }

    let healthJSON = """
    {"schema": 1, "profile": "kali-arm64", "ok": false,
     "checks": [{"name": "ssh:22", "ok": false, "detail": "连接失败"}]}
    """
    let health = GuiParsing.decodeHealth(healthJSON)
    check(health?.ok == false, "解析健康检查 JSON")
    check(health?.checks.first?.detail == "连接失败", "健康检查明细")
    check(health?.isPending == false, "明确失败不显示为等待")

    let pendingHealth = GuiParsing.decodeHealth("""
    {"schema": 1, "profile": "kali-arm64", "ok": true, "pending": true,
     "checks": [{"name": "dhcp", "ok": null, "detail": "启动中"}]}
    """)
    check(pendingHealth?.isPending == true, "健康检查 pending 不显示为通过")

    // MARK: 错误文案

    let failure = GuiMessages.failureMessage(action: "导入 Kali", exitCode: 2,
                                             output: "错误：来源校验失败\n（SHA-256 不一致）")
    check(failure.contains("退出码 2"), "错误文案包含退出码")
    check(failure.contains("SHA-256 不一致"), "错误文案保留 CLI 原文")
    check(GuiMessages.resetConfirmationBody.contains("overlay"), "重置确认说明 overlay 影响")
    check(GuiMessages.resetConfirmationBody.contains("丢失"), "重置确认说明改动会丢失")
    check(GuiMessages.verifyFailedBanner.contains("禁用"), "校验失败横幅说明按钮禁用")

    // MARK: 重置门禁

    var resetState = GuiState()
    resetState.configuredProfileIDs = Set(LabNode.required.map(\.rawValue))
    resetState.importedProfileIDs = Set(LabNode.required.map(\.rawValue))
    check(ResetGate.plan(state: resetState, confirmed: false) == nil, "未确认时不产生重置命令")
    let plan = ResetGate.plan(state: resetState, confirmed: true)
    check(plan?.count == 3, "确认后按节点逐个重置")
    check(plan?.first == .resetProfile(profileID: LabNode.kali.rawValue), "重置顺序从 Kali 开始")

    let notImported = GuiState()
    check(ResetGate.plan(state: notImported, confirmed: true) == nil, "未导入时即使确认也不重置")

    // MARK: .app 内 CLI 路径

let bundle = URL(fileURLWithPath: "/Applications/CTFLab.app")
check(AppLayout.cliPath(bundleURL: bundle)
      == "/Applications/CTFLab.app/Contents/Resources/bin/ctflab-cli",
      "GUI 调用的 CLI 位于 Resources/bin（与打包工具一致）")
check(!AppLayout.cliRelativePath.hasPrefix("/"), "CLI 相对路径不得以 / 开头")

// MARK: 分发目录识别（含空格路径）

    let tempDir = URL(fileURLWithPath: NSTemporaryDirectory())
        .appendingPathComponent("ctflab gui test")
    try? FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
    let layout = DistributionLayout(dir: tempDir.path)
    try? "{}".write(toFile: layout.manifestPath, atomically: true, encoding: .utf8)
    let detection = layout.detect()
    check(detection.found.contains("DISTRIBUTION.json"), "识别 DISTRIBUTION.json（空格路径）")
    check(!detection.missing.contains("DISTRIBUTION.json"), "清单存在不报缺失")
    check(layout.manifestPath.hasSuffix("ctflab gui test/DISTRIBUTION.json"), "清单路径拼接正确")

    // 清单可解析时列出载荷文件并解析各节点基盘
    let manifestJSON = """
    {"entries": [
      {"file": "kali-arm64-base.qcow2", "profile": "kali-arm64", "role": "base"},
      {"file": "kali-arm64-uefi-vars.fd", "profile": "kali-arm64", "role": "nvram"},
      {"file": "smoke-base.qcow2", "profile": "smoke", "role": "base"},
      {"file": "basic-pentesting-2-base.qcow2", "profile": "basic-pentesting-2", "role": "base"}]}
    """
    try? manifestJSON.write(toFile: layout.manifestPath, atomically: true, encoding: .utf8)
    let payloads = layout.expectedPayloadPaths()
    check(payloads.count == 4, "从清单解析四个载荷文件（三基盘 + NVRAM）")
    check(payloads.contains { $0.hasSuffix("kali-arm64-uefi-vars.fd") }, "识别 Kali NVRAM 路径")
    check(layout.basePath(for: .kali)?.hasSuffix("kali-arm64-base.qcow2") == true,
          "从清单解析 Kali 基盘路径")
    check(layout.basePath(for: .smoke)?.hasSuffix("smoke-base.qcow2") == true,
          "从清单解析 Smoke 基盘路径")
    check(layout.basePath(for: .basic)?.hasSuffix("basic-pentesting-2-base.qcow2") == true,
          "从清单解析 Basic 基盘路径")
    check(layout.baseProfileIDs() == ["kali-arm64", "smoke", "basic-pentesting-2"],
          "分发清单可列出可管理的所有基盘节点")
    check(layout.basePath(forProfileID: "basic-pentesting-2")?.hasSuffix("basic-pentesting-2-base.qcow2") == true,
          "扩展管理路径按 profile ID 解析基盘")
    let rootURL = URL(fileURLWithPath: layout.dir).standardizedFileURL
    let baseURL = URL(fileURLWithPath: layout.basePath(for: .kali) ?? "").standardizedFileURL
    check(baseURL.path.hasPrefix(rootURL.path + "/"),
          "基盘路径位于所选分发目录内")

    let escapeManifest = """
    {"entries": [{"file": "../outside.qcow2", "profile": "kali-arm64", "role": "base"}]}
    """
    try? escapeManifest.write(toFile: layout.manifestPath, atomically: true, encoding: .utf8)
    check(layout.basePath(for: .kali) == nil, "清单越界基盘路径被拒绝")

    try? FileManager.default.removeItem(at: tempDir)

    // MARK: 登记标签去重（同名登记附 ID）与镜像文件夹扫描

    check(LabNode.displayLabel(for: "kali-arm64") == "Kali Linux ARM64（kali-arm64）",
          "已知课程节点显示名附 ID")
    check(LabNode.displayLabel(for: "unnamed-node") == "unnamed-node",
          "登记名与 ID 相同时不加后缀")
    check(LabNode.displayLabel(for: "kali-arm64", name: "Webserver") == "Webserver（kali-arm64）",
          "登记名与 ID 不同时附 ID")
    check(LabNode.displayLabel(for: "webserver-e2e", name: "Webserver") == "Webserver（webserver-e2e）",
          "历史同名登记通过 ID 后缀区分")

    let scanDir = URL(fileURLWithPath: NSTemporaryDirectory())
        .appendingPathComponent("ctflab gui scan test")
    try? FileManager.default.createDirectory(at: scanDir, withIntermediateDirectories: true)
    for name in ["b.vmdk", "a.QCOW2", "notes.txt", "c.ova"] {
        FileManager.default.createFile(atPath: scanDir.appendingPathComponent(name).path,
                                       contents: Data([0x01]))
    }
    let scanned = ImageFolderScanner.scan(scanDir.path)
    check(scanned.map(\.fileName) == ["a.QCOW2", "b.vmdk", "c.ova"],
          "只扫描支持的镜像扩展名并按名称排序")
    check(ImageFolderScanner.scan("/definitely/not/exist/ctflab") == [],
          "不存在的目录返回空（空文件夹为合法状态）")
    try? FileManager.default.removeItem(at: scanDir)

    check(CliAction.deregisterProfile(profileID: "webserver-e2e").arguments()
          == ["deregister", "webserver-e2e"], "移除登记命令拼接")

    check(CliAction.runProfiles(profileIDs: ["kali-arm64"], clipboard: true).arguments()
          == ["run", "kali-arm64", "--clipboard"], "剪贴板共享打开时附加 --clipboard")
    check(CliAction.runProfiles(profileIDs: ["kali-arm64"], clipboard: false,
                                displayQuality: "smooth").arguments()
          == ["run", "kali-arm64", "--display-quality", "smooth"], "清晰度参数透传")
    check(CliAction.onboardAuto(sourcePath: "/tmp/a/kali-base.qcow2", profileID: "kali-base")
          .arguments() == ["onboard", "/tmp/a/kali-base.qcow2", "--id", "kali-base"],
          "自动导入不带架构参数（由 inspect 推断）")
    check(ImageOnboardingRules.availableProfileID(sourcePath: "/tmp/smoke.qcow2",
          existingIDs: ["smoke"]) == "smoke-2", "仅登记同名节点不隐藏新来源")
    check(ImageOnboardingRules.availableProfileID(sourcePath: "/tmp/smoke.vmdk",
          existingIDs: ["smoke", "smoke-2"]) == "smoke-3", "同批导入 ID 不重复")
    check(ImageOnboardingRules.validProfileID(ImageOnboardingRules.availableProfileID(
          sourcePath: "/tmp/" + String(repeating: "a", count: 49) + ".qcow2",
          existingIDs: [String(repeating: "a", count: 49)])), "碰撞后 ID 仍在长度边界内")
    check(CliAction.runProfiles(profileIDs: ["kali-arm64"], clipboard: false,
          fileTransfer: true).arguments() == ["run", "kali-arm64", "--file-transfer"],
          "文件传输不隐式开启剪贴板")
    let pendingNodes = try! JSONDecoder().decode(StatusReport.self, from: Data("""
      {"profiles":[{"id":"smoke","imported":false,"running":false},
        {"id":"old","imported":true,"running":false,"source_path":"/tmp/old.qcow2"}],
        "state_dir":"/tmp/state"}
      """.utf8)).profiles
    let pendingFiles = [ImageLibraryEntry(fileName: "smoke.qcow2", path: "/tmp/smoke.qcow2", sizeBytes: 1),
                        ImageLibraryEntry(fileName: "old.qcow2", path: "/tmp/old.qcow2", sizeBytes: 1)]
    check(ImageOnboardingRules.pendingImages(pendingFiles, nodes: pendingNodes).map(\.fileName)
          == ["smoke.qcow2"], "仅过滤已导入来源，不过滤未导入的登记 ID")
    check(CliAction.removeImage(profileID: "smoke").arguments() == ["remove", "smoke"],
          "删除镜像命令拼接")

    let builtinStatusJSON = """
    {"profiles": [{"id": "webserver", "name": "Webserver", "builtin": true,
                   "imported": false, "running": false},
                  {"id": "webserver-e2e", "name": "Webserver", "builtin": false,
                   "imported": false, "running": false}], "state_dir": "/tmp/x"}
    """
    if let data = builtinStatusJSON.data(using: .utf8),
       let report = try? JSONDecoder().decode(StatusReport.self, from: data) {
        check(report.profiles.count == 2, "状态报告解析两个登记")
        check(report.profiles.first { $0.id == "webserver" }?.builtin == true,
              "内置课程包 builtin 标记可解析")
        check(report.profiles.first { $0.id == "webserver-e2e" }?.builtin == false,
              "用户登记 builtin=false 可解析")
    } else {
        check(false, "状态报告 builtin 字段解析失败")
    }

    check(RecoveryRules.validName("before-1") && !RecoveryRules.validName("../bad"), "恢复点名称拒绝路径")
    check(RecoveryRules.validName(RecoveryRules.checkpointName()), "自动保护点名称合法")
    check(CliAction.snapshot(profileID: "smoke", operation: "list").arguments()
          == ["snapshot", "list", "smoke", "--json"], "恢复点列表使用 JSON")
    let backupArgs = CliAction.backupReset(profileID: "smoke").arguments()
    check(backupArgs.count == 4 && RecoveryRules.validName(backupArgs[3]), "备份重置附安全名称")
    let stableBackup = CliAction.backupReset(profileID: "smoke")
    check(stableBackup.arguments() == stableBackup.arguments(), "备份命令与日志使用同一名称")
    check(CliAction.showDisplay(profileID: "smoke").arguments() == ["show", "smoke"], "打开显示不会拼接 run")
    check(CliAction.reconnectDisplay(profileID: "kali-arm64").arguments() == ["show", "kali-arm64", "--reconnect"], "卡住恢复仅重连显示")
    check(CliAction.runProfiles(profileIDs: ["kali-arm64"], clipboard: false, resourcePreset: "light")
          .arguments().suffix(2) == ["--resource-preset", "light"], "资源档位与显示权限独立")
    check(NodeStatusFilter.active.matches(statusProfile(id: "smoke", running: true)), "运行状态筛选")
    check(!NodeStatusFilter.active.matches(statusProfile(id: "smoke")), "不运行的节点不混入运行筛选")
    check(NodeStatusFilter.problems.matches(statusProfile(id: "smoke", imported: false, importState: "missing-base")), "基盘失效仍可被问题筛选找到")
    check(CliAction.preflight(profileID: "kali-arm64", resourcePreset: "light").arguments() == ["preflight", "kali-arm64", "--resource-preset", "light"], "预检保留选中节点资源档位")
    check(CliAction.displayDiagnose(profileID: "smoke").arguments() == ["display-diagnose", "smoke"], "诊断只针对选中节点")
    check(CliAction.updateRollback.arguments() == ["update", "rollback"], "回退不混入停止或重置命令")
    let failedPreflight = PreflightReport.decode("启动失败\n{\"ok\":false,\"checks\":[{\"name\":\"disk\",\"ok\":false,\"detail\":\"旧基盘\",\"hint\":\"先备份\"}]}")
    check(failedPreflight?.guidance.contains("先备份") == true, "错误包装后的预检提示可读")
    print("---")
    print("共 \(checkCount) 项检查，失败 \(failureCount) 项")
    exit(failureCount == 0 ? 0 : 1)
    }

@main
struct GuiCoreTestRunner {
    static func main() {
        runAll()
    }
}
