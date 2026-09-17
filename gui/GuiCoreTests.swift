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
    check(!state.canStart, "校验失败时启动禁用")
    check(state.report?.entries.first?.isOK == false, "失败条目状态可读")
    check(state.report?.entries.first?.statusText == "哈希不符", "失败状态中文文案")

    state.report = okReport
    check(state.canImport, "校验通过后导入可用")
    check(!state.canStart, "未导入时启动仍禁用")

    state.importedProfileIDs = Set(LabNode.required.map(\.rawValue))
    check(state.allImported, "三个节点全部导入")
    check(state.canStart, "全部导入且未运行时启动可用")
    state.selectedProfileIDs = Set([LabNode.kali.rawValue, LabNode.smoke.rawValue])
    check(state.canStartSelected, "可只选择 Kali 与一个靶机启动")
    state.selectedProfileIDs = []
    check(!state.canStartSelected, "未选择节点时启动禁用")
    state.selectedProfileIDs = Set(LabNode.required.map(\.rawValue))
    check(state.canReset, "全部导入后重置可用")
    check(!state.canStop, "未运行时停止禁用")

    state.runningProfileIDs = Set(LabNode.required.map(\.rawValue))
    check(state.canStop, "运行中停止可用")
    check(!state.canStart, "所选节点均运行时启动禁用")
    state.runningProfileIDs = [LabNode.kali.rawValue]
    state.selectedProfileIDs = Set([LabNode.kali.rawValue, LabNode.smoke.rawValue])
    check(state.canStart, "Kali 运行时仍可追加启动 Smoke")
    check(state.startableSelectedProfileIDs == Set([LabNode.smoke.rawValue]), "启动时自动略过已运行节点")

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
    let appendedArgs = CliAction.runProfiles(profileIDs: ["webserver", "smoke", "kali-arm64"]).arguments()
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
