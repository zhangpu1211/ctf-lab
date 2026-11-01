// CTFLab 图形入口（SwiftUI/AppKit，课堂 App 与随包运行时统一要求 macOS 26.0+）。
//
// 只做三件事：驱动现有 CLI（dist verify / import --manifest / run / status / health /
// stop --all / reset）、展示结果、按状态机门禁按钮。所有业务逻辑在 GuiCore.swift。

import AppKit
import SwiftUI

struct PublicDiagnosticsSheet: View {
    @ObservedObject var model: GuiModel
    let snapshot: MacPublicDiagnostics
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("分享诊断摘要").font(.title2)
            Text("只包含软件版本、系统类型和匿名节点阶段。摘要来自当前列表快照，可能已过期，不代表来宾或服务验收。")
            Text("下方内容就是将保存的完整文件。不会包含路径、账号、节点原名、进程号或日志，也不会自动上传。")
                .font(.caption).foregroundStyle(.secondary)
            ScrollView {
                Text(snapshot.text).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }.frame(minHeight: 320)
            if !model.publicDiagnosticsError.isEmpty { Text(model.publicDiagnosticsError).foregroundStyle(.red) }
            HStack {
                Spacer()
                Button("关闭") { model.publicDiagnostics = nil }
                Button("保存此预览…") { model.savePublicDiagnostics(snapshot) }.keyboardShortcut(.defaultAction)
            }
        }.padding(20).frame(width: 680, height: 500)
    }
}

// MARK: - 运行模型

@MainActor
final class GuiModel: ObservableObject {
    @Published var publicDiagnostics: MacPublicDiagnostics?
    @Published var publicDiagnosticsError = ""
    @Published var sceneGeneric = true
    @Published var sceneRuntimeProfile = ""
    @Published var sceneLocalView: MacRemoteJSON?
    @Published var sceneExternalAttach: MacRemoteJSON?
    @Published var sceneAttachForm: [String: String] = [:]
    @Published var showScenarioWorkspace = false
    @Published var sceneInstance = UUID().uuidString.lowercased()
    @Published var sceneManifest = ""
    @Published var sceneManifestSHA = ""
    @Published var sceneAssets: [String: String] = [:]
    @Published var sceneFirmware: [String: [String]] = [:]
    @Published var scenePlan: MacRemoteJSON?
    @Published var sceneSourceManifest: MacRemoteJSON?
    @Published var sceneReply: MacRemoteJSON?
    @Published var sceneSnapshot: String?
    @Published var sceneDraft: MacRemoteJSON = .null
    @Published var sceneDraftDiff: MacRemoteJSON = .null
    @Published private(set) var sceneDraftHistory: MacGraphHistory?
    @Published var sceneDraftContext = ""
    @Published var sceneGraphOpen = false
    @Published var sceneDraftNodeName = ""
    @Published var sceneDraftAsset = ""
    @Published var sceneDraftNetworkName = ""
    @Published var sceneDraftCIDR = ""
    @Published var sceneHistory: [MacSavedOperation] = []
    @Published var sceneHistoryHasNext = false
    @Published var sceneHistoryRecord: MacSavedRecord?
    @Published var sceneEvents: [MacRemoteJSON] = []
    @Published var sceneEventNotice = ""
    private var sceneHistoryNext: String?
    private var sceneEventCursor = 0
    private var sceneDraftRevision = 0
    private var sceneLastRequest: MacRemoteJSON?
    private var sceneCallTicket: UUID?
    @Published var sceneWorkspaceBusy = false
    @Published var sceneEmulation = false
    @Published var sceneNewGeneration = "2"
    @Published var sceneMessage = "先选择场景清单查看设计；读取状态不会准备或启动。"
    @Published var showRemoteWorkspace = false
    @Published var remoteTargets: [MacSavedTarget] = []
    @Published var remoteSelected = ""
    @Published var remoteConfig = ""
    @Published var remoteLabel = ""
    @Published var remoteWizard = ["host": "", "port": "22", "user": "", "server_uuid": "", "identity": "", "known_hosts": ""]
    @Published var remoteContext: MacRemoteContext?
    @Published var remoteInstance = ""
    @Published var remoteView: MacRemoteJSON = .null
    @Published var remoteLeases: MacRemoteJSON = .null
    @Published var remoteLease = ""
    @Published var remoteTTL = "1800"
    @Published var remoteStopConsent = false
    @Published var remotePending: [MacRemoteJSON] = []
    @Published var remotePendingKnown = false
    @Published var remoteAdminOpen = false
    @Published var remoteOffers: [MacRemoteJSON] = []
    @Published var remoteOffer = ""
    @Published var remoteCourseInstance = ""
    @Published var remoteCoursePlan: MacRemoteJSON = .null
    @Published var remoteAudit: MacRemoteJSON = .null
    @Published var remoteAuditPlan: MacRemoteJSON = .null
    @Published var remoteBusy = false
    @Published var remoteMessage = "读取保存列表不会连接服务器。"
    @Published var remoteConnectionID: String?
    @Published var remoteUploads: [MacRemoteJSON] = []
    @Published var remoteDownloads: [MacRemoteJSON] = []
    @Published var remoteExports: [MacRemoteJSON] = []
    @Published var remoteAssetFile = ""
    @Published var remoteAssetSource = ""
    @Published var remoteTransferID: (kind: String, id: String)?
    private var remoteEpoch = 0
    private var remoteHistoryInFlight = false
    @Published var state = GuiState()
    @Published var log: String = ""
    @Published var verifyRows: [DistEntry] = []
    @Published var nodes: [StatusProfile] = []
    @Published var nodeSearchText = ""
    @Published var nodeStatusFilter = NodeStatusFilter.all
    @Published var displayDiagnosis = [String: String]()
    @Published var courseResults = [String: String]()
    @Published var updateMessage = ""
    @Published var libraryPreferences = NodeLibraryPreferences()
    @Published var favoritesOnly = false
    @Published var recentFirst = true
    @Published var groupFilter = ""
    @Published var groupDrafts: [String: String] = [:]
    @Published var showCourseManager = false
    @Published var courseDraftName = ""
    @Published var courseDraftSelected = Set<String>()
    @Published var pendingCourse: NodeCourse?
    @Published var showCourseConfirmation = false
    @Published var stopImportQueueRequested = false
    @Published var imageLibrary: [ImageLibraryEntry] = []
    @Published var deregisterTargets: Set<String> = []
    /// 左侧列表当前选中的文件夹镜像（与节点选择互斥）。
    @Published var selectedFilePath: String?
    @Published var showNodeResetConfirmation = false
    @Published var scenarioReports: [ScenarioReport] = []
    @Published var scenarioBusy = false
    @Published var scenarioReadError: String?
    @Published var showScenarioStopConfirmation = false
    @Published var nodeResetTarget: String?
    @Published var showImageRemoveConfirmation = false
    @Published var imageRemoveTarget: String?
    /// CLI 输出面板默认收起（视图状态放模型里，避免命令行 swiftc 的宏限制）。
    @Published var cliLogExpanded = false
    /// 文本剪贴板共享（显式授权项）：记忆在用户默认值里，跨启动沿用。
    @Published var clipboardSharingEnabled: Bool {
        didSet { UserDefaults.standard.set(clipboardSharingEnabled, forKey: "CTFLabClipboardSharing") }
    }
    @Published var fileTransferEnabled: Bool {
        didSet { UserDefaults.standard.set(fileTransferEnabled, forKey: "CTFLabFileTransfer") }
    }
    private var reservedImportIDs: Set<String> = []
    /// 显示清晰度：smooth=1:1 逻辑分辨率（UI 正常大小，默认）；
    /// sharp=Retina 像素密度（更精细但 UI 更小）。记忆在用户默认值。
    @Published var displayQualitySharp: Bool {
        didSet { UserDefaults.standard.set(displayQualitySharp, forKey: "CTFLabDisplayQualitySharp") }
    }
    @Published var resourcePreset = "original"

    init() {
        clipboardSharingEnabled = UserDefaults.standard.bool(forKey: "CTFLabClipboardSharing")
        fileTransferEnabled = UserDefaults.standard.bool(forKey: "CTFLabFileTransfer")
        displayQualitySharp = UserDefaults.standard.bool(forKey: "CTFLabDisplayQualitySharp")
        let scope = ProcessInfo.processInfo.environment["CTFLAB_GUI_STATE_DIR"] ?? "default"
        if let data = UserDefaults.standard.data(forKey: "CTFLabLibrary:\(scope)"),
           let preferences = try? JSONDecoder().decode(NodeLibraryPreferences.self, from: data) {
            libraryPreferences = preferences
        }
    }
    @Published var showResetConfirmation = false
    @Published var showImageOnboarding = false
    @Published var onboardingSourcePath = ""
    @Published var onboardingProfileID = ""
    @Published var onboardingReport: ImageInspectionReport?
    @Published var onboardingImportedProfileID: String?
    @Published var onboardingMatrixReportPath: String?
    @Published var onboardingMatrixReviewAttempt: Int?
    @Published var onboardingMatrixScreenshotPath: String?
    @Published var showMatrixApplyConfirmation = false
    @Published var importCanCancel = false
    private var activeImportControl: URL?
    private var retryCandidate: (id: String, source: String)?

    var canRetryOnboarding: Bool {
        retryCandidate?.id == onboardingProfileID && retryCandidate?.source == onboardingSourcePath
    }

    func cancelCurrentImport() {
        guard importCanCancel, let directory = activeImportControl else { return }
        do {
            try Data().write(to: directory.appendingPathComponent("cancel"), options: .atomic)
            stopImportQueueRequested = true
            importCanCancel = false
            state.progressText = "正在安全取消；发布已开始时将先完成本项登记…"
        } catch {
            state.lastError = "无法请求安全取消：\(error.localizedDescription)"
        }
    }
    @Published var onboardingMessage = ""
    @Published var showRecovery = false
    @Published var recoveryProfileID = ""
    @Published var recoveryName = ""
    @Published var recoverySnapshots: [RecoverySnapshot] = []
    @Published var recoveryBackups: [RecoveryBackup] = []
    @Published var recoveryPending: CliAction?
    @Published var showRecoveryConfirmation = false
    private var statusRefreshInFlight = false
    private var lastAutomaticRefresh = Date.distantPast

    /// 状态目录覆盖（仅用于测试/隔离验收；学生双击运行时使用 CLI 默认目录）。
    private let stateDirOverride = ProcessInfo.processInfo.environment["CTFLAB_GUI_STATE_DIR"]
    /// CLI 入口覆盖（仅用于测试）；默认取 .app 内的 ctflab-cli。
    private let cliOverride = ProcessInfo.processInfo.environment["CTFLAB_GUI_CLI"]

    var cliPath: String {
        if let cliOverride, !cliOverride.isEmpty { return cliOverride }
        return AppLayout.cliPath(bundleURL: Bundle.main.bundleURL)
    }

    var stateDirLabel: String {
        stateDirOverride ?? "~/Library/Application Support/CTFLab（默认）"
    }

    func saveLibraryPreferences() {
        guard let data = try? JSONEncoder().encode(libraryPreferences) else { return }
        UserDefaults.standard.set(data, forKey: "CTFLabLibrary:\(stateDirOverride ?? "default")")
    }

    func toggleFavorite(_ id: String) {
        if libraryPreferences.favorites.contains(id) { libraryPreferences.favorites.remove(id) }
        else { libraryPreferences.favorites.insert(id) }
        saveLibraryPreferences()
    }

    func recordUse(_ id: String) {
        libraryPreferences.lastUsed[id] = Date()
        saveLibraryPreferences()
    }

    func requestCourseStart(_ course: NodeCourse) {
        guard !state.phase.isBusy else { return }
        state.lastError = nil
        pendingCourse = nil
        do {
            let pending = try CourseLaunchRules.pending(course, profiles: nodes)
            guard !pending.isEmpty else { state.lastError = "这个组合已全部运行，无需重复启动。"; return }
            pendingCourse = NodeCourse(name: course.name, profileIDs: pending, id: course.id)
            showCourseConfirmation = true
        } catch { state.lastError = error.localizedDescription }
    }

    func confirmCourseStart() {
        guard !state.phase.isBusy, let course = pendingCourse else { return }
        pendingCourse = nil
        do {
            let pending = try CourseLaunchRules.pending(course, profiles: nodes)
            state.lastError = nil
            state.phase = .busy
            courseResults = Dictionary(uniqueKeysWithValues: pending.map { ($0, "等待启动") })
            startCourseSequence(pending, index: 0)
        } catch { state.lastError = error.localizedDescription }
    }

    private func startCourseSequence(_ ids: [String], index: Int) {
        guard index < ids.count else {
            state.phase = .idle; state.progressText = ""
            refreshStatus(); return
        }
        let id = ids[index]
        state.progressText = "启动课程组合：\(id)（\(index + 1)/\(ids.count)）"
        run(.runProfiles(profileIDs: [id], clipboard: id == "kali-arm64" && clipboardSharingEnabled,
                         displayQuality: displayQualitySharp ? "sharp" : "smooth",
                         fileTransfer: id == "kali-arm64" && fileTransferEnabled,
                         resourcePreset: id == "kali-arm64" && resourcePreset != "original" ? resourcePreset : nil)) { [weak self] outcome in
            guard let self else { return }
            if case .failure(let message) = outcome {
                self.courseResults[id] = "启动失败"
                for remaining in ids.dropFirst(index + 1) { self.courseResults[remaining] = "未启动（前项失败）" }
                self.state.phase = .failed; self.state.progressText = ""
                self.state.lastError = "组合启动在 \(id) 处停止；已启动节点保持运行。\n\(message)"
                self.refreshStatus(); return
            }
            self.state.runningProfileIDs.insert(id)
            self.courseResults[id] = "启动命令成功（登录与服务仍需检查）"
            self.recordUse(id)
            self.startCourseSequence(ids, index: index + 1)
        }
    }

    func stopRemainingImports() {
        guard state.phase == .importing else { return }
        stopImportQueueRequested = true
        state.progressText = "当前镜像安全处理完后停止后续导入；不强杀转换、不删除已完成节点。"
    }

    private func stopImportQueueIfRequested() -> Bool {
        guard stopImportQueueRequested else { return false }
        stopImportQueueRequested = false
        state.phase = .idle; state.progressText = ""
        appendLog("已停止后续导入；当前完成的节点保留，可重新扫描继续。")
        refreshStatus(); scanImageFolder(); return true
    }

    // MARK: 持久状态恢复

    func refreshStatus() {
        guard !statusRefreshInFlight else { return }
        statusRefreshInFlight = true
        run(.status) { [weak self] outcome in
            guard let self else { return }
            self.statusRefreshInFlight = false
            switch outcome {
            case .success(let text):
                if let report = GuiParsing.decodeStatus(text) {
                    self.applyStatusReport(report)
                }
            case .failure(let message):
                self.state.lastError = message
            }
        }
    }

    func refreshAutomatically() {
        guard !state.phase.isBusy, !showRecovery else { return }
        let interval: TimeInterval = nodes.contains(where: \.running) ? 3 : 15
        guard Date().timeIntervalSince(lastAutomaticRefresh) >= interval else { return }
        lastAutomaticRefresh = Date()
        refreshStatus()
    }

    func openRecovery(_ profileID: String) {
        guard !state.phase.isBusy, let node = nodes.first(where: { $0.id == profileID }),
              node.imported, !node.running else { return }
        recoveryProfileID = profileID
        recoverySnapshots = []
        recoveryBackups = []
        recoveryName = ""
        showRecovery = true
        loadRecovery()
    }

    func loadRecovery() {
        guard !state.phase.isBusy else { return }
        state.phase = .busy
        let profile = recoveryProfileID
        run(.snapshot(profileID: profile, operation: "list")) { [weak self] outcome in
            guard let self else { return }
            if case .success(let text) = outcome,
               let report = try? JSONDecoder().decode(SnapshotReport.self, from: Data(text.utf8)) {
                self.recoverySnapshots = report.snapshots
            } else if case .failure(let message) = outcome { self.state.lastError = message }
            self.run(.snapshot(profileID: profile, operation: "list-backups")) { [weak self] outcome in
                guard let self else { return }
                self.state.phase = .idle
                if case .success(let text) = outcome,
                   let report = try? JSONDecoder().decode(BackupReport.self, from: Data(text.utf8)) {
                    self.recoveryBackups = report.backups
                } else if case .failure(let message) = outcome { self.state.lastError = message }
            }
        }
    }

    func performRecovery(_ action: CliAction) {
        guard !state.phase.isBusy else { return }
        state.phase = .busy
        state.progressText = "正在处理恢复点；仅作用于所选已停止节点…"
        run(action) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            if case .failure(let message) = outcome { self.state.lastError = message }
            self.loadRecovery()
            self.refreshStatus()
        }
    }

    func confirmRecovery() {
        guard let action = recoveryPending else { return }
        recoveryPending = nil
        // 磁盘恢复前先保存命名快照；失败就不继续覆盖当前实验。
        if case .snapshot(let profile, "revert", _) = action {
            guard !state.phase.isBusy else { return }
            state.phase = .busy
            run(.snapshot(profileID: profile, operation: "create", name: RecoveryRules.checkpointName())) { [weak self] outcome in
                guard let self else { return }
                self.state.phase = .idle
                if case .failure(let message) = outcome { self.state.lastError = message; return }
                self.performRecovery(action)
            }
        } else { performRecovery(action) }
    }

    private static func profileIDs(_ profiles: [StatusProfile]) -> Set<String> {
        Set(profiles.map(\.id))
    }

    /// 运行管理展示 CLI 已登记的全部 profile。未知课程节点只使用 profile ID，不让 GUI
    /// 猜测其硬件参数；实际白名单仍由 CLI/profile YAML 决定。
    private func applyStatusReport(_ report: StatusReport) {
        let unchanged = Set(report.profiles.filter { next in
            next.running && nodes.contains(where: { $0.id == next.id && $0.pid == next.pid && $0.running })
        }.map(\.id))
        nodes = report.profiles
        state.importedProfileIDs = Self.profileIDs(report.profiles.filter(\.imported))
        state.runningProfileIDs = Self.profileIDs(report.profiles.filter(\.running))
        // 状态刷新后必须丢弃上一次健康结果；否则重启后的节点会被显示成“通过”。
        state.healthyProfileIDs.formIntersection(unchanged)
        state.pendingHealthProfileIDs.formIntersection(unchanged)
    }

    // MARK: 动作

    func chooseDistributionDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "选择镜像文件夹"
        panel.message = "选择存放镜像的文件夹：可为空、可放成套分发（DISTRIBUTION.json + SHA256SUMS），也可放单个磁盘镜像（qcow2/ova/vmdk/vdi/vhd/vhdx/img/raw）"
        if panel.runModal() == .OK, let url = panel.url {
            state.distDir = url.path
            state.report = nil
            verifyRows = []
            // 导入状态属于状态目录；切换文件夹只影响“本文件夹能提供什么”，已导入节点保持可用。
            state.configuredProfileIDs.removeAll()
            state.selectedProfileID = nil
            state.healthyProfileIDs.removeAll()
            state.pendingHealthProfileIDs.removeAll()
            state.phase = .idle
            state.lastError = nil
            appendLog("已选择镜像文件夹：\(url.path)")
            // 用户预期的主流程：选文件夹即扫描并自动导入；空文件夹是合法状态。
            scanAndImport()
        }
    }

    /// 扫描 + 自动导入：成套分发（有 DISTRIBUTION.json）按清单导入缺失节点；
    /// 普通文件夹对每个新镜像执行 onboard（架构由 inspect 证据推断）。
    /// 幂等：已导入来源（source_path 相同）与 id 冲突的文件自动跳过。
    func scanAndImport() {
        guard let dir = state.distDir, !dir.isEmpty, !state.phase.isBusy else { return }
        imageLibrary = ImageFolderScanner.scan(dir)
        let layout = DistributionLayout(dir: dir)
        if FileManager.default.fileExists(atPath: layout.manifestPath) {
            appendLog("检测到成套分发清单；校验后自动导入缺失节点。")
            verifyDistribution { [weak self] in
                self?.importMissingFromManifest()
            }
            return
        }
        if imageLibrary.isEmpty {
            appendLog("文件夹顶层没有镜像文件（支持 qcow2/ova/vmdk/vdi/vhd/vhdx/img/raw）；文件夹可以为空。")
            return
        }
        onboardPendingFiles()
    }

    /// 只刷新扫描结果，不触发导入（列表展示用）。
    func scanImageFolder() {
        guard let dir = state.distDir, !dir.isEmpty else { return }
        imageLibrary = ImageFolderScanner.scan(dir)
    }

    /// 清单导入的增量版：只导入尚未导入的 profile。
    /// 内容包（schema 2，带 profile 登记）走单次 `dist install`，由 CLI 做整体
    /// 校验、排他装配置与事务回滚；旧分发目录保持逐节点 import 循环不变。
    private func importMissingFromManifest() {
        guard let dir = state.distDir else { return }
        // 双保险：本函数只允许在“本次校验通过”后进入；任何失败路径都不得
        // 继续导入，更不得回退普通镜像 onboard。
        guard state.report?.ok == true else { return }
        if state.report?.pack != nil {
            installContentPack()
            return
        }
        let layout = DistributionLayout(dir: dir)
        let profileIDs = layout.baseProfileIDs().filter { !state.importedProfileIDs.contains($0) }
        guard !profileIDs.isEmpty else {
            appendLog("成套分发节点已全部导入，无新增。")
            onboardPendingFiles()
            return
        }
        state.configuredProfileIDs = Set(layout.baseProfileIDs())
        stopImportQueueRequested = false
        state.phase = .importing
        importNext(profileIDs: profileIDs, index: 0, layout: layout)
    }

    /// 安装已通过校验的内容包：CLI 负责冲突拒绝与失败回滚；GUI 只展示结论。
    func installContentPack() {
        guard let dir = state.distDir, !dir.isEmpty, !state.phase.isBusy else { return }
        // 与决策门一致：只有本次校验通过的报告才允许触发安装。
        guard state.report?.ok == true else { return }
        stopImportQueueRequested = false
        state.phase = .importing
        state.progressText = "正在安装内容包（校验→配置→基盘→说明）…"
        run(.distInstall(dir: dir)) { [weak self] outcome in
            guard let self else { return }
            switch outcome {
            case .success(let text):
                if let report = PackInstallReport.parse(text) {
                    if let pack = report.pack {
                        self.state.configuredProfileIDs = Set(pack.nodes.map(\.profile))
                        self.state.selectedProfileID = nil
                    }
                    let installed = (report.installed ?? []).joined(separator: "、")
                    let skipped = (report.skippedIdentical ?? []).joined(separator: "、")
                    var summary = "内容包安装完成"
                    if !installed.isEmpty { summary += "：新装 \(installed)" }
                    if !skipped.isEmpty { summary += "；内容一致跳过 \(skipped)" }
                    self.appendLog(summary + "。导入不会自动启动；请选择节点后启动。")
                } else {
                    self.appendLog("内容包安装完成。")
                }
                self.state.phase = .imported
                self.state.progressText = ""
                self.refreshStatus()
                self.scanImageFolder()
            case .failure(let message):
                self.state.phase = .failed
                self.state.progressText = ""
                self.state.lastError = message
                self.appendLog(message)
            }
        }
    }

    /// 真正待导入的文件夹镜像：来源未导入且建议 id 未被占用。
    /// 自动导入与左栏“文件夹镜像”分组共用同一判据——导入完成后条目从分组
    /// 消失，分组为空即整组隐藏，避免与“镜像”列表重合。
    func pendingImageEntries() -> [ImageLibraryEntry] {
        ImageOnboardingRules.pendingImages(imageLibrary, nodes: nodes)
    }

    /// 逐个 onboard 文件夹里的新镜像；失败记录并继续，最后统一刷新状态。
    private func onboardPendingFiles() {
        let pending = pendingImageEntries()
        guard !pending.isEmpty else {
            appendLog(imageLibrary.isEmpty ? "没有可导入的镜像。" : "文件夹镜像均已导入，无新增。")
            return
        }
        appendLog("开始自动导入 \(pending.count) 个新镜像（架构与硬件由只读识别推断）…")
        reservedImportIDs = Set(nodes.map(\.id))
        stopImportQueueRequested = false
        state.phase = .importing
        onboardNext(pending: pending, index: 0)
    }

    private func onboardNext(pending: [ImageLibraryEntry], index: Int) {
        if stopImportQueueIfRequested() { return }
        guard index < pending.count else {
            state.phase = .idle
            state.progressText = ""
            appendLog("自动导入完成；已导入的镜像出现在左侧列表。")
            refreshStatus()
            scanImageFolder()
            return
        }
        let entry = pending[index]
        let profileID = ImageOnboardingRules.availableProfileID(
            sourcePath: entry.path, existingIDs: reservedImportIDs)
        reservedImportIDs.insert(profileID)
        state.progressText = "正在导入 \(entry.fileName)（\(index + 1)/\(pending.count)）…"
        run(.onboardAuto(sourcePath: entry.path, profileID: profileID)) { [weak self] outcome in
            guard let self else { return }
            switch outcome {
            case .success:
                self.appendLog("已导入 \(entry.fileName) 为节点 \(profileID)。")
            case .failure(let message):
                self.appendLog("跳过 \(entry.fileName)：\(message)")
            }
            self.onboardNext(pending: pending, index: index + 1)
        }
    }

    /// 从镜像库进入接入向导（与“添加 x86 镜像…”共用同一条只读识别路径）。
    func beginOnboarding(sourcePath: String) {
        guard !state.phase.isBusy else { return }
        onboardingSourcePath = sourcePath
        onboardingProfileID = ImageOnboardingRules.availableProfileID(sourcePath: sourcePath, existingIDs: Set(nodes.map(\.id)))
        onboardingReport = nil
        onboardingImportedProfileID = nil
        onboardingMatrixReportPath = nil
        onboardingMatrixReviewAttempt = nil
        onboardingMatrixScreenshotPath = nil
        showMatrixApplyConfirmation = false
        onboardingMessage = "原始镜像只读；请先执行“只读识别”，确认候选硬件后再导入。"
        showImageOnboarding = true
    }

    /// 新镜像只读选取：不转换、不导入，也不会修改原始镜像。
    func chooseX86Image() {
        guard !state.phase.isBusy else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = false
        panel.prompt = "选择镜像"
        panel.message = "选择 QCOW2、VMDK、VDI、VHD/VHDX、RAW、OVA，或只含一个磁盘的虚拟机目录"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        beginOnboarding(sourcePath: url.path)
    }

    func inspectOnboardingImage() {
        guard !onboardingSourcePath.isEmpty else { return }
        state.phase = .busy
        state.progressText = "正在只读识别镜像…"
        onboardingReport = nil
        onboardingImportedProfileID = nil
        onboardingMatrixReportPath = nil
        run(.inspectImage(sourcePath: onboardingSourcePath)) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            switch outcome {
            case .success(let text):
                guard let report = GuiParsing.decodeInspection(text) else {
                    self.onboardingMessage = "识别结果无法解析；未导入、未修改原始镜像。"
                    self.state.lastError = self.onboardingMessage
                    return
                }
                self.onboardingReport = report
                if report.candidate.architecture != "x86_64" {
                    self.onboardingMessage = "识别为 \(report.candidate.architecture)，本向导只接入 x86_64；未导入。"
                } else {
                    self.onboardingMessage = "识别完成：候选参数仍需人工确认；未启动、未导入。"
                }
            case .failure(let message):
                self.onboardingMessage = "只读识别失败；未导入、未修改原始镜像。"
                self.state.lastError = message
            }
        }
    }

    /// 用户确认 x86_64 候选后才调用既有 onboard。CLI 在用户状态目录排他写入 profile 并转换派生基盘。
    func importOnboardingCandidate() {
        guard !state.phase.isBusy else { return }
        guard let report = onboardingReport, report.candidate.architecture == "x86_64" else {
            onboardingMessage = "请先完成 x86_64 只读识别。"
            return
        }
        guard ImageOnboardingRules.validProfileID(onboardingProfileID) else {
            onboardingMessage = "配置 ID 只能用小写字母、数字和连字符，长度 1～49，且不能以连字符开头或结尾。"
            return
        }
        let retry = canRetryOnboarding
        if !retry && nodes.contains(where: { $0.id == onboardingProfileID }) {
            onboardingMessage = "该配置 ID 已存在，不能覆盖。请修改 ID（例如添加 -2）后重试。"
            return
        }
        state.lastError = nil
        state.phase = .importing
        state.progressText = "正在创建候选配置并导入派生基盘…"
        let importingID = onboardingProfileID
        let importingSource = onboardingSourcePath
        let action: CliAction = retry
            ? .retryOnboard(sourcePath: importingSource, profileID: importingID)
            : .onboardX86(sourcePath: importingSource, profileID: importingID)
        run(action) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            switch outcome {
            case .success:
                self.retryCandidate = nil
                self.onboardingImportedProfileID = importingID
                self.onboardingMatrixReportPath = nil
                self.state.configuredProfileIDs.insert(importingID)
                self.state.selectedProfileID = importingID
                // 该文件已导入：从“文件夹新增”分组退选，右侧切到新导入的节点。
                if self.selectedFilePath == importingSource {
                    self.selectedFilePath = nil
                }
                self.onboardingMessage = "候选配置和派生基盘已创建；尚未启动验证，请执行“启动探测”。"
                self.appendLog("x86_64 候选 \(importingID) 已导入；原始镜像保持不变。")
                self.refreshStatus()
            case .failure(let message):
                self.retryCandidate = retry || (self.retryCandidate?.id == importingID
                                                && self.retryCandidate?.source == importingSource)
                    ? (importingID, importingSource) : nil
                self.onboardingMessage = self.retryCandidate != nil
                    ? "导入未完成；原始镜像未修改。再次点击导入可重试保留的候选配置。"
                    : "导入未完成；尚未创建可重试候选，请修正问题后再次导入。"
                self.state.lastError = message
            }
        }
    }

    func probeOnboardingCandidate(matrix: Bool) {
        guard let profileID = onboardingImportedProfileID, !state.phase.isBusy else { return }
        state.lastError = nil
        onboardingMatrixReportPath = nil
        onboardingMatrixReviewAttempt = nil
        onboardingMatrixScreenshotPath = nil
        state.phase = .busy
        state.progressText = matrix ? "正在运行受控启动回退矩阵…" : "正在启动探测候选镜像…"
        run(.probeProfile(profileID: profileID, matrix: matrix)) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            switch outcome {
            case .success(let text):
                if matrix, let result = MatrixProbeResult.parse(text) {
                    self.onboardingMatrixReportPath = result.reportPath
                    self.onboardingMatrixReviewAttempt = result.reviewAttempt
                    self.onboardingMatrixScreenshotPath = result.screenshotPath
                    self.onboardingMessage = result.reviewAttempt != nil
                        ? "没有自动成功结论。请打开并检查截图：只有确认系统正常引导，才保存该候选；UEFI Shell、PXE 或报错画面请勿确认。保存后仍未验收。"
                        : "回退矩阵命中候选。请先人工查看截图；确认后仅保存固件和磁盘总线参数，状态仍是 candidate。"
                } else {
                    self.onboardingMessage = matrix
                        ? "回退矩阵没有形成可固化的成功结论；请人工检查日志，原配置未修改。"
                        : "启动探测完成：请查看日志中的截图、网络和服务证据；这不等同于已验证交付。"
                }
            case .failure(let message):
                if matrix { self.onboardingMatrixReportPath = nil }
                self.onboardingMessage = matrix
                    ? "回退矩阵未找到可用候选，或需要人工查看失败截图；原始镜像未修改。"
                    : "首次启动探测未通过；可运行受控回退矩阵，不会自动改写候选配置。"
                self.state.lastError = message
            }
        }
    }

    /// 只把已经人工复核的矩阵白名单硬件参数保存到候选 profile。
    /// CLI 会再次校验报告归属、profile/基盘哈希和运行状态，并在替换前生成备份。
    func applyOnboardingMatrixCandidate() {
        guard let profileID = onboardingImportedProfileID,
              let reportPath = onboardingMatrixReportPath,
              !state.phase.isBusy else { return }
        state.lastError = nil
        state.phase = .busy
        state.progressText = "正在校验报告并保存候选硬件参数…"
        let action: CliAction = onboardingMatrixReviewAttempt.map {
            .reviewMatrixCandidate(profileID: profileID, reportPath: reportPath, attempt: $0)
        } ?? .applyMatrixCandidate(profileID: profileID, reportPath: reportPath)
        run(action) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            switch outcome {
            case .success:
                self.onboardingMatrixReportPath = nil
                self.onboardingMessage = "候选硬件参数已保存，原 profile 已备份；状态仍为 candidate，尚未完成登录、网络和目标服务验收。"
                self.refreshStatus()
            case .failure(let message):
                self.onboardingMessage = "未保存矩阵候选：报告或当前基盘状态已变化。原配置保持不变。"
                self.state.lastError = message
            }
        }
    }

    func verifyDistribution(completion: (() -> Void)? = nil) {
        guard let dir = state.distDir, !dir.isEmpty else {
            state.lastError = "请先选择分发目录"
            completion?()
            return
        }
        state.phase = .verifying
        state.progressText = "正在校验分发目录…"
        run(.distVerify(dir: dir)) { [weak self] outcome in
            guard let self else { return }
            switch outcome {
            case .success(let text), .failure(let text):
                // dist verify 失败时 CLI 仍输出结构化 JSON（原始透传，不做尾部截断），
                // 因此这里必须能解码出红色校验行与具体问题。
                guard let report = GuiParsing.decodeDistReport(text) else {
                    self.state.phase = .failed
                    self.state.progressText = ""
                    self.state.lastError = text
                    self.appendLog(text)
                    return
                }
                self.state.report = report
                self.verifyRows = report.entries
                let baseProfiles = report.entries.compactMap { entry -> String? in
                    guard entry.role == "base", let profile = entry.profile,
                          !profile.isEmpty else { return nil }
                    return profile
                }
                if report.ok && !baseProfiles.isEmpty {
                    self.state.configuredProfileIDs = Set(baseProfiles)
                    // 校验只登记“本次分发目录有哪些节点”；它不等于已导入，
                    // 也不替用户默认勾选或批量启动任何节点。
                    self.state.selectedProfileID = nil
                }
                self.state.progressText = ""
                self.state.phase = report.ok ? .verified : .failed
                if report.ok {
                    self.state.lastError = nil
                } else {
                    // 失败横幅给出具体问题（缺件/哈希不符/结构非法），不只说“校验失败”。
                    let detail = report.problems.prefix(3).joined(separator: "；")
                    self.state.lastError = detail.isEmpty
                        ? GuiMessages.verifyFailedBanner
                        : "\(GuiMessages.verifyFailedBanner)\n\(detail)"
                }
                let summary = report.summary.map {
                    "通过 \($0.ok)/\($0.total)"
                } ?? ""
                self.appendLog(report.ok
                    ? "分发目录校验通过（\(summary)）"
                    : "分发目录校验失败：\(report.problems.joined(separator: "；"))")
                // 决策门：校验失败或输出不可解码时中止全部导入，
                // 绝不能回退到普通镜像 onboard 路径（否则清单目录里的磁盘
                // 会被当成新镜像自动登记成第二个节点）。
                switch DistImportGate.decide(report: report, manifestExists: true) {
                case .installPack, .importMissing:
                    completion?()
                case .abort:
                    return
                }
            }
        }
    }

    func importAll() {
        guard state.canImport else {
            state.lastError = GuiMessages.notVerifiedPrefix
            return
        }
        guard let dir = state.distDir else { return }
        if state.report?.pack != nil {
            installContentPack()
            return
        }
        let layout = DistributionLayout(dir: dir)
        // 基盘路径来自分发清单（与老师生成的一致），缺失时明确报错而不是猜文件名。
        let profileIDs = layout.baseProfileIDs()
        guard !profileIDs.isEmpty else {
            state.lastError = "分发清单里没有 role=base 的节点条目"
            appendLog(state.lastError ?? "")
            return
        }
        state.configuredProfileIDs = Set(profileIDs)
        state.selectedProfileID = nil
        stopImportQueueRequested = false
        state.phase = .importing
        importNext(profileIDs: profileIDs, index: 0, layout: layout)
    }

    private func importNext(profileIDs: [String], index: Int, layout: DistributionLayout) {
        if stopImportQueueIfRequested() { return }
        guard index < profileIDs.count else {
            state.phase = .imported
            state.progressText = ""
            appendLog("\(profileIDs.count) 个节点导入完成。请选择一个节点再启动；Kali 默认使用真实自动分辨率。")
            refreshStatus()
            return
        }
        let profileID = profileIDs[index]
        state.progressText = state.importProgressText(index: index, total: profileIDs.count, profileID: profileID)
        guard let sourcePath = layout.basePath(forProfileID: profileID) else {
            state.phase = .failed
            state.lastError = "分发清单里缺少 \(LabNode.displayName(for: profileID)) 的基盘条目"
            return
        }
        run(.importProfile(profileID: profileID, sourcePath: sourcePath,
                        manifestPath: layout.manifestPath)) { [weak self] outcome in
            guard let self else { return }
            switch outcome {
            case .success:
                self.state.importedProfileIDs.insert(profileID)
                self.appendLog("\(LabNode.displayName(for: profileID)) 导入完成")
                self.importNext(profileIDs: profileIDs, index: index + 1, layout: layout)
            case .failure(let message):
                self.state.phase = .failed
                self.state.progressText = ""
                self.state.lastError = message
                self.appendLog(message)
            }
        }
    }

    func selectNode(_ profileID: String?) {
        guard !state.phase.isBusy else { return }
        state.selectedProfileID = profileID
    }

    func startSelected() {
        guard let selectedProfileID = state.selectedProfileID, state.canStartSelected else {
            state.lastError = state.selectedProfileID == nil
                ? "请先选择一个已导入的节点。"
                : "所选节点尚未导入、已在运行，或分发目录尚未校验。"
            return
        }
        state.phase = .busy
        state.progressText = selectedProfileID == LabNode.kali.rawValue
            ? "正在启动 \(LabNode.displayName(for: selectedProfileID))…（自动分辨率）"
            : "正在启动 \(LabNode.displayName(for: selectedProfileID))…"
        state.lastError = nil
        run(.preflight(profileID: selectedProfileID,
                       resourcePreset: selectedProfileID == "kali-arm64" && resourcePreset != "original" ? resourcePreset : nil)) { [weak self] outcome in
            guard let self else { return }
            switch outcome {
            case .success(let text):
                guard let report = try? JSONDecoder().decode(PreflightReport.self, from: Data(text.utf8)), report.ok else {
                    self.state.phase = .idle; self.state.progressText = ""; self.state.lastError = "启动前检查结果无法确认，未启动节点。"; return
                }
                self.launchSelectedAfterPreflight(selectedProfileID)
            case .failure(let text):
                self.state.phase = .idle; self.state.progressText = ""
                self.state.lastError = PreflightReport.decode(text)?.guidance ?? text
            }
        }
    }

    private func launchSelectedAfterPreflight(_ selectedProfileID: String) {
        run(.runProfiles(profileIDs: [selectedProfileID],
                         clipboard: selectedProfileID == "kali-arm64" && clipboardSharingEnabled,
                         displayQuality: displayQualitySharp ? "sharp" : "smooth",
                         fileTransfer: selectedProfileID == "kali-arm64" && fileTransferEnabled,
                         resourcePreset: selectedProfileID == "kali-arm64" && resourcePreset != "original" ? resourcePreset : nil)) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            if case .failure(let message) = outcome { self.state.lastError = message }
            else { self.recordUse(selectedProfileID) }
            self.refreshStatus()
        }
    }

    func diagnoseDisplay(_ profileID: String) {
        guard !state.phase.isBusy else { return }
        state.phase = .busy
        run(.displayDiagnose(profileID: profileID)) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            switch outcome {
            case .success(let text):
                if let report = try? JSONDecoder().decode(DisplayDiagnosisReport.self, from: Data(text.utf8)) {
                    self.displayDiagnosis[profileID] = report.hint
                } else { self.state.lastError = "显示诊断无法解析；未重启或重置节点。" }
            case .failure(let text): self.state.lastError = text
            }
        }
    }

    func stageLocalUpdate() {
        guard !state.phase.isBusy else { return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.treatsFilePackagesAsDirectories = true; panel.allowsMultipleSelection = false
        panel.message = "选择本地 CTFLab.app；复制验证，不覆盖现用版本或镜像。"
        guard panel.runModal() == .OK, let source = panel.url else { return }
        let sidecar = source.appendingPathExtension("sha256")
        guard let text = try? String(contentsOf: sidecar, encoding: .utf8),
              let hash = text.split(whereSeparator: \.isWhitespace).first, hash.count == 64 else {
            state.lastError = "缺少完整 App 哈希旁车，拒绝更新。"; return
        }
        let confirm = NSAlert()
        confirm.messageText = "校验这个本地候选？"
        confirm.informativeText = "树 SHA-256：\(hash)\n旁车不是来源身份认证，请自行确认可信来源。本地候选可能只有 ad-hoc 签名，不等于已公证。只复制到独立更新槽位，不覆盖已安装 App。"
        confirm.addButton(withTitle: "校验并暂存"); confirm.addButton(withTitle: "取消")
        guard confirm.runModal() == .alertFirstButtonReturn else { return }
        state.phase = .busy; updateMessage = "正在校验并复制本地候选…"
        run(.updateStage(source: source.path, sha256: String(hash))) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            switch outcome {
            case .failure(let text): self.state.lastError = text; self.updateMessage = "校验失败；现用版本不变。"
            case .success(let text):
                guard let data = text.data(using: .utf8), let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let slot = value["slot"] as? String else {
                    self.state.lastError = "槽位结果无法解析，未切换版本。"; return
                }
                self.updateMessage = "候选已暂存，尚未切换。"
                let alert = NSAlert(); alert.messageText = "选择这个更新槽位？"
                alert.informativeText = "仅切换本地更新指针；本次 App、运行中节点与镜像保持不变。旧版本保留，可回退。"
                alert.addButton(withTitle: "选择候选"); alert.addButton(withTitle: "保持现用版本")
                if alert.runModal() == .alertFirstButtonReturn { self.selectUpdate(.updateSelect(slot: slot)) }
            }
        }
    }

    func selectUpdate(_ action: CliAction) {
        guard !state.phase.isBusy else { return }
        state.phase = .busy
        run(action) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            switch outcome {
            case .failure(let text): self.state.lastError = text
            case .success(let text):
                self.updateMessage = "所选槽位已保存；使用“打开所选更新版本”，不会替换系统安装。"
                if let data = text.data(using: .utf8), let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let path = value["app"] as? String {
                    NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
                }
            }
        }
    }

    func rollbackUpdate() {
        let alert = NSAlert(); alert.messageText = "回退下次启动版本？"
        alert.informativeText = "验证前一更新槽位后切换指针；不回退镜像、不停止运行节点。没有前版时只报告错误。"
        alert.addButton(withTitle: "验证并回退"); alert.addButton(withTitle: "取消")
        if alert.runModal() == .alertFirstButtonReturn { selectUpdate(.updateRollback) }
    }

    func launchUpdate() {
        guard !state.phase.isBusy else { return }
        let alert = NSAlert(); alert.messageText = "打开所选更新版本？"
        alert.informativeText = "再次验证哈希和签名后打开新的管理面板。不会停止运行节点或迁移镜像；当前面板可手动退出。"
        alert.addButton(withTitle: "验证并打开"); alert.addButton(withTitle: "取消")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        state.phase = .busy
        run(.updateLaunch) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            switch outcome {
            case .success: self.updateMessage = "已请求打开所选版本；系统默认安装路径未变。"
            case .failure(let text): self.state.lastError = text
            }
        }
    }

    func checkStatus() {
        guard state.canCheckStatus else { return }
        state.phase = .busy
        state.progressText = "正在检查状态与健康…"
        state.healthyProfileIDs.removeAll()
        state.pendingHealthProfileIDs.removeAll()
        run(.status) { [weak self] outcome in
            guard let self else { return }
            switch outcome {
            case .success(let text):
                if let report = GuiParsing.decodeStatus(text) {
                    self.applyStatusReport(report)
                }
            case .failure(let message):
                self.state.lastError = message
            }
            let activeProfiles = self.nodes.filter(\.running).map(\.id)
            self.checkHealthSequence(profileIDs: activeProfiles, index: 0)
        }
    }

    private func checkHealthSequence(profileIDs: [String], index: Int) {
        guard index < profileIDs.count else {
            state.phase = .idle
            state.progressText = ""
            appendLog("状态与健康检查完成。")
            return
        }
        let profileID = profileIDs[index]
        run(.healthProfile(profileID: profileID)) { [weak self] outcome in
            guard let self else { return }
            switch outcome {
            case .success(let text), .failure(let text):
                if let report = GuiParsing.decodeHealth(text) {
                    if report.isPending {
                        self.state.pendingHealthProfileIDs.insert(profileID)
                        self.state.healthyProfileIDs.remove(profileID)
                    } else if report.ok {
                        self.state.pendingHealthProfileIDs.remove(profileID)
                        self.state.healthyProfileIDs.insert(profileID)
                    } else {
                        self.state.pendingHealthProfileIDs.remove(profileID)
                        self.state.healthyProfileIDs.remove(profileID)
                    }
                    let detail = report.checks.map {
                        "\($0.ok == true ? "OK" : ($0.ok == nil ? "WAIT" : "FAIL")) \($0.name)"
                    }.joined(separator: ", ")
                    let label = report.isPending ? "等待" : (report.ok ? "通过" : "未通过")
                    self.appendLog("\(LabNode.displayName(for: profileID)) 健康检查：\(label)（\(detail)）")
                } else {
                    self.appendLog(text)
                }
            }
            self.checkHealthSequence(profileIDs: profileIDs, index: index + 1)
        }
    }

    /// 表格快捷键仍先把该行设为当前选择，再复用同一条单节点启动路径。
    func startProfile(_ profileID: String) {
        selectNode(profileID)
        startSelected()
    }

    func stopProfile(_ profileID: String) {
        selectNode(profileID)
        stopSelected()
    }

    func showDisplay(_ profileID: String, reconnect: Bool = false) {
        guard !state.phase.isBusy else { return }
        displayDiagnosis.removeValue(forKey: profileID)
        state.phase = .busy
        state.progressText = "正在恢复显示窗口（虚拟机不会重启）…"
        run(reconnect ? .reconnectDisplay(profileID: profileID) : .showDisplay(profileID: profileID)) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            switch outcome {
            case .success(let text):
                if let report = try? JSONDecoder().decode(DisplayOpenReport.self, from: Data(text.utf8)) {
                    // 对现有应用恢复窗口；不使用 open 启动另一份 QEMU。
                    NSRunningApplication(processIdentifier: pid_t(report.pid))?
                        .activate(options: [.activateAllWindows])
                }
            case .failure(let message): self.state.lastError = message
            }
            self.refreshStatus()
        }
    }

    func previewPublicDiagnostics() {
        guard !state.phase.isBusy, !nodes.isEmpty else {
            state.lastError = "请先检查状态，再预览诊断摘要。"; return
        }
        #if arch(arm64)
        let machine = "arm64"
        #elseif arch(x86_64)
        let machine = "x86_64"
        #else
        let machine = "unknown"
        #endif
        publicDiagnosticsError = ""
        do {
            publicDiagnostics = try MacPublicDiagnostics.preview(nodes,
                version: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown",
                machine: machine)
        } catch { publicDiagnostics = nil; state.lastError = "无法生成诊断摘要；没有导出任何文件。" }
    }

    func savePublicDiagnostics(_ snapshot: MacPublicDiagnostics) {
        guard publicDiagnostics?.id == snapshot.id else { return }
        publicDiagnosticsError = ""
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "ctflab-share-summary.json"
        panel.message = "保存当前预览的匿名摘要；不会上传，也不会重新采集状态。"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try snapshot.save(to: url)
            publicDiagnostics = nil
            NSWorkspace.shared.activateFileViewerSelecting([url])
        } catch { publicDiagnosticsError = "摘要保存未完成。请使用新文件名；已有文件保留，不会覆盖。" }
    }

    func exportDiagnostics() {
        guard !state.phase.isBusy else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "ctflab-diagnostics-\(UUID().uuidString.prefix(8)).json"
        panel.message = "包含运行状态、路径与日志尾行，可能含敏感信息，仅供本机排查。公开反馈请用“分享诊断摘要”。"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        if FileManager.default.fileExists(atPath: url.path) {
            state.lastError = "请使用新文件名；诊断导出不会覆盖已有文件。"
            return
        }
        state.phase = .busy
        run(.diagnostics(path: url.path)) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            if case .failure(let message) = outcome { self.state.lastError = message }
            if FileManager.default.fileExists(atPath: url.path) {
                NSWorkspace.shared.activateFileViewerSelecting([url])
            }
        }
    }

    func stopSelected() {
        guard let selectedProfileID = state.selectedProfileID, state.canStopSelected else {
            state.lastError = state.selectedProfileID == nil
                ? "请先选择一个运行中的节点。"
                : "所选节点当前未运行。"
            return
        }
        state.phase = .busy
        state.progressText = "正在停止 \(LabNode.displayName(for: selectedProfileID))…"
        run(.stopProfiles(profileIDs: [selectedProfileID])) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            if case .failure(let message) = outcome { self.state.lastError = message }
            self.refreshStatus()
        }
    }

    /// 单节点重启（第 8 项）：组合既有 stop + run 两个 CLI 子命令，
    /// 顺序执行、任一步失败即停并报告；只作用于当前选中节点。
    func restartSelected() {
        guard let selectedProfileID = state.selectedProfileID, state.canStopSelected else {
            state.lastError = state.selectedProfileID == nil
                ? "请先选择一个运行中的节点。"
                : "重启只对运行中的节点可用。"
            return
        }
        state.phase = .busy
        state.progressText = "正在重启 \(LabNode.displayName(for: selectedProfileID))…"
        run(.stopProfiles(profileIDs: [selectedProfileID])) { [weak self] outcome in
            guard let self else { return }
            if case .failure(let message) = outcome {
                self.state.phase = .idle
                self.state.progressText = ""
                self.state.lastError = "重启失败（停止阶段）：\(message)"
                self.refreshStatus()
                return
            }
            self.run(.runProfiles(profileIDs: [selectedProfileID],
                                  clipboard: selectedProfileID == "kali-arm64" && self.clipboardSharingEnabled,
                                  displayQuality: self.displayQualitySharp ? "sharp" : "smooth",
                                  fileTransfer: selectedProfileID == "kali-arm64" && self.fileTransferEnabled,
                                  resourcePreset: selectedProfileID == "kali-arm64" && self.resourcePreset != "original" ? self.resourcePreset : nil)) { [weak self] outcome in
                guard let self else { return }
                self.state.phase = .idle
                self.state.progressText = ""
                if case .failure(let message) = outcome {
                    self.state.lastError = "重启失败（启动阶段）：\(message)"
                }
                self.refreshStatus()
            }
        }
    }

    func requestReset() {
        guard state.canReset else { return }
        showResetConfirmation = true
    }

    /// 移除“未导入”的用户登记（内置课程节点不可移除）。CLI 端还有运行中/
    /// 已导入守卫；这里只做 UI 侧态判断与状态刷新。
    func deregisterProfile(_ profileID: String) {
        guard !state.phase.isBusy else { return }
        guard let profile = nodes.first(where: { $0.id == profileID }), !profile.imported, !profile.running else {
            state.lastError = "只能移除“未导入”的登记；已导入的节点请先用重置删除导入数据。"
            return
        }
        state.phase = .busy
        state.progressText = "正在移除登记 \(profileID)…"
        run(.deregisterProfile(profileID: profileID)) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            switch outcome {
            case .success:
                self.deregisterTargets.insert(profileID)
                if self.state.selectedProfileID == profileID { self.state.selectedProfileID = nil }
                self.appendLog("已移除登记 \(profileID)。")
            case .failure(let message):
                self.state.lastError = message
            }
            self.refreshStatus()
        }
    }

    func confirmReset() {
        let plan = ResetGate.plan(state: state, confirmed: true)
        showResetConfirmation = false
        guard let plan else { return }
        state.phase = .busy
        resetSequence(plan: plan, index: 0)
    }

    /// 单节点重置（右栏操作）：只重置当前选中节点，独立于“重置全部”。
    func requestNodeReset(_ profileID: String) {
        guard !state.phase.isBusy else { return }
        nodeResetTarget = profileID
        showNodeResetConfirmation = true
    }

    /// 删除已导入镜像（列表移除）：删基盘副本与登记，不动原始来源文件。
    func requestImageRemove(_ profileID: String) {
        guard !state.phase.isBusy else { return }
        imageRemoveTarget = profileID
        showImageRemoveConfirmation = true
    }

    func confirmImageRemove() {
        guard let profileID = imageRemoveTarget else { return }
        showImageRemoveConfirmation = false
        imageRemoveTarget = nil
        state.phase = .busy
        state.progressText = "正在删除镜像 \(profileID)…"
        run(.removeImage(profileID: profileID)) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            switch outcome {
            case .success:
                if self.state.selectedProfileID == profileID { self.state.selectedProfileID = nil }
                self.appendLog("已删除镜像 \(profileID)（原始来源文件不受影响）。")
            case .failure(let message):
                self.state.lastError = message
            }
            self.refreshStatus()
        }
    }

    func confirmNodeReset() {
        guard let profileID = nodeResetTarget else { return }
        showNodeResetConfirmation = false
        nodeResetTarget = nil
        state.phase = .busy
        state.progressText = "正在重置 \(profileID)…"
        run(.resetProfile(profileID: profileID)) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            switch outcome {
            case .success:
                self.appendLog("已重置 \(profileID)：下次启动会从基础镜像创建全新 overlay。")
            case .failure(let message):
                self.state.lastError = message
            }
            self.refreshStatus()
        }
    }

    private func resetSequence(plan: [CliAction], index: Int) {
        guard index < plan.count else {
            state.phase = .idle
            state.progressText = ""
            appendLog("重置完成：\(plan.count) 个节点的 overlay 已删除，基础镜像未受影响。")
            refreshStatus()
            return
        }
        let action = plan[index]
        state.progressText = "正在重置（\(index + 1)/\(plan.count)）…"
        run(action) { [weak self] outcome in
            guard let self else { return }
            if case .failure(let message) = outcome {
                self.state.phase = .failed
                self.state.lastError = message
                self.appendLog(message)
                return
            }
            self.resetSequence(plan: plan, index: index + 1)
        }
    }

    var sceneHasCurrent: Bool { sceneGeneric ? sceneLocalView != nil : sceneSnapshot != nil }
    func sceneGenericAllowed(_ action: String) -> Bool {
        guard !sceneWorkspaceBusy, let view = sceneLocalView else { return false }
        let status = view["status"], state = status["state"].text ?? "unknown"
        if action == "cancel" { return status["operation_id"].text != nil && ["accepted", "unknown"].contains(status["result"].text ?? "") }
        if status["result"].text == "accepted" || view["execution"]["identity"].text == "running" { return false }
        if action != "recover" && !MacObservationWindow.fresh(view) { return false }
        if action == "start" && (view["runtime"]["dependencies"]["tls_control"].flag == false || view["runtime"]["emulation_required"].flag == true && !sceneEmulation) { return false }
        switch action {
        case "prepare": return view["generation"].integer == 0 && state == "unknown"
        case "start", "reset": return ["prepared", "stopped"].contains(state)
        case "stop": return ["process-running", "guest-ready", "service-ready", "recovery-required"].contains(state)
        case "recover": return (view["generation"].integer ?? 0) > 0
        case "guest": return state == "process-running"
        default: return false
        }
    }
    func sceneGenericCall(_ payload: [String: MacRemoteJSON]) {
        guard !sceneWorkspaceBusy, MacRemoteRules.uuid(sceneInstance) else { return }
        do {
            let encoded = try MacRemoteJSON.object(["instance_uuid": .string(sceneInstance), "payload": .object(payload)]).encoded()
            let context = sceneInstance, action = payload["action"]?.text ?? "", revision = sceneDraftRevision
            let ticket = UUID(); sceneCallTicket = ticket
            sceneWorkspaceBusy = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
                guard let self, self.sceneCallTicket == ticket else { return }
                self.sceneCallTicket = nil; self.sceneWorkspaceBusy = false
                guard self.sceneGeneric, self.sceneInstance == context else { return }
                if let old = self.sceneLocalView { self.sceneLocalView = MacObservationWindow.invalidated(old) }
                self.sceneMessage = "请求暂未返回，结果可能已记录；请读取状态或查询原请求。不会自动重发，也不终止后台工作。"
            }
            if action != "draft" && action != "overview" && action != "query-request" && action != "external-attach-status"
                && action != "operation-history" && action != "operation-result" && action != "events" { sceneLocalView = nil; sceneSnapshot = nil }
            run(.genericClient(json: encoded)) { [weak self] outcome in
                guard let self, self.sceneCallTicket == ticket else { return }
                self.sceneCallTicket = nil; self.sceneWorkspaceBusy = false
                guard self.sceneGeneric, self.sceneInstance == context else { return }
                let output: String
                switch outcome { case .success(let v), .failure(let v): output = v }
                do {
                    let reply = try MacRemoteJSON.decode(output)
                    if let message = reply["error"]["message"].text { if let old = self.sceneLocalView { self.sceneLocalView = MacObservationWindow.invalidated(old) }; self.sceneMessage = message; return }
                    self.sceneReply = reply
                    if action == "preview" {
                        self.scenePlan = reply["plan"]; self.sceneSourceManifest = reply["source_manifest"]; self.sceneManifestSHA = reply["manifest_sha256"].text ?? ""
                        self.sceneMessage = "通用设计已校验；尚未配置、复制或启动。"
                    } else if action == "instances", reply["state"].text == "listed" {
                        self.sceneMessage = reply["reports"].items.isEmpty ? "还没有通用实验。到模板页选择场景设计、配置资产并建立实例。" : "已列出保存的实验；选择实例后读取状态，不会自动启动。"
                    } else if action == "overview", reply["manifest"] != .null {
                        self.sceneLocalView = reply; self.sceneSourceManifest = reply["manifest"]; self.scenePlan = .object(["manifest": reply["manifest"]]); self.sceneManifestSHA = ""
                        self.sceneMessage = "已读取当前通用实例。进程、来宾、服务和课程验收分别核对。"
                    } else if action == "external-attach-status", reply["state"].text == "external-attach-status" {
                        self.sceneExternalAttach = reply
                        self.sceneMessage = "外部攻击机状态已读取；连接/断开按前置条件开放。"
                    } else if action == "query-request" {
                        self.sceneMessage = reply["recorded"].flag == true ? "原请求记录已读取：" + (reply["response"]["state"].text ?? "结果待核对") + "；未派发操作。" : "暂未找到原请求；标识保留，不会自动重发。"
                    } else if action == "operation-history" {
                        do {
                            let page = try MacHistoryPage(reply, instance: context)
                            if let expected = self.sceneHistoryNext {
                                guard page.operations.first?.operationID == expected else { throw MacRemoteError.invalid }
                                self.sceneHistory += page.operations
                            } else { self.sceneHistory = page.operations }
                            self.sceneHistoryNext = page.nextBefore
                            self.sceneHistoryHasNext = page.truncated
                            self.sceneMessage = page.truncated ? "已读取已保存操作历史（只读），还有更早记录；可翻页或查看原响应。" : "已读取已保存操作历史（只读）；不含请求参数，不会自动重发。"
                        } catch { self.sceneMessage = "历史回复无法核验，保留已读取内容；不自动重发。" }
                    } else if action == "operation-result" {
                        do {
                            let record = try MacSavedRecord(reply, instance: context)
                            self.sceneHistoryRecord = record
                            self.sceneMessage = record.response == .null ? "该操作尚无已保存响应（历史）；当前状态以重新读取为准。" : "原响应已读取（历史）；未派发任何操作。"
                        } catch { self.sceneMessage = "原响应回复无法核验，保留现场；不自动重发。" }
                    } else if action == "events" {
                        let result = MacEventPage.refresh(.number(Double(self.sceneEventCursor)), reply, view: self.sceneLocalView)
                        self.sceneEventCursor = result.cursor
                        if result.reload {
                            self.sceneEvents = []
                            self.sceneEventNotice = "事件序列已变化或无法核验，本地时间线已清空；请重新读取状态后再读取新事件，不会重发操作。"
                        } else {
                            self.sceneEvents = Array((self.sceneEvents + result.events).suffix(80))
                            self.sceneEventNotice = result.events.isEmpty ? "暂无新事件。" : ""
                        }
                    } else if action == "draft", revision == self.sceneDraftRevision, self.sceneDraftContext == context {
                        guard reply["applied"].flag == false, reply["requires_new_generation"].flag == true,
                              reply["manifest"] == self.sceneDraft else { throw MacRemoteError.invalid }
                        self.sceneDraftDiff = reply; self.sceneMessage = "草稿及差异已校验；未修改运行实例，可导出后配置新实例。"
                    } else { self.sceneMessage = "本次请求已返回，请重新读取状态；结果未知时不自动重发。" }
                } catch { if let old = self.sceneLocalView { self.sceneLocalView = MacObservationWindow.invalidated(old) }; self.sceneMessage = "回复无法核验，保留现场，不自动重发。" }
            }
        } catch { sceneMessage = "请求无法编码。" }
    }
    func sceneRequestGeneric(_ action: String, list: Bool = false) {
        if list { sceneGenericCall(["action": .string("instances")]); return }
        if action == "status" { sceneGenericCall(["action": .string("overview")]); return }
        if action == "preview" { sceneGenericCall(["action": .string("preview"), "manifest": .string(sceneManifest)]); return }
        if action == "configure" {
            guard MacRemoteRules.digest(sceneManifestSHA), !sceneRuntimeProfile.isEmpty else { sceneMessage = "先预览清单并选择私有运行时配置。"; return }
            sceneGenericCall(["action": .string("configure"), "manifest": .string(sceneManifest), "manifest_sha256": .string(sceneManifestSHA),
                "assets": .object(sceneAssets.mapValues { .string($0) }), "profile": .string(sceneRuntimeProfile),
                "nvram": .object(Dictionary(uniqueKeysWithValues: sceneUEFINodes.map { ($0, MacRemoteJSON.string(sceneFirmware[$0]?[1] ?? "")) }))]); return
        }
        guard sceneGenericAllowed(action), let view = sceneLocalView else { return }
        var params: [String: MacRemoteJSON] = [:]
        switch action {
        case "prepare": params = ["course_id": .string("host"), "baseline_id": .string("host")]
        case "start": params = ["display": .string("headless"), "allow_emulation": .bool(view["runtime"]["emulation_required"].flag == true && sceneEmulation)]
        case "reset": params = ["baseline_id": .string("host")]
        case "cancel": params = ["operation_id": view["status"]["operation_id"]]
        default: break
        }
        sceneSubmit(action, params: params, view: view)
    }
    func sceneSubmit(_ operation: String, params: [String: MacRemoteJSON], view: MacRemoteJSON) {
        let request: [String: MacRemoteJSON] = ["protocol": .string("ctflab-local"), "version": .number(1),
            "request_id": .string(UUID().uuidString.lowercased()), "operation": .string(operation), "instance_uuid": .string(sceneInstance),
            "expected_generation": operation == "prepare" ? .null : view["status"]["generation"],
            "expected_state_revision": operation == "prepare" ? .null : view["status"]["state_revision"],
            "idempotency_key": .string(UUID().uuidString.lowercased()), "parameters": .object(params)]
        sceneLastRequest = .object(request)
        sceneGenericCall(["action": .string("submit"), "request": .object(request)])
    }
    var sceneCanQueryOriginal: Bool { !sceneWorkspaceBusy && sceneLastRequest?["instance_uuid"].text == sceneInstance }
    func sceneQueryOriginal() {
        guard sceneCanQueryOriginal, let request = sceneLastRequest else { return }
        sceneGenericCall(["action":.string("query-request"),"request":request])
    }
    // MARK: A03 持久历史与严格事件（只读；实例来自当前选择，主体来自本机进程，界面不能替换）
    func sceneResetReadonly() {
        sceneHistory = []; sceneHistoryNext = nil; sceneHistoryHasNext = false
        sceneHistoryRecord = nil; sceneEvents = []; sceneEventCursor = 0; sceneEventNotice = ""
    }
    func sceneHistoryLoad() {
        guard !sceneWorkspaceBusy, MacRemoteRules.uuid(sceneInstance) else { return }
        sceneHistory = []; sceneHistoryNext = nil; sceneHistoryHasNext = false; sceneHistoryRecord = nil
        sceneGenericCall(["action": .string("operation-history"), "limit": .number(20)])
    }
    func sceneHistoryNextPage() {
        guard !sceneWorkspaceBusy, MacRemoteRules.uuid(sceneInstance), let before = sceneHistoryNext else { return }
        sceneGenericCall(["action": .string("operation-history"), "limit": .number(20), "before": .string(before)])
    }
    func sceneSavedRecord(_ operationID: String) {
        guard !sceneWorkspaceBusy, MacRemoteRules.uuid(operationID) else { return }
        sceneGenericCall(["action": .string("operation-result"), "operation_id": .string(operationID)])
    }
    func sceneEventsRefresh() {
        guard !sceneWorkspaceBusy, MacRemoteRules.uuid(sceneInstance) else { return }
        sceneGenericCall(["action": .string("events"), "after": .number(Double(sceneEventCursor))])
    }
    func sceneGuest(_ node: String, _ action: String) {
        guard sceneGenericAllowed("guest"), let view = sceneLocalView else { return }
        sceneSubmit("guest", params: ["node": .string(node), "action": .string(action)], view: view)
    }
    func sceneGuestPreparation(_ node: String, target: String, resume: Bool) {
        guard sceneGenericAllowed("guest"), let view = sceneLocalView else { return }
        do {
            let value = try MacGuestRecovery.parameters(view,node: node,target: target,resume: resume)
            guard case .object(let params) = value else { return }
            sceneSubmit("guest",params: params,view: view)
        } catch { sceneMessage = "请先恢复核验实验进程，再核对原准备记录；现场变化后须重新核对。" }
    }
    func sceneRecoverPreparation(_ action: String) {
        guard let view = sceneLocalView, MacObservationWindow.fresh(view), view["execution"]["identity"].text != "running" else { return }
        let source = view[action == "resume-dispatch" ? "dispatch" : "preparation"]
        guard source[action == "resume-dispatch" ? "resume_allowed" : "restart_allowed"].flag == true else { return }
        sceneGenericCall(["action": .string(action), "instance_uuid": .string(sceneInstance), "operation_id": source["operation_id"],
            "state_revision": source["state_revision"], "attempt_id": .string(UUID().uuidString.lowercased())])
    }
    func sceneLoadDraft() {
        guard sceneGeneric, !sceneWorkspaceBusy, sceneLocalView != nil, let source = sceneSourceManifest else { return }
        do { sceneDraft = try MacGraphDraft.checked(source); sceneDraftHistory = try MacGraphHistory(sceneDraft); sceneDraftContext = sceneInstance; sceneDraftRevision += 1; sceneDraftDiff = .null }
        catch { sceneMessage = "当前清单无法显示为拓扑草稿。" }
    }
    func sceneEditDraft(_ transform: (MacRemoteJSON) throws -> MacRemoteJSON) {
        guard !sceneWorkspaceBusy, sceneGeneric, sceneDraftContext == sceneInstance else { return }
        do { let next = try transform(sceneDraft); var history = try sceneDraftHistory ?? MacGraphHistory(sceneDraft); try history.edit(next); sceneDraftHistory = history; sceneDraft = history.present; sceneDraftRevision += 1; sceneDraftDiff = .null }
        catch { sceneMessage = "草稿操作未完成：核对资源范围、依赖循环、标识、可用地址、网段重叠或重复连接。" }
    }
    func sceneMoveDraft(_ redo: Bool) {
        guard !sceneWorkspaceBusy, sceneGeneric, sceneDraftContext == sceneInstance, var history = sceneDraftHistory, history.present == sceneDraft else { return }
        if redo { history.redo() } else { history.undo() }
        sceneDraftHistory = history; sceneDraft = history.present; sceneDraftRevision += 1; sceneDraftDiff = .null
    }
    func sceneValidateDraft() {
        guard sceneDraftContext == sceneInstance, sceneDraft != .null else { return }
        sceneDraftDiff = .null; sceneGenericCall(["action": .string("draft"), "manifest": sceneDraft])
    }
    func sceneExportDraft() {
        guard sceneDraftContext == sceneInstance, sceneDraftDiff["manifest"] == sceneDraft, sceneDraftDiff["applied"].flag == false else { return }
        let picker = NSSavePanel(); picker.nameFieldStringValue = "ctflab-scenario-draft.json"
        guard picker.runModal() == .OK, let url = picker.url else { return }
        do {
            let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(sceneDraft).write(to: url, options: .withoutOverwriting)
            sceneMessage = "已导出后端校验草稿；已有文件不覆盖。草稿导出不等于可执行模板；发布可执行模板须通过具体场景验收并绑定草稿摘要。"
        } catch { sceneMessage = "草稿未导出，已有文件保留。" }
    }
    func sceneExport() {
        guard let manifest = sceneSourceManifest, manifest != .null else { return }
        let picker = NSSavePanel(); picker.nameFieldStringValue = "ctflab-scenario.json"
        guard picker.runModal() == .OK, let url = picker.url else { return }
        do { let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]; let data = try encoder.encode(manifest); guard data.count <= 4 * 1024 * 1024 else { throw MacRemoteError.invalid }; try data.write(to: url, options: .withoutOverwriting); sceneMessage = "已导出校验清单；已有文件不覆盖。" }
        catch { sceneMessage = "导出未完成；已有文件保留。" }
    }
    func sceneDisplay(_ node: String) {
        guard let view = sceneLocalView, MacObservationWindow.fresh(view), view["observations"][node]["state"].text == "process-running" else { return }
        sceneGenericCall(["action": .string("display"), "node": .string(node)])
    }
    func sceneRearm(_ node: String) {
        guard let view = sceneLocalView, MacObservationWindow.fresh(view), view["status"]["operation_id"] == .null else { return }
        sceneGenericCall(["action": .string("rearm-observer"), "instance_uuid": .string(sceneInstance), "generation": view["generation"],
            "state_revision": view["status"]["state_revision"], "node": .string(node), "attempt_id": .string(UUID().uuidString.lowercased())])
    }

    func sceneRearmLog(_ node: String) {
        guard let view = sceneLocalView, MacLogRecovery.allowed(view,node:node,busy:sceneWorkspaceBusy) else { return }
        sceneGenericCall(["action": .string("rearm-log"), "instance_uuid": .string(sceneInstance), "generation": view["generation"],
            "state_revision": view["status"]["state_revision"], "node": .string(node), "attempt_id": .string(UUID().uuidString.lowercased())])
    }

    var sceneAssetIDs: [String] {
        if case .object(let items) = scenePlan?["manifest"]["assets"] { return items.keys.sorted() }
        return []
    }
    var sceneNodeIDs: [String] {
        if case .object(let items) = scenePlan?["manifest"]["nodes"] { return items.keys.sorted() }
        return []
    }
    var sceneNetworkIDs: [String] {
        if case .object(let items) = scenePlan?["manifest"]["networks"] { return items.keys.sorted() }
        return []
    }
    func sceneMembers(_ network: String) -> String {
        sceneNodeIDs.filter { node in
            scenePlan?["manifest"]["nodes"][node]["interfaces"].items.contains { $0["network"].text == network } == true
        }.joined(separator: "  ↔  ")
    }
    var sceneUEFINodes: [String] { sceneNodeIDs.filter { scenePlan?["manifest"]["nodes"][$0]["firmware"].text == "uefi" } }
    func chooseSceneFile(_ kind: String, id: String = "", role: Int = 0) {
        guard !sceneWorkspaceBusy else { return }
        let picker = NSOpenPanel(); picker.canChooseDirectories = false; picker.allowsMultipleSelection = false
        guard picker.runModal() == .OK, let url = picker.url else { return }
        if kind == "profile" { sceneRuntimeProfile = url.path }
        else if kind == "manifest" { sceneManifest = url.path; scenePlan = nil; sceneSourceManifest = nil; sceneAssets = [:]; sceneFirmware = [:] }
        else if kind == "asset" { sceneAssets[id] = url.path }
        else { var pair = sceneFirmware[id] ?? ["", ""]; pair[role] = url.path; sceneFirmware[id] = pair }
        sceneSnapshot = nil; sceneLocalView = nil
    }
    func sceneRequest(_ action: String, list: Bool = false) {
        guard !sceneWorkspaceBusy, list || MacRemoteRules.uuid(sceneInstance) else { return }
        if sceneGeneric { sceneRequestGeneric(action, list: list); return }
        var value: [String: MacRemoteJSON] = ["action": .string(action), "instance_uuid": list ? .null : .string(sceneInstance)]
        if action == "preview" || action == "prepare" { value["manifest"] = .string(sceneManifest) }
        if action == "prepare" {
            value["manifest_sha256"] = .string(sceneManifestSHA)
            value["assets"] = .object(sceneAssets.mapValues { .string($0) })
            value["firmware"] = .object(sceneFirmware.mapValues { .array($0.map { .string($0) }) })
        }
        if !["status", "preview"].contains(action) {
            guard let checksum = sceneSnapshot else { sceneMessage = "请先读取当前实例状态，再确认本次操作。"; return }
            value["expected_sha256"] = .string(checksum)
        }
        if action == "start" { value["allow_emulation"] = .bool(sceneEmulation) }
        if action == "reset" {
            guard let generation = Int(sceneNewGeneration), generation >= 2 else { sceneMessage = "目标代次须为大于当前代次的整数。"; return }
            value["new_generation"] = .number(Double(generation))
        }
        do {
            let encoded = try MacRemoteJSON.object(value).encoded(), context = sceneInstance
            sceneWorkspaceBusy = true; sceneSnapshot = nil
            run(.scenarioClient(json: encoded)) { [weak self] outcome in
                guard let self else { return }; self.sceneWorkspaceBusy = false
                guard context == self.sceneInstance else { return }
                let output: String
                switch outcome { case .success(let v), .failure(let v): output = v }
                do {
                    let reply = try MacRemoteJSON.decode(output)
                    if let error = reply["error"]["message"].text { self.sceneMessage = error; return }
                    self.sceneReply = reply
                    if action == "preview" { self.scenePlan = reply["plan"]; self.sceneSourceManifest = reply["source_manifest"]; self.sceneManifestSHA = reply["manifest_sha256"].text ?? ""; self.sceneMessage = "设计已校验；尚未准备磁盘、启动或验证网络。" }
                    else if action == "status" {
                        if !list { self.sceneSnapshot = reply["snapshot_sha256"].text }
                        self.sceneMessage = "已读取现场；选择实例后再次读取，变更操作只用本次状态。"
                    } else { self.sceneMessage = "本次操作已返回。请重新读取状态；进程就绪不代表课程或隔离已验收。" }
                } catch { self.sceneMessage = "回复无法核验，结果未知；保留现场，不自动重发。" }
            }
        } catch { sceneMessage = "请求无法编码，请核对所选清单和资产。" }
    }

    // MARK: Wintermute 场景（独立状态根；不动单机 profile）

    func refreshScenario() {
        guard !scenarioBusy else { return }
        scenarioBusy = true
        run(.scenarioStatus) { [weak self] outcome in
            guard let self else { return }
            self.scenarioBusy = false
            switch outcome {
            case .success(let text):
                // 无实例时 CLI 输出提示文本而非 JSON；按空场景处理。
                if self.state.lastError == self.scenarioReadError {
                    self.state.lastError = nil
                }
                self.scenarioReadError = nil
                self.scenarioReports = ScenarioReport.decode(text) ?? []
            case .failure(let message):
                self.scenarioReadError = message
                self.state.lastError = message
            }
        }
    }

    func stopScenario() {
        guard !scenarioBusy else { return }
        scenarioBusy = true
        state.progressText = "正在按日志身份核验并请求正常停止；超时不强杀…"
        run(.scenarioStop) { [weak self] outcome in
            guard let self else { return }
            self.scenarioBusy = false
            self.state.progressText = ""
            switch outcome {
            case .success:
                break
            case .failure(let message):
                // 停止未全部完成（退出码 1）也给出输出，便于查看待停止成员。
                self.state.lastError = message
            }
            self.refreshScenario()
        }
    }

    func recoverScenario(closeReset: Bool, releaseOrphan: Bool) {
        guard !scenarioBusy else { return }
        scenarioBusy = true
        run(.scenarioRecover(closeReset: closeReset, releaseOrphan: releaseOrphan)) { [weak self] outcome in
            guard let self else { return }
            self.scenarioBusy = false
            if case .failure(let message) = outcome { self.state.lastError = message }
            self.refreshScenario()
        }
    }

    // MARK: CLI 调用

    private func run(_ action: CliAction, completion: @escaping @MainActor (CliOutcome) -> Void) {
        let arguments = action.arguments(stateDir: stateDirOverride)
        appendLog("$ \(action.displayCommand)")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: cliPath)
        process.arguments = arguments
        let privateInput = action.privateRequest
        guard privateInput == nil || privateInput!.count <= 4 * 1024 * 1024 else {
            completion(.failure("请求超过容量，本次没有启动CLI。")); return
        }
        guard let ticket = CLIRequestSlots.shared.acquire() else {
            completion(.failure("待核验的CLI请求已达上限，本次没有启动新进程；请先核对已有请求。")); return
        }
        let response = CLIResponseOnce { outcome in Task { @MainActor in completion(outcome) } }
        let lifetime = CLIRequestLifetime(ticket: ticket, hasInput: privateInput != nil)
        let inputPipe = privateInput == nil ? nil : Pipe()
        if let inputPipe { process.standardInput = inputPipe }
        var environment: [String: String] = [
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": ProcessInfo.processInfo.environment["LANG"] ?? "en_US.UTF-8",
        ]
        if let home = ProcessInfo.processInfo.environment["HOME"] { environment["HOME"] = home }
        if let stateDir = stateDirOverride { environment["CTFLAB_GUI_STATE_DIR"] = stateDir }
        if let stateDir = stateDirOverride {
            environment["CTFLAB_PROFILE_DIR"] = URL(fileURLWithPath: stateDir)
                .appendingPathComponent("profiles").path
        }
        var controlDirectory: URL?
        if action.controlsImport {
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ctflab-import-\(UUID().uuidString)")
            do {
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                       attributes: [.posixPermissions: 0o700])
                controlDirectory = directory
                activeImportControl = directory
                importCanCancel = true
                environment["CTFLAB_IMPORT_CANCEL_FILE"] = directory.appendingPathComponent("cancel").path
            } catch {
                ticket.release()
                response.finish(.failure("无法建立导入取消通道：\(error.localizedDescription)"))
                return
            }
        }
        let importDirectory = controlDirectory
        process.environment = environment
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        let handle = pipe.fileHandleForReading
        let buffer = OutputBuffer(limit: privateInput == nil ? 16 * 1024 * 1024 : 4 * 1024 * 1024)
        let collector = CLIPipeCollector(handle: handle, buffer: buffer)
        guard collector.canObserve else {
            ticket.release()
            if let directory = importDirectory {
                try? FileManager.default.removeItem(at: directory)
                if activeImportControl == directory { activeImportControl = nil; importCanCancel = false }
            }
            response.finish(.failure("无法建立CLI输出观察通道，本次没有启动进程。")); return
        }
        let updates = CLIOutputUpdates()
        let onChunk: @Sendable (Data) -> Void = { [weak self] chunk in
            if privateInput != nil {
                if buffer.overflowed { response.finish(.failure(buffer.snapshot().text)) }
                return
            }
            if updates.offer(chunk, progress: buffer.latestProgress()) {
                Task { @MainActor [weak self] in
                    let batch = updates.take()
                    guard let self else { return }
                    self.appendLog(batch.text)
                    if let directory = importDirectory, self.activeImportControl == directory,
                       !FileManager.default.fileExists(atPath: directory.appendingPathComponent("cancel").path),
                       let progress = batch.progress {
                        self.state.progressText = progress.label
                        self.importCanCancel = progress.cancellable
                    }
                }
            }
        }
        handle.readabilityHandler = { fileHandle in
            switch collector.receive(onChunk) {
            case .received: break
            case .eof: fileHandle.readabilityHandler = nil
            case .failed:
                fileHandle.readabilityHandler = nil
                if privateInput != nil { response.finish(.failure(buffer.snapshot().text)) }
            }
        }
        if privateInput != nil { response.startTimeout(seconds: 90) }
        process.terminationHandler = { [weak self] finished in
            handle.readabilityHandler = nil
            let closed = collector.drain(onChunk)
            lifetime.processFinished(outputClosed: closed)
            let snapshot = buffer.snapshot()
            let output = snapshot.text
            Task { @MainActor [weak self] in
                guard let self else { return }
                if closed, let directory = importDirectory {
                    try? FileManager.default.removeItem(at: directory)
                    if self.activeImportControl == directory {
                        self.activeImportControl = nil
                        self.importCanCancel = false
                    }
                }
                if case .onboardX86(let source, let id) = action,
                   finished.terminationStatus != 0, snapshot.candidateCreated {
                    self.retryCandidate = (id, source)
                }
                if !snapshot.complete {
                    response.finish(.failure(output))
                } else if finished.terminationStatus == 0 {
                    response.finish(.success(output))
                } else {
                    // 错误弹窗只截取尾部；候选是否已创建必须检查完整输出，
                    // 否则长转换/多条警告会把重试依据截掉。
                    let label = action.displayCommand
                    let message = action.preservesRawOutputOnFailure
                        ? output
                        : GuiMessages.failureMessage(
                            action: label, exitCode: finished.terminationStatus, output: output)
                    response.finish(.failure(message))
                }
            }
        }
        do {
            try process.run()
            if let privateInput, let inputPipe {
                DispatchQueue.global(qos: .userInitiated).async {
                    do {
                        try inputPipe.fileHandleForWriting.write(contentsOf: privateInput)
                        try inputPipe.fileHandleForWriting.close()
                        lifetime.inputFinished()
                    } catch {
                        buffer.markReadFailure()
                        do { try inputPipe.fileHandleForWriting.close(); lifetime.inputFinished() } catch {}
                        response.finish(.failure(buffer.snapshot().text))
                    }
                }
            }
        } catch {
            handle.readabilityHandler = nil
            ticket.release()
            try? inputPipe?.fileHandleForWriting.close()
            if let directory = importDirectory {
                try? FileManager.default.removeItem(at: directory)
                activeImportControl = nil
                importCanCancel = false
            }
            let message = "无法启动内置 CLI：\(error.localizedDescription)\n（\(cliPath)）"
            appendLog(message)
            response.finish(.failure(message))
        }
    }

    // 远程回调只更新同一上下文；页面重开不自动连接、重试或停止。
    private func remoteCall(_ value: MacRemoteJSON, completion: @escaping (MacRemoteJSON?) -> Void) {
        let ticket = remoteEpoch
        do {
            let encoded = try value.encoded()
            run(.remoteClient(json: encoded)) { [weak self] outcome in
                guard let self, ticket == self.remoteEpoch else { return }
                let text: String
                switch outcome { case .success(let v), .failure(let v): text = v }
                do {
                    let reply = try MacRemoteJSON.decode(text)
                    if let error = reply["error"]["message"].text { self.remoteMessage = error; completion(nil) }
                    else { completion(reply) }
                } catch { self.remoteMessage = "响应未能核验；结果未知，不自动重发。"; completion(nil) }
            }
        } catch { remoteMessage = "请求结构无法核验。"; completion(nil) }
    }
    func loadRemoteTargets() {
        guard !remoteBusy else { return }; remoteBusy = true
        remoteCall(.object(["action": .string("targets")])) { reply in
            self.remoteBusy = false
            guard let reply else { return }
            do { self.remoteTargets = try reply["targets"].items.map(MacSavedTarget.init) }
            catch { self.remoteTargets = []; self.remoteMessage = "目标列表无法核验。" }
        }
    }
    func chooseRemoteConfig() {
        let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false; panel.message = "选择管理员提供的私有SSH连接配置，不会连接服务器。"
        if panel.runModal() == .OK, let path = panel.url?.path { remoteConfig = path }
    }
    func saveRemoteTarget() {
        guard !remoteBusy, !remoteLabel.isEmpty, remoteConfig.hasPrefix("/") else { return }
        remoteBusy = true
        remoteCall(.object(["action": .string("save-target"), "id": .string(UUID().uuidString.lowercased()),
            "label": .string(remoteLabel), "config": .string(remoteConfig)])) { reply in
            self.remoteBusy = false
            if reply != nil { self.remoteMessage = "目标已保存；尚未连接，请明确选择连接。"; self.loadRemoteTargets() }
        }
    }
    func chooseRemoteIdentity(_ key: String) {
        guard ["identity", "known_hosts"].contains(key), !remoteBusy else { return }
        let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
        panel.message = key == "identity" ? "选择本机SSH身份文件；不复制私钥。" : "选择管理员提供的固定主机密钥文件。"
        if panel.runModal() == .OK, let path = panel.url?.path { remoteWizard[key] = path }
    }
    func createRemoteTarget() {
        guard !remoteBusy, !remoteLabel.isEmpty, let port = Int(remoteWizard["port"] ?? ""), (1...65535).contains(port),
              MacRemoteRules.uuid((remoteWizard["server_uuid"] ?? "").lowercased()),
              remoteWizard.values.allSatisfy({ !$0.isEmpty }) else { remoteMessage = "请填写目标名称、服务器标识、端口与身份/固定主机密钥文件。"; return }
        var config = remoteWizard.mapValues { MacRemoteJSON.string($0) }
        config["port"] = .number(Double(port)); config["server_uuid"] = .string((remoteWizard["server_uuid"] ?? "").lowercased())
        config["ssh"] = .string("/usr/bin/ssh")
        remoteBusy = true
        remoteCall(.object(["action": .string("create-target"), "id": .string(UUID().uuidString.lowercased()),
            "label": .string(remoteLabel), "config": .object(config)])) { reply in
            self.remoteBusy = false
            if reply != nil { self.remoteMessage = "私有配置已生成并保存；未连接或安装SSH，私钥未复制。"; self.loadRemoteTargets() }
        }
    }
    func disconnectRemote() {
        remoteEpoch += 1; remoteAdminOpen = false; remoteOffers = []; remoteCoursePlan = .null; remoteAudit = .null; remoteAuditPlan = .null; remoteOffer = ""; remoteCourseInstance = ""; remoteBusy = false; remoteConnectionID = nil; remoteContext = nil
        remoteView = .null; remoteLeases = .null; remotePending = []; remotePendingKnown = false
        remoteInstance = ""; remoteLease = ""; remoteStopConsent = false; remoteExports = []
        remoteUploads = []; remoteDownloads = []; remoteTransferID = nil
        remoteHistoryInFlight = false
        remoteMessage = "管理已断开；远程实验与传输不因关闭面板而停止，也不会自动重发。"
    }
    func connectRemote() {
        guard !remoteBusy, let saved = remoteTargets.first(where: { $0.id == remoteSelected }) else { return }
        disconnectRemote(); remoteSelected = saved.id; remoteBusy = true
        let identity = UUID().uuidString.lowercased(); remoteConnectionID = identity
        remoteCall(.object(["action": .string("connect"), "id": .string(saved.id), "connection_id": .string(identity)])) { reply in
            self.remoteBusy = false; self.remoteConnectionID = nil
            guard let reply else { return }
            if reply["connection_phase"].text == "cancelled" {
                self.remoteContext = nil; self.remoteMessage = "本次连接已取消；未发送实验变更。"; return
            }
            do {
                self.remoteContext = try MacRemoteContext(saved: saved, reply: reply)
                self.remoteMessage = "连接已核验；请选择分配实例，再明确读取状态。"
            } catch { self.remoteContext = nil; self.remoteMessage = "连接目标/权限无法核验；未发送实验变更。" }
        }
    }
    func cancelRemoteConnection() {
        guard let identity = remoteConnectionID else { return }
        remoteCall(.object(["action": .string("cancel-connect"), "id": .string(remoteSelected), "connection_id": .string(identity)])) { reply in
            guard let reply else { return }
            self.remoteMessage = reply["connection_phase"].text == "returned" ? "连接已经返回；取消不会追溯关闭它，可明确断开管理。" : "已登记本次连接取消；不停止远程实验。"
        }
    }
    func selectRemoteInstance(_ value: String) {
        guard !remoteBusy else { return }
        remoteEpoch += 1; remoteInstance = value; remoteView = .null; remoteLeases = .null
        remoteLease = ""; remoteStopConsent = false; remotePending = []; remotePendingKnown = false; remoteExports = []
    }
    private func remoteRead(_ action: String, context: MacRemoteContext) -> MacRemoteJSON {
        .object(["action": .string("request"), "id": .string(context.saved.id), "payload": .object([
            "action": .string(action), "target": .string(context.saved.target), "instance_uuid": .string(remoteInstance)])])
    }
    func refreshRemote() {
        guard !remoteBusy, let context = remoteContext, context.instances.contains(remoteInstance) else { return }
        remoteBusy = true; remotePendingKnown = false
        remoteCall(remoteRead("overview", context: context)) { reply in
            do {
                guard let reply else { throw MacRemoteError.invalid }
                self.remoteView = try MacRemoteRules.overview(reply, context: context, instance: self.remoteInstance, previous: self.remoteView)
            } catch { self.remoteView = .null; self.remoteBusy = false; return }
            @MainActor func pending() {
                self.remoteCall(.object(["action": .string("pending"), "id": .string(context.saved.id)])) { reply in
                    self.remoteBusy = false
                    guard let reply, reply["truncated"].flag == false else { self.remotePendingKnown = false; return }
                    self.remotePending = reply["attempts"].items
                    self.remotePendingKnown = self.remotePending.allSatisfy { MacRemoteRules.uuid($0["id"].text ?? "") && $0["payload"]["target"].text == context.saved.target }
                }
            }
            if context.leases {
                self.remoteCall(self.remoteRead("lease-status", context: context)) { reply in
                    self.remoteLeases = reply?["target"].text == context.saved.target ? reply?["result"] ?? .null : .null
                    pending()
                }
            } else { self.remoteLeases = .null; pending() }
        }
    }
    var remoteHasPending: Bool { !remotePendingKnown || !remotePending.isEmpty }
    func remoteAllowed(_ operation: String) -> Bool {
        if remoteContext?.leases == true, ["prepare", "start", "reset"].contains(operation),
           !MacRemoteRules.activeLease(remoteLeases, selected: remoteLease, instance: remoteInstance) { return false }
        return MacRemoteRules.allowed(operation, view: remoteView, context: remoteContext, instance: remoteInstance,
            lease: remoteLease, busy: remoteBusy, pending: remoteHasPending)
    }
    func performRemote(_ operation: String) {
        guard remoteAllowed(operation), let context = remoteContext else { return }
        do {
            let payload = try MacRemoteRules.operation(operation, view: remoteView, context: context, instance: remoteInstance, lease: remoteLease)
            sendRemoteMutation(payload, context: context)
        } catch { remoteMessage = "状态/目标已变化，请刷新。" }
    }
    func changeRemoteLease(_ action: String) {
        guard !remoteBusy, !remoteHasPending, let context = remoteContext, let ttl = Int(remoteTTL) else { return }
        do {
            let payload = try MacRemoteRules.lease(action, status: remoteLeases, context: context, instance: remoteInstance,
                selected: remoteLease, ttl: ttl, consent: remoteStopConsent)
            sendRemoteMutation(payload, context: context)
        } catch { remoteMessage = "租约权限/期限/状态无法核验，请刷新；到期停止策略还需要明确勾选。" }
    }
    private func sendRemoteMutation(_ payload: MacRemoteJSON, context: MacRemoteContext) {
        remoteBusy = true; remotePendingKnown = false
        remoteCall(.object(["action": .string("request"), "id": .string(context.saved.id), "payload": payload,
            "attempt_id": .string(UUID().uuidString.lowercased())])) { reply in
            self.remoteBusy = false
            if let reply, reply["target"].text == context.saved.target {
                let result = reply["result"]
                if result["state"].text == "active", result["time_state"].text == "active", MacRemoteRules.uuid(result["lease_id"].text ?? "") { self.remoteLease = result["lease_id"].text ?? "" }
                self.remoteMessage = "请求已返回；接收不等于执行完成，请以当前核验状态为准。"
            }
            self.refreshRemote()
        }
    }
    func loadRemoteAdminPending() {
        guard !remoteBusy, let context = remoteContext else { return }
        remoteBusy = true
        remoteCall(.object(["action": .string("pending"), "id": .string(context.saved.id)])) { reply in
            self.remoteBusy = false
            guard let reply, reply["truncated"].flag == false else { return }
            self.remotePending = reply["attempts"].items.filter { $0["payload"]["target"].text == context.saved.target }
        }
    }
    func remoteAdministration(_ action: String, values: [String: MacRemoteJSON] = [:]) {
        guard !remoteBusy, let context = remoteContext else { return }
        do {
            let payload = try MacRemoteRules.administration(action, context: context, values: values)
            var request: [String: MacRemoteJSON] = ["action": .string("request"), "id": .string(context.saved.id), "payload": payload]
            if ["course-provision", "audit-settle"].contains(action) { request["attempt_id"] = .string(UUID().uuidString.lowercased()) }
            remoteBusy = true
            remoteCall(.object(request)) { reply in
                self.remoteBusy = false
                do {
                    guard let reply else { throw MacRemoteError.invalid }
                    let result = try MacRemoteRules.administrationResult(reply, payload: payload, context: context)
                    switch action {
                    case "course-list": self.remoteOffers = result["offers"].items; self.remoteCoursePlan = .null
                    case "course-preview": self.remoteCoursePlan = result
                    case "audit-review": self.remoteAudit = result; self.remoteAuditPlan = .null
                    case "audit-settlement-preview": self.remoteAuditPlan = result
                    default:
                        self.remoteCoursePlan = .null; self.remoteAuditPlan = .null; self.remoteAudit = .null
                        self.remoteMessage = "管理请求已返回；课程尚需准备和实机验收，审计原执行结果仍为未知。"
                    }
                } catch {
                    self.remoteCoursePlan = .null; self.remoteAuditPlan = .null
                    self.remoteMessage = "管理响应未能核验。变更请求已在本机记录；可读取原请求后明确重试。"
                }
                self.loadRemoteAdminPending()
            }
        } catch { remoteMessage = "管理参数或当前权限无法核验，请重新选择并预览。" }
    }
    func retryRemoteAdministration(_ item: MacRemoteJSON) {
        guard !remoteBusy, let context = remoteContext, item["payload"]["target"].text == context.saved.target,
              let action = item["payload"]["action"].text, ["course-provision", "audit-settle"].contains(action),
              let identity = item["id"].text, MacRemoteRules.uuid(identity) else { return }
        remoteBusy = true
        remoteCall(.object(["action": .string("retry"), "attempt_id": .string(identity)])) { _ in
            self.remoteBusy = false; self.remoteCoursePlan = .null; self.remoteAuditPlan = .null; self.remoteAudit = .null
            self.loadRemoteAdminPending()
        }
    }
    func retryRemote(_ item: MacRemoteJSON) {
        guard !remoteBusy, let context = remoteContext, item["payload"]["target"].text == context.saved.target,
              item["payload"]["instance_uuid"].text == remoteInstance, let identity = item["id"].text, MacRemoteRules.uuid(identity) else { return }
        remoteBusy = true; remotePendingKnown = false
        remoteCall(.object(["action": .string("retry"), "attempt_id": .string(identity)])) { _ in self.remoteBusy = false; self.refreshRemote() }
    }
    func remoteDisplayAllowed(_ node: String) -> Bool {
        !remoteBusy && remoteContext?.display == true && remoteContext?.leases == true
            && remoteView["status"]["state"].text == "process-running" && remoteView["observations"][node]["state"].text == "process-running"
            && MacRemoteRules.activeLease(remoteLeases, selected: remoteLease, instance: remoteInstance)
    }
    func requestRemoteDisplay(_ node: String) {
        guard remoteDisplayAllowed(node), let context = remoteContext else { return }
        remoteBusy = true
        remoteCall(.object(["action": .string("display"), "id": .string(context.saved.id), "instance_uuid": .string(remoteInstance),
            "node": .string(node), "lease_id": .string(remoteLease)])) { reply in
            self.remoteBusy = false
            if reply != nil { self.remoteMessage = "已请求独立显示窗口；连接尚未验证，关闭窗口不会停止实验。" }
        }
    }

    func chooseRemoteAsset() {
        let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
        panel.message = "选择已获准上传的原始资产；不会执行或解包。"
        if panel.runModal() == .OK, let path = panel.url?.path { remoteAssetFile = path }
    }
    func refreshRemoteTransferHistory() {
        guard !remoteHistoryInFlight, let context = remoteContext else { return }; remoteHistoryInFlight = true
        remoteCall(.object(["action": .string("asset-history"), "id": .string(context.saved.id)])) { reply in
            self.remoteUploads = reply?["uploads"].items ?? []
            self.remoteCall(.object(["action": .string("evidence-history"), "id": .string(context.saved.id)])) { reply in
                self.remoteDownloads = reply?["downloads"].items ?? []; self.remoteHistoryInFlight = false
            }
        }
    }
    func uploadRemoteAsset() {
        guard !remoteBusy, let context = remoteContext, context.assets, remoteAssetFile.hasPrefix("/"), !remoteAssetSource.isEmpty else { return }
        let id = UUID().uuidString.lowercased(); remoteTransferID = ("asset", id); remoteBusy = true
        remoteCall(.object(["action": .string("asset-upload"), "id": .string(context.saved.id), "upload_id": .string(id),
            "file": .string(remoteAssetFile), "source": .string(remoteAssetSource), "audience": .string("student")])) { reply in
            self.remoteBusy = false; self.remoteTransferID = nil
            if reply != nil { self.remoteMessage = "本次传输已返回；历史verified不代表当前远端，需明确核对。" }
            self.refreshRemoteTransferHistory()
        }
    }
    func remoteTransferAction(_ action: String, kind: String, identity: String) {
        guard MacRemoteRules.uuid(identity), let context = remoteContext, ["asset", "evidence"].contains(kind) else { return }
        let cancelling = action.hasSuffix("cancel")
        let active = remoteTransferID?.kind == kind && remoteTransferID?.id == identity
        let history = kind == "asset" ? remoteUploads : remoteDownloads
        let key = kind == "asset" ? "upload_id" : "download_id"
        guard active || history.contains(where: { $0[key].text == identity && $0["target_id"].text == context.saved.id
            && (kind == "asset" || $0["instance_uuid"].text == remoteInstance) }) else { return }
        guard cancelling || (kind == "asset" ? context.assets : context.evidence) else { return }
        guard cancelling || !remoteBusy else { return }
        if !cancelling { remoteBusy = true; remoteTransferID = (kind, identity) }
        remoteCall(.object(["action": .string(action), kind == "asset" ? "upload_id" : "download_id": .string(identity)])) { reply in
            if !cancelling { self.remoteBusy = false; self.remoteTransferID = nil }
            if let reply {
                if action == "asset-probe" {
                    self.remoteMessage = reply["server_current_verified"].flag == true ? "服务器当前完整传输状态已核对；不代表课程可用。" : "服务器当前状态未通过完整核对；历史verified不作为当前证据。"
                } else { self.remoteMessage = cancelling ? "已请求暂停，部分文件和记录保留。" : "显式传输请求已返回；未自动打开或执行内容。" }
            }
            self.refreshRemoteTransferHistory()
        }
    }
    func listRemoteEvidence() {
        guard !remoteBusy, let context = remoteContext, context.evidence, context.instances.contains(remoteInstance) else { return }
        remoteBusy = true
        remoteCall(.object(["action": .string("evidence-list"), "id": .string(context.saved.id), "instance_uuid": .string(remoteInstance)])) { reply in
            self.remoteBusy = false; self.remoteExports = reply?["exports"].items ?? []
        }
    }
    func downloadRemoteEvidence(export: MacRemoteJSON, file: MacRemoteJSON) {
        guard !remoteBusy, let context = remoteContext, context.evidence, context.instances.contains(remoteInstance),
              let name = file["name"].text, let sha = file["sha256"].text, MacRemoteRules.digest(sha),
              MacRemoteRules.uuid(export["export_id"].text ?? ""), file["size"].integer != nil else { return }
        let id = UUID().uuidString.lowercased(); remoteTransferID = ("evidence", id); remoteBusy = true
        let payload: MacRemoteJSON = .object(["instance_uuid": .string(remoteInstance), "export_id": export["export_id"],
            "file": .string(name), "sha256": .string(sha), "size": file["size"]])
        remoteCall(.object(["action": .string("evidence-download"), "id": .string(context.saved.id),
            "download_id": .string(id), "payload": payload])) { reply in
            self.remoteBusy = false; self.remoteTransferID = nil
            if reply != nil { self.remoteMessage = "下载请求已返回；副本留在本机私有目录，不自动打开/解包。" }
            self.refreshRemoteTransferHistory()
        }
    }

    func appendLog(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .newlines)
        guard !trimmed.isEmpty else { return }
        log += (log.isEmpty ? "" : "\n") + trimmed
        if log.count > 120_000 {
            log = String(log.suffix(80_000))
        }
    }

    func copyError() {
        let text = state.lastError ?? log
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
        appendLog("已复制到剪贴板。")
    }
}

// MARK: - 界面

/// Wintermute 场景面板：只读状态 + 身份核验停止/显式恢复；不把进程存活称为题目可用。
struct ScenarioSection: View {
    @ObservedObject var model: GuiModel

    var body: some View {
        GroupBox("Wintermute 场景（三节点双隔离网；独立于单机节点）") {
            VStack(alignment: .leading, spacing: 8) {
                if model.scenarioReadError != nil {
                    Text("场景状态读取失败；无法判断是否存在或运行实例。请查看错误信息后重试。")
                        .foregroundStyle(.orange)
                        .font(.callout)
                } else if model.scenarioReports.isEmpty {
                    Text(model.scenarioBusy ? "正在读取场景状态…" : "状态根下没有场景实例；用 CLI `scenario prepare` 创建。")
                        .foregroundStyle(.secondary)
                        .font(.callout)
                }
                ForEach(model.scenarioReports, id: \.instance_uuid) { report in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(report.summaryState).bold()
                            Text(report.instance_uuid).font(.caption).foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        }
                        Text(report.stateDetail).font(.caption).foregroundStyle(.secondary)
                        ForEach(report.next ?? [], id: \.self) { hint in
                            Text("下一步：\(hint)").font(.caption).foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        }
                    }
                    .padding(.vertical, 2)
                }
                HStack {
                    Button("刷新状态") { model.refreshScenario() }
                        .disabled(model.scenarioBusy)
                    Button("请求正常停止…") { model.showScenarioStopConfirmation = true }
                        .disabled(model.scenarioBusy || model.scenarioReadError != nil || model.scenarioReports.isEmpty)
                    Button("收口重置事务") {
                        model.recoverScenario(closeReset: true, releaseOrphan: false)
                    }
                    .disabled(model.scenarioBusy || model.scenarioReadError != nil || model.scenarioReports.isEmpty)
                    Button("释放接续孤儿预约") {
                        model.recoverScenario(closeReset: false, releaseOrphan: true)
                    }
                    .disabled(model.scenarioBusy || model.scenarioReadError != nil || model.scenarioReports.isEmpty)
                }
                Text("准备/启动/重置需用 CLI scenario 子命令；进程与 QMP 已核验不代表来宾地址、题目或隔离已验收。")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(4)
        }
        .onAppear { model.refreshScenario() }
    }
}

struct RecoverySheet: View {
    @ObservedObject var model: GuiModel
    @Environment(\.dismiss) private var dismiss

    private func request(_ operation: String, _ name: String) {
        model.recoveryPending = .snapshot(profileID: model.recoveryProfileID,
                                          operation: operation, name: name)
        model.showRecoveryConfirmation = true
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("快照与备份 · \(LabNode.displayName(for: model.recoveryProfileID))").font(.title2)
            Text("仅对已停止节点操作。恢复快照前自动保存当前恢复点；恢复整盘备份前自动保留当前实例。删除恢复点不可撤销。")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                TextField("快照名（小写英文、数字、._-，最多 32 字符）", text: $model.recoveryName)
                Button("创建快照") {
                    model.performRecovery(.snapshot(profileID: model.recoveryProfileID,
                                                     operation: "create", name: model.recoveryName))
                }.disabled(model.state.phase.isBusy || !RecoveryRules.validName(model.recoveryName))
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    Text("磁盘快照").font(.headline)
                    if model.recoverySnapshots.isEmpty { Text("暂无快照（首次启动后可创建）").foregroundStyle(.secondary) }
                    ForEach(model.recoverySnapshots) { item in
                        HStack {
                            Text(item.tag); Text(item.date).foregroundStyle(.secondary); Spacer()
                            Button("恢复…") { request("revert", item.tag) }
                            Button("删除…", role: .destructive) { request("delete", item.tag) }
                        }
                    }
                    Divider()
                    Text("整盘备份").font(.headline)
                    if model.recoveryBackups.isEmpty { Text("暂无整盘备份").foregroundStyle(.secondary) }
                    ForEach(model.recoveryBackups) { item in
                        HStack {
                            Text(item.name)
                            if !item.complete { Text("不完整").foregroundStyle(.orange) }
                            Spacer()
                            Button("恢复…") { request("restore-backup", item.name) }.disabled(!item.complete)
                            Button("删除…", role: .destructive) { request("delete-backup", item.name) }
                        }
                    }
                    Button("备份当前实例并重置…") {
                        model.recoveryPending = .backupReset(profileID: model.recoveryProfileID)
                        model.showRecoveryConfirmation = true
                    }
                }.disabled(model.state.phase.isBusy)
            }
            if let error = model.state.lastError { Text(error).font(.caption).foregroundStyle(.red).textSelection(.enabled) }
            HStack {
                Button("刷新") { model.loadRecovery() }.disabled(model.state.phase.isBusy)
                Spacer()
                Button("关闭") { dismiss() }.disabled(model.state.phase.isBusy)
            }
        }
        .padding(20).frame(width: 720, height: 480)
        .interactiveDismissDisabled(model.state.phase.isBusy)
        .alert("确认恢复点操作？", isPresented: $model.showRecoveryConfirmation) {
            Button("取消", role: .cancel) { model.recoveryPending = nil }
            Button("确认执行", role: .destructive) { model.confirmRecovery() }
        } message: {
            Text("只作用于 \(model.recoveryProfileID)。恢复会改变当前实验内容；删除快照或备份不可撤销。其他节点与原始镜像不受影响。")
        }
    }
}

struct CourseManagerSheet: View {
    @ObservedObject var model: GuiModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("课程组合").font(.title2)
            if !model.courseResults.isEmpty {
                ScrollView {
                    ForEach(model.courseResults.keys.sorted(), id: \.self) { id in
                        Text("\(LabNode.displayName(for: id))：\(model.courseResults[id] ?? "未知")").font(.caption)
                    }
                }.frame(maxHeight: 100)
            }
            Text("组合只记录节点 ID，不修改镜像或网络。启动前会列出待启动节点并要求确认；默认单节点操作保持不变。")
                .font(.caption).foregroundStyle(.secondary)
            TextField("组合名称", text: $model.courseDraftName).textFieldStyle(.roundedBorder)
            ScrollView {
                VStack(alignment: .leading) {
                    ForEach(model.nodes.filter(\.imported)) { node in
                        Toggle(node.name ?? node.id, isOn: Binding(
                            get: { model.courseDraftSelected.contains(node.id) },
                            set: { if $0 { model.courseDraftSelected.insert(node.id) } else { model.courseDraftSelected.remove(node.id) } }))
                    }
                }
            }.frame(maxHeight: 180)
            Button("保存组合") {
                model.libraryPreferences.courses.append(NodeCourse(name: model.courseDraftName,
                                                                  profileIDs: Array(model.courseDraftSelected)))
                model.saveLibraryPreferences(); model.courseDraftName = ""; model.courseDraftSelected.removeAll()
            }.disabled(model.courseDraftName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.courseDraftSelected.isEmpty)
            Divider()
            ScrollView {
                ForEach(model.libraryPreferences.courses) { course in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(course.name)
                            Text(course.profileIDs.joined(separator: "、")).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("启动…") { model.requestCourseStart(course) }
                            .disabled(model.state.phase.isBusy)
                        Button("删除组合") {
                            model.libraryPreferences.courses.removeAll { $0.id == course.id }
                            model.saveLibraryPreferences()
                        }
                    }.padding(.vertical, 4)
                }
            }
            if let error = model.state.lastError {
                Text(error).foregroundStyle(.red).textSelection(.enabled)
            }
            HStack { Spacer(); Button("关闭") { dismiss() } }
        }.padding(20).frame(width: 680, height: 560)
        .alert("确认启动课程组合？", isPresented: $model.showCourseConfirmation) {
            Button("取消", role: .cancel) { model.pendingCourse = nil }
            Button("启动这些节点") { model.confirmCourseStart(); dismiss() }
        } message: {
            Text("仅启动：\(model.pendingCourse?.profileIDs.joined(separator: "、") ?? "")。已运行节点不重复启动；遇到错误停止后续队列，已有节点保持运行。网络策略不会改变。")
        }
    }
}

private enum MacWorkspacePage: String, CaseIterable {
    case library = "镜像库", experiments = "实验", topology = "拓扑", templates = "模板", remote = "远程", versions = "版本", diagnostics = "诊断"
    var icon: String {
        switch self {
        case .library: return "square.stack.3d.up"
        case .experiments: return "play.rectangle"
        case .topology: return "point.3.connected.trianglepath.dotted"
        case .templates: return "square.grid.2x2"
        case .remote: return "network"
        case .versions: return "arrow.triangle.2.circlepath"
        case .diagnostics: return "waveform.path.ecg"
        }
    }
    var subtitle: String {
        switch self {
        case .library: return "管理镜像，直接进入你的实验节点。"
        case .experiments: return "选择实验，查看状态，控制一次完整的运行。"
        case .topology: return "从节点到网段，清楚看到实验的连接关系。"
        case .templates: return "配置可复用场景，校验设计后再建立实验。"
        case .remote: return "连接受限运行器，管理远程实验与课程。"
        case .versions: return "校验本地更新，选择版本与恢复入口。"
        case .diagnostics: return "检查当前状态，整理可以分享的诊断证据。"
        }
    }
}

private final class MacWorkspaceSelection: ObservableObject {
    @Published var page: MacWorkspacePage = .library
    @Published var editTopology = false
    @Published var showActivity = false
}

struct ContentView: View {
    @ObservedObject var model: GuiModel
    @StateObject private var workspace = MacWorkspaceSelection()

    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 10) {
                    Image(systemName: "cube.transparent.fill").font(.system(size: 28)).foregroundStyle(.blue)
                    VStack(alignment: .leading) { Text("CTFLab").font(.title2.bold()); Text("本地实验工作台").font(.caption).foregroundStyle(.secondary) }
                }.padding(.horizontal, 8).padding(.top, 8)
                VStack(spacing: 3) {
                    // Cmd+1…7 直接切换页面：侧栏按钮同时注册键盘快捷键，无需先聚焦。
                    ForEach(Array(MacWorkspacePage.allCases.enumerated()), id: \.element) { offset, item in
                        Button { workspace.page = item } label: {
                            HStack(spacing: 10) { Image(systemName: item.icon).frame(width: 22); Text(item.rawValue); Spacer(); if workspace.page == item { Image(systemName: "chevron.right").font(.caption2) } }
                                .font(.system(size: 13, weight: workspace.page == item ? .semibold : .regular))
                                .padding(.horizontal, 12).padding(.vertical, 8)
                                .background(workspace.page == item ? Color.accentColor.opacity(0.13) : .clear, in: RoundedRectangle(cornerRadius: 9))
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(workspace.page == item ? Color.accentColor : .primary)
                        .keyboardShortcut(KeyEquivalent(Character(String(offset + 1))), modifiers: .command)
                        .accessibilityLabel("切换到\(item.rawValue)（Command \(offset + 1)）")
                    }
                }
                Divider()
                imageListColumn
            }.padding(12)
                .navigationTitle("工作空间")
                .navigationSplitViewColumnWidth(min: 290, ideal: 320, max: 400)
        } detail: {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(workspace.page.rawValue).font(.system(size: 29, weight: .bold))
                        Text(workspace.page.subtitle).font(.callout).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button { workspace.showActivity.toggle() } label: { Label("活动", systemImage: "text.alignleft") }
                }
                if let error = model.state.lastError { errorBanner(error) }
                workspaceContent.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                if workspace.showActivity { logPanel }
            }.padding(24)
                .background(Color(nsColor: .windowBackgroundColor))
                .navigationTitle("CTFLab · " + workspace.page.rawValue)
        }
        .navigationSplitViewStyle(.balanced)
        .tint(.accentColor)
        .frame(minWidth: 1040, minHeight: 740)
        .alert(GuiMessages.resetConfirmationTitle, isPresented: $model.showResetConfirmation) {
            Button(GuiMessages.resetCancelButton, role: .cancel) {}
            Button(GuiMessages.resetConfirmButton, role: .destructive) { model.confirmReset() }
        } message: {
            Text(GuiMessages.resetConfirmationBody)
        }
        .alert("停止 Wintermute 场景？", isPresented: $model.showScenarioStopConfirmation) {
            Button(GuiMessages.resetCancelButton, role: .cancel) {}
            Button("请求正常停止", role: .destructive) { model.stopScenario() }
        } message: {
            Text("会按日志身份核验后向节点请求 ACPI 关机、再停止双网服务；超时会保留待停止状态，不会强杀或删除任何资产。")
        }
        .alert("确认重置节点？", isPresented: $model.showNodeResetConfirmation) {
            Button(GuiMessages.resetCancelButton, role: .cancel) {}
            Button(GuiMessages.resetConfirmButton, role: .destructive) { model.confirmNodeReset() }
        } message: {
            Text("只会删除该节点的运行 overlay，节点内的实验改动会丢失；基础镜像不受影响，其他节点不受影响。")
        }
        .alert("删除这个镜像？", isPresented: $model.showImageRemoveConfirmation) {
            Button(GuiMessages.resetCancelButton, role: .cancel) {}
            Button("删除", role: .destructive) { model.confirmImageRemove() }
        } message: {
            Text("会删除该节点的导入数据（基盘副本与运行 overlay），并从列表移除；你的原始镜像文件不受影响，之后可重新导入。")
        }
        .sheet(isPresented: $model.showImageOnboarding) {
            ImageOnboardingSheet(model: model)
        }
        .sheet(isPresented: $model.showRecovery) { RecoverySheet(model: model) }
        .sheet(isPresented: $model.showCourseManager) { CourseManagerSheet(model: model) }
        .sheet(isPresented: $model.showRemoteWorkspace) { MacRemoteSheet(model: model) }
        .sheet(isPresented: $model.showScenarioWorkspace) { MacScenarioSheet(model: model) }
        .sheet(item: $model.publicDiagnostics) { snapshot in
            PublicDiagnosticsSheet(model: model, snapshot: snapshot)
        }
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            model.refreshAutomatically()
        }
    }

    @ViewBuilder private var workspaceContent: some View {
        switch workspace.page {
        case .library:
            VStack(alignment: .leading, spacing: 16) {
                actionRow
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        detailColumn.frame(minHeight: 320)
                        DisclosureGroup("文件夹与成套导入") { directoryRow; verifyTable }
                        DisclosureGroup("Wintermute 课程快捷操作") { ScenarioSection(model: model) }
                    }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
                }.background(.background, in: RoundedRectangle(cornerRadius: 16))
            }
        case .experiments:
            MacScenarioSheet(model: model, embedded: true)
        case .topology:
            topologyWorkspace
        case .templates:
            MacScenarioSheet(model: model, embedded: true, configurationOnly: true)
        case .remote:
            MacRemoteSheet(model: model, embedded: true)
        case .versions:
            VStack(alignment: .leading, spacing: 20) {
                Label("本地版本管理", systemImage: "shippingbox").font(.title2.bold())
                Text("选择更新包后先校验，再打开已核验的版本。保留上一槽位用于回退。切换版本前请妥善处理正在进行的操作。")
                    .foregroundStyle(.secondary)
                Button("校验本地 App 更新…") { model.stageLocalUpdate() }
                Button("打开所选更新版本…") { model.launchUpdate() }
                Button("回退上个更新槽位…") { model.rollbackUpdate() }
                Text(model.updateMessage.isEmpty ? "尚未校验本地更新包。" : model.updateMessage).textSelection(.enabled)
                Spacer()
            }.padding(24).frame(maxWidth: .infinity, alignment: .leading).background(.background, in: RoundedRectangle(cornerRadius: 16)).disabled(model.state.phase.isBusy)
        case .diagnostics:
            VStack(alignment: .leading, spacing: 20) {
                Label("状态与证据", systemImage: "stethoscope").font(.title2.bold())
                Text(model.state.statusLine).textSelection(.enabled)
                Button("检查状态") { model.checkStatus() }.disabled(!model.state.canCheckStatus)
                Button("预览可分享诊断摘要…") { model.previewPublicDiagnostics() }.disabled(model.state.phase.isBusy || model.nodes.isEmpty)
                Button("导出完整本机诊断（私密）…") { model.exportDiagnostics() }.disabled(model.state.phase.isBusy)
                Text("分享前可预览摘要；完整诊断可能包含本机路径，应保留在私有环境。") .font(.caption).foregroundStyle(.secondary)
                logPanel
                Spacer()
            }.padding(24).frame(maxWidth: .infinity, alignment: .leading).background(.background, in: RoundedRectangle(cornerRadius: 16))
        }
    }

    private var topologyWorkspace: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Picker("视图", selection: $workspace.editTopology) { Text("连接总览").tag(false); Text("编辑草稿").tag(true) }.pickerStyle(.segmented).frame(width: 240)
                Spacer()
                Button("选择实验") { workspace.page = .experiments }
                Button("读取此实例状态") { model.sceneRequest("status") }.disabled(model.sceneWorkspaceBusy)
            }
            if workspace.editTopology {
                if model.sceneDraft != .null && model.sceneDraftContext == model.sceneInstance && model.sceneGeneric {
                    MacGraphSheet(model: model, embedded: true)
                } else {
                    VStack(alignment: .leading, spacing: 16) {
                        Label("从已读取的通用实验载入设计", systemImage: "pencil.and.outline").font(.title3.bold())
                        Text("先在实验页选择通用实例并读取状态，再载入草稿。编辑只生成新设计，不会更改运行中的节点或连线。")
                        Button("载入当前实验草稿") { model.sceneLoadDraft() }.disabled(model.sceneLocalView == nil || !model.sceneGeneric || model.sceneWorkspaceBusy)
                    }.padding(24)
                }
            } else if let view = model.sceneLocalView {
                TimelineView(.periodic(from: .now, by: 1)) { _ in
                    MacRuntimeTopology(view: view, expanded: true).padding(20)
                }
            } else if let manifest = model.sceneSourceManifest, let design = MacDesignTopology.project(manifest) {
                VStack(alignment: .leading, spacing: 12) {
                    Label("清单设计 · 尚未读取运行状态", systemImage: "pencil.and.outline").font(.headline)
                    MacRuntimeTopology(view: design, expanded: true)
                }.padding(20)
            } else {
                VStack(alignment: .leading, spacing: 18) {
                    Label("资源节点", systemImage: "square.stack.3d.up").font(.headline)
                    Text("尚未读取场景连接。下面是已导入的真实资源，不推断它们之间的网络关系；选择实验后可查看节点、网卡、网段与设计连线。")
                        .font(.callout).foregroundStyle(.secondary)
                    ScrollView {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 18)], spacing: 18) {
                            ForEach(filteredNodes, id: \.id) { node in
                                Button { model.selectedFilePath = nil; model.selectNode(node.id); workspace.page = .library } label: {
                                    VStack(alignment: .leading, spacing: 12) {
                                        Image(systemName: "desktopcomputer").font(.system(size: 30)).foregroundStyle(.blue)
                                        Text(node.name ?? LabNode.displayName(for: node.id)).font(.headline)
                                        Text("资源节点 · 未读取场景连接").font(.caption).foregroundStyle(.secondary)
                                        Label("查看节点", systemImage: "arrow.up.right") .font(.caption)
                                    }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
                                        .background(.blue.opacity(0.06), in: RoundedRectangle(cornerRadius: 14))
                                }.buttonStyle(.plain)
                            }
                        }
                        if filteredNodes.isEmpty { ContentUnavailableView("还没有镜像节点", systemImage: "square.stack.3d.up", description: Text("到镜像库添加资源，或在实验页选择已有实例。")) }
                    }
                }.padding(24)
            }
            Spacer(minLength: 0)
        }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(.background, in: RoundedRectangle(cornerRadius: 16))
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("实验工作台").font(.system(size: 28, weight: .bold))
                Text(model.state.statusLine).font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            Label("本地运行", systemImage: "desktopcomputer")
                .font(.caption).foregroundStyle(.secondary)
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(.regularMaterial, in: Capsule())
        }
        .help("状态目录：\(model.stateDirLabel)")
    }

    private var directoryRow: some View {
        HStack(spacing: 8) {
            Text("镜像文件夹")
            Text(model.state.distDir ?? "（未选择——也可以不选，直接启动已导入的节点）")
                .textSelection(.enabled)
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(6)
                .background(Color(nsColor: .textBackgroundColor))
                .cornerRadius(4)
            Button("选择…") { model.chooseDistributionDirectory() }
            if model.state.distDir != nil {
                Button("扫描并导入新增") { model.scanAndImport() }
                    .disabled(model.state.phase.isBusy)
            }
        }
    }

    /// 顶部操作区：节点级操作移入右侧详情栏，这里只留导入与低频菜单。
    private var actionRow: some View {
        HStack(spacing: 10) {
            Menu("导入…") {
                Button("添加 x86 镜像…") { model.chooseX86Image() }
                    .disabled(model.state.phase.isBusy)
                Divider()
                Button("校验成套分发…") { model.verifyDistribution() }
                    .disabled(!model.state.canVerify)
                Button("导入成套实验环境") { model.importAll() }
                    .disabled(!model.state.canImport)
            }
            Menu("更多") {
                if !model.updateMessage.isEmpty { Text(model.updateMessage) }
                Button("校验本地 App 更新…") { model.stageLocalUpdate() }.disabled(model.state.phase.isBusy)
                Button("回退上个更新槽位…") { model.rollbackUpdate() }.disabled(model.state.phase.isBusy)
                Button("打开所选更新版本…") { model.launchUpdate() }.disabled(model.state.phase.isBusy)
                Divider()
                Button("检查状态") { model.checkStatus() }
                    .disabled(!model.state.canCheckStatus)
                Button("分享诊断摘要…") { model.previewPublicDiagnostics() }
                    .disabled(model.state.phase.isBusy || model.nodes.isEmpty)
                Button("完整本机诊断（私密）…") { model.exportDiagnostics() }
                    .disabled(model.state.phase.isBusy)
                Divider()
                Toggle("共享文本剪贴板（启动时生效）", isOn: $model.clipboardSharingEnabled)
                Toggle("允许向 Kali 拖入文件（独立授权；启动时生效）", isOn: $model.fileTransferEnabled)
                Toggle("清晰优先（Retina 像素，UI 更小；默认流畅）", isOn: $model.displayQualitySharp)
                Picker("Kali 资源（下次启动生效）", selection: $model.resourcePreset) {
                    Text("沿用镜像配置").tag("original")
                    Text("轻量 · 2GiB / 2 核").tag("light")
                    Text("均衡 · 4GiB / 4 核").tag("balanced")
                    Text("性能 · 8GiB / 4 核").tag("performance")
                }
                Divider()
                Button("重置全部节点…") { model.requestReset() }
                    .disabled(!model.state.canReset)
            }
            Spacer()
            if model.state.phase.isBusy || !model.state.progressText.isEmpty {
                ProgressView().controlSize(.small)
                Text(model.state.progressText).font(.caption)
            }
            if model.state.phase == .importing {
                Button("取消当前导入") { model.cancelCurrentImport() }
                    .disabled(!model.importCanCancel)
                Button("停止后续导入") { model.stopRemainingImports() }
                    .disabled(model.stopImportQueueRequested)
            }
            Button("本机场景…") { model.showScenarioWorkspace = true }
            Button("远程实验…") { model.showRemoteWorkspace = true }
            Button("课程组合…") { model.showCourseManager = true }
                .disabled(model.state.phase.isBusy)
        }
    }

    /// 主区两栏：左侧统一镜像列表（已导入节点 + 文件夹候选），右侧当前状态与操作。
    private var mainSplit: some View {
        HStack(alignment: .top, spacing: 0) {
            imageListColumn
                .frame(width: 460)
            Divider()
            detailColumn
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(minHeight: 440)
    }

    /// 统一选择：节点用 profile ID，文件夹镜像用 "file:"+路径。
    private var listSelection: Binding<String?> {
        Binding(
            get: {
                if let path = model.selectedFilePath { return "file:\(path)" }
                return model.state.selectedProfileID
            },
            set: { newValue in
                guard let newValue, !newValue.isEmpty else {
                    model.selectedFilePath = nil
                    model.selectNode(nil)
                    return
                }
                workspace.page = .library
                if newValue.hasPrefix("file:") {
                    model.state.selectedProfileID = nil
                    model.selectedFilePath = String(newValue.dropFirst(5))
                } else {
                    model.selectedFilePath = nil
                    model.selectNode(newValue)
                }
            })
    }

    /// 左侧列表只显示已导入的镜像（用户以文件夹为来源的模型）；
    /// 未导入登记不占列表，仍可通过 CLI 管理。
    private var filteredNodes: [StatusProfile] {
        let eligible = model.nodes.filter { node in
            (node.imported || node.importState == "missing-base") && model.nodeStatusFilter.matches(node)
                && (!model.favoritesOnly || model.libraryPreferences.favorites.contains(node.id))
                && (model.groupFilter.isEmpty || model.libraryPreferences.groups[node.id] == model.groupFilter)
        }
        return model.libraryPreferences.ordered(NodeSearch.filter(eligible, query: model.nodeSearchText),
                                                recentFirst: model.recentFirst)
    }

    /// “文件夹镜像”分组 = 真正待导入的文件（与自动导入同一判据）再过搜索框；
    /// 已导入/历史来源的文件不显示，导入完成后分组为空即整组隐藏。
    private var filteredLibrary: [ImageLibraryEntry] {
        let query = model.nodeSearchText.trimmingCharacters(in: .whitespaces)
        let pending = model.pendingImageEntries()
        guard !query.isEmpty else { return pending }
        return pending.filter { $0.fileName.localizedCaseInsensitiveContains(query) }
    }

    private var imageListColumn: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Label("镜像与节点", systemImage: "externaldrive").font(.headline)
                Spacer()
                Text("\(filteredNodes.count) 个")
                    .font(.caption).foregroundStyle(.secondary)
            }
            HStack(spacing: 6) {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField("搜索（ID、名称、文件名）", text: $model.nodeSearchText)
                    .textFieldStyle(.roundedBorder)
                if !model.nodeSearchText.isEmpty {
                    Button("清除") { model.nodeSearchText = "" }
                }
            }
            Picker("状态", selection: $model.nodeStatusFilter) {
                ForEach(NodeStatusFilter.allCases, id: \.self) { filter in Text(filter.rawValue).tag(filter) }
            }.font(.caption)
            HStack {
                Toggle("仅收藏", isOn: $model.favoritesOnly)
                Toggle("最近使用优先", isOn: $model.recentFirst)
                Picker("分组", selection: $model.groupFilter) {
                    Text("全部").tag("")
                    ForEach(Array(Set(model.libraryPreferences.groups.values)).sorted(), id: \.self) { group in
                        Text(group).tag(group)
                    }
                }
            }.font(.caption)
            List(selection: listSelection) {
                Section("镜像") {
                    ForEach(filteredNodes) { node in
                        imageNodeRow(node).tag(node.id)
                    }
                }
                if !filteredLibrary.isEmpty {
                    Section("文件夹新增（待导入）") {
                        ForEach(filteredLibrary) { entry in
                            imageFileRow(entry).tag("file:\(entry.path)")
                        }
                    }
                }
            }
            .listStyle(.sidebar)
        }
        .padding(.trailing, 0)
    }

    private func imageNodeRow(_ node: StatusProfile) -> some View {
        let nodeState = NodeOperationalState.state(for: node)
        return HStack(spacing: 8) {
            Circle()
                .fill(nodeState.isProblem ? Color.orange :
                      (nodeState == .running ? Color.green : Color.secondary.opacity(0.5)))
                .frame(width: 8, height: 8)
            if model.libraryPreferences.favorites.contains(node.id) {
                Image(systemName: "star.fill").foregroundStyle(.yellow)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(node.name ?? LabNode.displayName(for: node.id))
                    .lineLimit(1)
                if (node.name ?? node.id) != node.id {
                    Text(node.id).font(.caption2).foregroundStyle(.secondary)
                }
            }
            Spacer()
            Text(node.imported ? nodeState.rawValue : "未导入")
                .font(.caption)
                .foregroundStyle(node.imported
                                 ? (nodeState.isProblem ? Color.orange :
                                    (nodeState == .running ? Color.green : Color.secondary))
                                 : Color.secondary.opacity(0.7))
        }
        .padding(.vertical, 7)
        .accessibilityElement(children: .combine)
        .contextMenu {
            Button(model.libraryPreferences.favorites.contains(node.id) ? "取消收藏" : "收藏此节点") {
                model.toggleFavorite(node.id)
            }
            if node.running {
                Button("停止此节点") { model.stopProfile(node.id) }
                Button("重启此节点") { model.selectNode(node.id); model.restartSelected() }
            } else if node.imported {
                Button("启动此节点") { model.startProfile(node.id) }
            }
            if !node.imported && !node.running && node.builtin != true {
                Button("移除这条登记…") { model.deregisterProfile(node.id) }
            }
        }
    }

    private func imageFileRow(_ entry: ImageLibraryEntry) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "externaldrive").foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 1) {
                Text(entry.fileName).lineLimit(1)
                Text(entry.sizeBytes.map(Self.humanSize) ?? "—")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            Spacer()
            Text("未导入").font(.caption).foregroundStyle(.secondary.opacity(0.7))
        }
        .padding(.vertical, 2)
    }

    /// 右栏：选中镜像的当前状态与操作按钮；未选中时给出入口提示。
    @ViewBuilder
    private var detailColumn: some View {
        if let path = model.selectedFilePath {
            folderFileDetail(path)
        } else if let id = model.state.selectedProfileID,
                  let node = model.nodes.first(where: { $0.id == id }) {
            nodeDetail(node)
        } else {
            ContentUnavailableView {
                Label("选择一个实验", systemImage: "square.stack.3d.up")
            } description: {
                Text(model.nodes.filter(\.imported).isEmpty
                     ? "选择镜像文件夹或导入镜像，建立你的第一个实验。"
                     : "从资源库选择镜像，查看运行状态并继续实验。")
            }
        }
    }

    private func folderFileDetail(_ path: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("镜像文件").font(.headline)
            if let entry = model.imageLibrary.first(where: { $0.path == path }) {
                LabeledContent("文件") {
                    Text(entry.fileName).textSelection(.enabled)
                }
                LabeledContent("大小") {
                    Text(entry.sizeBytes.map(Self.humanSize) ?? "—")
                }
            }
            LabeledContent("路径") {
                Text(path).textSelection(.enabled).lineLimit(2)
                    .truncationMode(.middle)
            }
            Button("识别并导入…") { model.beginOnboarding(sourcePath: path) }
                .disabled(model.state.phase.isBusy)
            Text("只读识别后确认候选硬件，才会创建配置并导入派生基盘；原始镜像保持不变。导入完成后镜像会出现在左侧列表。")
                .font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(.leading, 12)
    }

    private func nodeDetail(_ node: StatusProfile) -> some View {
        let nodeState = NodeOperationalState.state(for: node)
        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text("当前状态").font(.headline)
                Spacer()
                if node.builtin == true {
                    Text("内置课程包").font(.caption)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Color.secondary.opacity(0.15)).cornerRadius(4)
                }
            }
            LabeledContent("节点") {
                VStack(alignment: .trailing) {
                    Text(node.name ?? LabNode.displayName(for: node.id))
                    if (node.name ?? node.id) != node.id {
                        Text(node.id).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            HStack {
                Button(model.libraryPreferences.favorites.contains(node.id) ? "取消收藏" : "收藏") {
                    model.toggleFavorite(node.id)
                }
                TextField("分组（回车保存）", text: Binding(
                    get: { model.groupDrafts[node.id] ?? model.libraryPreferences.groups[node.id] ?? "" },
                    set: { model.groupDrafts[node.id] = String($0.prefix(64)) }))
                    .onSubmit {
                        model.libraryPreferences.setGroup(model.groupDrafts[node.id] ?? model.libraryPreferences.groups[node.id] ?? "", for: node.id)
                        model.groupDrafts.removeValue(forKey: node.id)
                        model.saveLibraryPreferences()
                    }
                    .textFieldStyle(.roundedBorder)
            }
            LabeledContent("状态") {
                Text(node.imported ? nodeState.rawValue : "未导入")
                    .foregroundStyle(node.imported
                                     ? (nodeState.isProblem ? Color.orange :
                                        (nodeState == .running ? Color.green : Color.primary))
                                     : Color.secondary)
            }
            LabeledContent("启动进度") {
                if let boot = node.boot {
                    Text(boot.displayText)
                        .foregroundStyle(boot.isTimedOut ? Color.orange : Color.secondary)
                } else {
                    Text(node.running ? "读取中…" : "—").foregroundStyle(.secondary)
                }
            }
            if let stages = node.boot?.stages {
                ForEach(Array(stages.enumerated()), id: \.offset) { _, stage in
                    HStack {
                        Image(systemName: stage.ok == true ? "checkmark.circle.fill" : "clock")
                            .foregroundStyle(stage.ok == true ? Color.green : Color.secondary)
                        Text(["process": "进程启动", "guest-boot": "系统引导", "display": "显示连接", "network": "网络就绪"][stage.name] ?? stage.name)
                        Text(stage.detail ?? "等待中").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            LabeledContent("显示客户端") {
                let text = SpiceClientStatus.columnText(node.spiceClient)
                Text(text).foregroundStyle(text == "已连接" ? Color.green : Color.secondary)
            }
            if let guidance = DisplaySessionGuidance.message(for: node) {
                Text(guidance).font(.caption).foregroundStyle(.secondary)
            }
            if let loginHelp = DisplaySessionGuidance.loginHelp(for: node) {
                DisclosureGroup("登录与锁屏说明") {
                    Text(loginHelp).font(.caption).foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            }
            if let sleepHelp = DisplaySessionGuidance.sleepHelp(for: node) {
                Text(sleepHelp).font(.caption).foregroundStyle(.orange)
                    .textSelection(.enabled)
            }
            LabeledContent("健康") {
                Text(model.state.healthyProfileIDs.contains(node.id)
                     ? "通过" : (model.state.pendingHealthProfileIDs.contains(node.id)
                                 ? "等待" : (node.running ? "待检查" : "—")))
            }
            if let resources = node.resources {
                if let memory = resources.memoryMB, let cpus = resources.cpus {
                    LabeledContent(node.running ? "本次配置" : "下次默认配置") {
                        Text("\(memory) MiB / \(cpus) 核（不是实际占用）")
                    }
                }
                if node.running {
                    LabeledContent("宿主资源采样") {
                        Text("CPU \(resources.cpuPercent.map { String(format: "%.1f%%", $0) } ?? "未知") · RSS \(resources.rssMB.map { String(format: "%.1f MiB", $0) } ?? "未知")")
                    }
                    if let acceleration = resources.acceleration {
                        LabeledContent("运行加速器") { Text(acceleration == "hvf" ? "HVF 硬件虚拟化" : acceleration) }
                    }
                    Text("CPU 是宿主 ps 采样口径，可超过 100%；RSS 是 QEMU 宿主驻留内存，不是来宾内存压力。读不到时显示未知。")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            if let pid = node.pid, node.running {
                LabeledContent("PID") { Text("\(pid)") }
            }
            let detailText = NodeOperationalState.detailText(for: node)
            if !detailText.isEmpty {
                Text(detailText).font(.caption).foregroundStyle(.secondary)
            }
            if node.boot?.isTimedOut == true {
                Text(node.boot?.diagnosis?.hint ?? "启动超时：查看日志定位卡住的阶段")
                    .font(.callout).foregroundStyle(.orange)
            }
            if let diagnosis = model.displayDiagnosis[node.id] {
                Text(diagnosis).font(.callout).foregroundStyle(.orange).textSelection(.enabled)
            }
            Text("显示窗口内 Shift+F12 可释放残留按键与鼠标；Shift+F11 切换工作区展开。")
                .font(.caption).foregroundStyle(.secondary)
            LabeledContent("日志") {
                if let logPath = node.logPath {
                    Text(logPath).textSelection(.enabled).font(.caption).lineLimit(1)
                        .truncationMode(.middle)
                } else {
                    Text("—").foregroundStyle(.secondary)
                }
            }

            Divider()
            HStack(spacing: 10) {
                if node.imported && !node.running {
                    Button("启动") { model.startProfile(node.id) }
                        .disabled(!model.state.canStartSelected || model.state.selectedProfileID != node.id)
                }
                if node.running {
                    Button(DisplaySessionGuidance.actionTitle(for: node)) { model.showDisplay(node.id) }
                        .disabled(model.state.phase.isBusy)
                    if DisplaySessionGuidance.canReconnect(node) {
                        Button("诊断显示") { model.diagnoseDisplay(node.id) }.disabled(model.state.phase.isBusy)
                        Button("重连显示") { model.showDisplay(node.id, reconnect: true) }
                            .help("画面卡住时只重建显示连接，不重启虚拟机、不改变剪贴板或文件共享")
                            .disabled(model.state.phase.isBusy)
                    }
                    Button("停止") { model.stopProfile(node.id) }
                        .disabled(!model.state.canStopSelected || model.state.selectedProfileID != node.id)
                    Button("重启") { model.selectNode(node.id); model.restartSelected() }
                        .disabled(!model.state.canStopSelected || model.state.selectedProfileID != node.id)
                }
                if node.imported && !node.running && !model.state.phase.isBusy {
                    Button("快照与备份…") { model.openRecovery(node.id) }
                    Button("重置此节点…", role: .destructive) { model.requestNodeReset(node.id) }
                    Button("删除镜像…", role: .destructive) { model.requestImageRemove(node.id) }
                }
                if !node.imported && !node.running && node.builtin != true {
                    Button("移除这条登记…", role: .destructive) { model.deregisterProfile(node.id) }
                }
            }
            if !node.imported {
                Text(node.builtin == true
                     ? "内置课程包：从“导入…”校验成套分发并导入，或用 x86 向导接入。"
                     : "未导入的登记：可移除，或重新导入镜像。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(.leading, 12)
    }

    private func errorBanner(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            Text(text).textSelection(.enabled).font(.callout)
            Spacer()
            Button("复制错误信息") { model.copyError() }
        }
        .padding(8)
        .background(Color.orange.opacity(0.12))
        .cornerRadius(6)
    }

    /// 内容包摘要：节点、资源需求、本机冲突预览与验收声明边界。
    /// 数据全部来自 `dist verify --json` 的只读报告；导入决定仍由 CLI 在安装时做出。
    @ViewBuilder
    private var packSummary: some View {
        if let pack = model.state.report?.pack {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    Image(systemName: "shippingbox.fill").foregroundStyle(.teal)
                    Text("\(pack.name)（\(pack.id) v\(pack.version)）").font(.headline)
                    Spacer()
                    if let satisfied = pack.runnerSatisfied, !satisfied {
                        Text("要求运行器 \(pack.requiresRunner)，当前不满足")
                            .font(.caption).foregroundStyle(.red)
                    }
                }
                ForEach(pack.nodes, id: \.profile) { node in
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(node.name ?? node.profile).font(.callout)
                        let resources = Self.packNodeResources(node)
                        if resources.isEmpty {
                            Text(node.profile).font(.caption).foregroundStyle(.secondary)
                        } else {
                            Text(resources).font(.caption).foregroundStyle(.secondary)
                        }
                        let packSha = model.state.report?.entries.first {
                            $0.file == "\(node.profile).yaml"
                        }?.expectedSha256
                        if let note = DistImportGate.conflictNote(local: node.local,
                                                                  profilePackSha256: packSha) {
                            let color: Color = note.contains("内置") ? .red
                                : (note.contains("一致") ? .secondary : .orange)
                            Text(note).font(.caption).foregroundStyle(color)
                        }
                        Spacer()
                    }
                }
                if let docs = pack.docs, !docs.isEmpty {
                    Text("说明文件：\(docs.joined(separator: "、"))（导入后随状态目录保存）")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let claims = pack.claims, !claims.isEmpty {
                    Text(pack.claimsNote ?? "包内验收声明仅供参考，导入不代表本机已验收。")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(8)
            .background(Color.teal.opacity(0.08))
            .cornerRadius(6)
        }
    }

    /// 成套分发校验结果：仅在已校验（有行）时出现；普通文件夹不占位。
    @ViewBuilder
    private var verifyTable: some View {
        if !model.verifyRows.isEmpty {
            VStack(spacing: 8) {
                packSummary
                Table(model.verifyRows) {
                    TableColumn("文件") { row in
                        Text(row.file).textSelection(.enabled)
                    }
                    TableColumn("大小") { row in
                        Text(row.size.map(Self.humanSize) ?? "—")
                    }
                    TableColumn("状态") { row in
                        Text(row.statusText)
                            .foregroundStyle(row.isOK ? Color.green : Color.red)
                    }
                    TableColumn("说明") { row in
                        Text(row.problem ?? "").textSelection(.enabled)
                    }
                }
                .frame(minHeight: 180)
            }
        }
    }

    /// CLI 输出默认收起：日常流程不需要读命令日志，出错时再展开复制。
    private var logPanel: some View {
        DisclosureGroup(isExpanded: $model.cliLogExpanded) {
            ScrollView {
                Text(model.log.isEmpty ? "（暂无输出）" : model.log)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(minHeight: 140)
            .padding(6)
            .background(Color(nsColor: .textBackgroundColor))
            .cornerRadius(4)
        } label: {
            HStack {
                Text("CLI 输出").font(.headline)
                Spacer()
                Button("复制错误信息") { model.copyError() }
            }
        }
    }

    static func humanSize(_ bytes: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        return formatter.string(fromByteCount: bytes)
    }

    static func packNodeResources(_ node: PackNode) -> String {
        var parts: [String] = []
        if let arch = node.architecture { parts.append(arch) }
        if let firmware = node.firmware { parts.append(firmware.uppercased()) }
        if let memory = node.memoryMb { parts.append("\(memory) MiB") }
        if let cpus = node.cpus { parts.append("\(cpus) vCPU") }
        return parts.joined(separator: " · ")
    }
}

/// 未知 x86_64 镜像的引导式接入界面。只展示 CLI 的白名单候选和证据，不提供任意 QEMU 参数输入。
private struct ImageOnboardingSheet: View {
    @ObservedObject var model: GuiModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("添加 x86_64 镜像").font(.title3).bold()
            Text("流程：只读识别 → 你确认候选 → 生成用户配置并导入派生基盘 → 启动探测。原始镜像不会被覆盖。")
                .font(.callout)
                .foregroundStyle(.secondary)

            LabeledContent("镜像") {
                Text(model.onboardingSourcePath.isEmpty ? "（未选择）" : model.onboardingSourcePath)
                    .lineLimit(1).truncationMode(.middle).textSelection(.enabled)
            }
            HStack {
                Button("重新选择…") { model.chooseX86Image() }
                    .disabled(model.state.phase.isBusy)
                Button("只读识别") { model.inspectOnboardingImage() }
                    .disabled(model.onboardingSourcePath.isEmpty || model.state.phase.isBusy)
                if model.state.phase.isBusy { ProgressView().controlSize(.small) }
            }

            // 模态向导遮住主窗口，导入控制必须在当前窗口内可达。
            if model.state.phase.isBusy {
                Text(model.state.progressText).font(.callout).textSelection(.enabled)
                if model.state.phase == .importing {
                    Button("取消当前导入") { model.cancelCurrentImport() }
                        .disabled(!model.importCanCancel)
                }
            }

            if let report = model.onboardingReport {
                GroupBox("候选硬件（不是已验证事实）") {
                    Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                        candidateRow("架构", report.candidate.architecture,
                                     report.confidence.architecture)
                        candidateRow("固件", report.candidate.firmware,
                                     report.confidence.firmware)
                        candidateRow("磁盘", diskText(report.candidate), report.confidence.disk)
                        candidateRow("网卡", report.candidate.networkAdapter,
                                     report.confidence.network)
                        GridRow {
                            Text("资源").foregroundStyle(.secondary)
                            Text("\(report.candidate.cpus) vCPU / \(report.candidate.memoryMB) MB")
                            Text(report.format ?? "未知格式").foregroundStyle(.secondary)
                        }
                    }
                    if !report.warnings.isEmpty {
                        Divider().padding(.vertical, 4)
                        ForEach(report.warnings, id: \.self) { warning in
                            Label(warning, systemImage: "exclamationmark.triangle")
                                .font(.caption).foregroundStyle(.orange)
                        }
                    }
                }
                .textSelection(.enabled)

                HStack {
                    Text("配置 ID")
                    TextField("例如 old-vulnbox", text: $model.onboardingProfileID)
                        .frame(width: 250)
                        .disabled(model.state.phase.isBusy)
                    Spacer()
                    Button(model.canRetryOnboarding ? "重试候选导入" : "创建候选并导入") { model.importOnboardingCandidate() }
                        .disabled(report.candidate.architecture != "x86_64"
                                  || !ImageOnboardingRules.validProfileID(model.onboardingProfileID)
                                  || model.state.phase.isBusy)
                }
                Text("此操作会在用户状态目录创建候选 profile 和只读基盘副本；不会覆盖已有同名配置。")
                    .font(.caption).foregroundStyle(.secondary)
            }

            if model.onboardingImportedProfileID != nil {
                HStack {
                    Button("启动探测") { model.probeOnboardingCandidate(matrix: false) }
                        .disabled(model.state.phase.isBusy)
                    Button("运行受控回退矩阵") { model.probeOnboardingCandidate(matrix: true) }
                        .disabled(model.state.phase.isBusy)
                    if let reportPath = model.onboardingMatrixReportPath {
                        if let screenshot = model.onboardingMatrixScreenshotPath {
                            Button("打开启动截图") {
                                NSWorkspace.shared.open(URL(fileURLWithPath: screenshot))
                            }
                        }
                        Button("查看报告与截图") {
                            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: reportPath)])
                        }
                        Button(model.onboardingMatrixReviewAttempt != nil ? "我已查看截图，保存候选…" : "确认保存命中参数") { model.showMatrixApplyConfirmation = true }
                            .disabled(model.state.phase.isBusy)
                    }
                }
                Text("矩阵仅尝试 BIOS/UEFI 与 SCSI、IDE、SATA、VirtIO 白名单组合；不会自动写回。人工确认保存时会先备份原 profile，且仍保持 candidate/未验收状态。")
                    .font(.caption).foregroundStyle(.secondary)
            }

            if !model.onboardingMessage.isEmpty {
                Text(model.onboardingMessage).font(.callout).textSelection(.enabled)
            }
            HStack {
                Spacer()
                Button("关闭") { dismiss() }
            }
        }
        .padding(20)
        .frame(minHeight: 430)
        .frame(width: 760)
        .confirmationDialog(
            "确认截图中系统正常引导，并保存候选硬件参数？",
            isPresented: $model.showMatrixApplyConfirmation,
            titleVisibility: .visible
        ) {
            Button("保存候选参数") { model.applyOnboardingMatrixCandidate() }
            Button("取消", role: .cancel) {}
        } message: {
            Text("UEFI Shell、PXE 或报错画面请取消。只保存白名单固件、磁盘总线和控制器；会复核报告、截图及镜像，备份原配置。保存后仍是未验收候选，不代表登录或服务可用。")
        }
    }

    @ViewBuilder
    private func candidateRow(_ label: String, _ value: String, _ confidence: InspectionConfidence) -> some View {
        GridRow {
            Text(label).foregroundStyle(.secondary)
            Text(value)
            Text("\(confidence.level)：\(confidence.reason)")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private func diskText(_ candidate: ImageCandidate) -> String {
        if let controller = candidate.diskController, !controller.isEmpty {
            return "\(candidate.diskBus) / \(controller)"
        }
        return candidate.diskBus
    }
}

@main
struct CTFLabGuiApp: App {
    @StateObject private var model = GuiModel()

    var body: some Scene {
        WindowGroup("CTFLab") {
            ContentView(model: model)
                .onAppear { model.refreshStatus() }
        }
    }
}

// 原生远程工作区：窗口只驱动固定客户端动作，不启动本机VM或改变远程生命周期。
@MainActor
private struct MacRemoteSheet: View {
    @ObservedObject var model: GuiModel
    var embedded = false
    @Environment(\.dismiss) private var dismiss
    private let names = ["prepare": "准备实验", "start": "启动", "stop": "正常停止", "reset": "整课重置", "recover": "恢复核验", "cancel": "取消后续操作"]
    private func confirm(_ message: String, action: () -> Void) {
        let alert = NSAlert(); alert.messageText = message
        alert.informativeText = "仅向当前已核验目标发送本次明确请求；结果未知时不自动重发。"
        alert.addButton(withTitle: "确认"); alert.addButton(withTitle: "取消")
        if alert.runModal() == .alertFirstButtonReturn { action() }
    }
    private func leaseEnabled(_ action: String) -> Bool {
        guard !model.remoteBusy, !model.remoteHasPending, let context = model.remoteContext, let ttl = Int(model.remoteTTL) else { return false }
        return (try? MacRemoteRules.lease(action, status: model.remoteLeases, context: context, instance: model.remoteInstance,
            selected: model.remoteLease, ttl: ttl, consent: model.remoteStopConsent)) != nil
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack { Text("远程实验").font(.title2).bold(); Spacer(); if !embedded { Button("关闭管理") { model.disconnectRemote(); dismiss() } } }
            Text("连接受限Linux运行器。关闭面板不会停止实验；需要管理员提供的私有连接配置。").font(.caption).foregroundStyle(.secondary)
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    targetSection
                    if let context = model.remoteContext {
                        if context.courses || context.audit {
                            Button(model.remoteAdminOpen ? "返回实例管理" : "课程与审计管理") {
                                model.remoteAdminOpen.toggle()
                                if model.remoteAdminOpen { model.loadRemoteAdminPending() }
                            }.disabled(model.remoteBusy)
                        }
                        if model.remoteAdminOpen { administrationSection(context) } else { instanceSection(context) }
                    }
                }.padding(4)
            }
            Text(model.remoteMessage).textSelection(.enabled).font(.callout)
            if model.remoteBusy { HStack { ProgressView().controlSize(.small); Text("请求处理中；未确认结果不会自动重发。").font(.caption) } }
        }.padding(embedded ? 0 : 20).frame(minWidth: embedded ? 0 : 920, minHeight: embedded ? 0 : 760)
        .onAppear { model.loadRemoteTargets() }
        .onDisappear { if !embedded { model.disconnectRemote() } }
        .onReceive(Timer.publish(every: 2, on: .main, in: .common).autoconnect()) { _ in
            if model.remoteTransferID != nil { model.refreshRemoteTransferHistory() }
        }
    }
    private var targetSection: some View {
        GroupBox("本机保存的目标") {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    TextField("目标名称", text: $model.remoteLabel).frame(width: 160)
                    TextField("私有配置文件", text: $model.remoteConfig)
                    Button("选择配置…") { model.chooseRemoteConfig() }
                    Button("保存目标") { model.saveRemoteTarget() }.disabled(model.remoteBusy || model.remoteLabel.isEmpty || model.remoteConfig.isEmpty)
                }.disabled(model.remoteBusy)
                Text("保存只登记本机配置/身份文件引用，不复制私钥，不连接服务器。").font(.caption).foregroundStyle(.secondary)
                DisclosureGroup("填写服务器信息生成配置") {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(["host", "port", "user", "server_uuid", "identity", "known_hosts"], id: \.self) { key in
                            HStack {
                                Text(["host": "服务器地址", "port": "SSH端口", "user": "SSH用户", "server_uuid": "服务器UUID", "identity": "身份文件", "known_hosts": "固定主机密钥文件"][key] ?? key).frame(width: 130, alignment: .leading)
                                TextField("", text: Binding(get: { model.remoteWizard[key] ?? "" }, set: { model.remoteWizard[key] = $0 }))
                                if ["identity", "known_hosts"].contains(key) { Button("选择…") { model.chooseRemoteIdentity(key) } }
                            }
                        }
                        Text("使用Mac系统SSH。主机密钥文件会复制到私有配置目录，原文件不变；私钥仅引用，不复制。").font(.caption)
                        Button("生成并保存配置（不连接）") { model.createRemoteTarget() }.disabled(model.remoteLabel.isEmpty)
                    }.padding(6).disabled(model.remoteBusy)
                }
                HStack {
                    Picker("保存目标", selection: $model.remoteSelected) {
                        Text("请选择").tag("")
                        ForEach(model.remoteTargets) { item in Text(item.label + " · " + String(item.server.prefix(8))).tag(item.id) }
                    }.disabled(model.remoteBusy || model.remoteContext != nil)
                    Button("刷新列表") { model.loadRemoteTargets() }.disabled(model.remoteBusy)
                    Button("明确连接") { model.connectRemote() }.disabled(model.remoteBusy || model.remoteSelected.isEmpty)
                    Button("断开管理") { model.disconnectRemote() }.disabled(model.remoteContext == nil && model.remoteConnectionID == nil)
                    if model.remoteConnectionID != nil { Button("取消本次连接") { model.cancelRemoteConnection() } }
                }
            }.padding(6)
        }
    }
    private func administrationSection(_ context: MacRemoteContext) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("管理操作只使用服务器登记课程与分配实例。配置不启动实验；审计观察不重放操作，原执行结果保留未知。").font(.caption)
            if context.courses {
                GroupBox("登记课程") {
                    VStack(alignment: .leading) {
                        Button("读取登记课程") { model.remoteAdministration("course-list") }
                        Picker("课程", selection: $model.remoteOffer) {
                            Text("请选择").tag("")
                            ForEach(Array(model.remoteOffers.enumerated()), id: \.offset) { _, offer in Text(offer["title"].text ?? "课程").tag(offer["offer_id"].text ?? "") }
                        }.onChange(of: model.remoteOffer) { model.remoteCoursePlan = .null; model.remoteCourseInstance = "" }
                        Picker("分配实例", selection: $model.remoteCourseInstance) {
                            Text("请选择").tag("")
                            ForEach(model.remoteOffers.first(where: { $0["offer_id"].text == model.remoteOffer })?["instances"].items.compactMap(\.text) ?? [], id: \.self) { Text($0).tag($0) }
                        }.onChange(of: model.remoteCourseInstance) { model.remoteCoursePlan = .null }
                        Button("预览课程配置") { model.remoteAdministration("course-preview", values: ["offer_id": .string(model.remoteOffer), "instance_uuid": .string(model.remoteCourseInstance)]) }
                        if let hash = model.remoteCoursePlan["mapping_sha256"].text {
                            Text("映射摘要：" + hash).font(.caption).textSelection(.enabled)
                            Button("确认配置（不启动）") { confirm("确认配置所选课程？") {
                                model.remoteAdministration("course-provision", values: ["offer_id": .string(model.remoteOffer), "instance_uuid": .string(model.remoteCourseInstance), "mapping_sha256": .string(hash)])
                            } }
                        }
                    }
                }
            }
            if context.audit {
                GroupBox("未决审计") {
                    VStack(alignment: .leading) {
                        Button("读取 / 刷新未决记录") { readAudit(after: 0) }
                        if let count = model.remoteAudit["pending_count"].integer { Text("未决 \(count) 项；独立快照不代表VM当前状态。") }
                        ForEach(Array(model.remoteAudit["pending"].items.enumerated()), id: \.offset) { _, row in
                            HStack {
                                Text((row["attempt_id"].text ?? "") + " · " + (row["observation"].text ?? "未知")).font(.caption)
                                Button("预览终态观察") { model.remoteAdministration("audit-settlement-preview", values: ["attempt_id": row["attempt_id"]]) }
                            }
                        }
                        if model.remoteAudit["more"].flag == true { Button("下一页") { readAudit(after: model.remoteAudit["next_intent"].integer ?? 0) } }
                        if let hash = model.remoteAuditPlan["review_sha256"].text {
                            Text("观察摘要：" + hash).font(.caption)
                            Button("追加观察，保留原结果未知") { confirm("确认追加此契约终态观察？") {
                                model.remoteAdministration("audit-settle", values: ["attempt_id": model.remoteAuditPlan["attempt_id"], "review_sha256": .string(hash)])
                            } }
                        }
                    }
                }
            }
            Button("读取本机未确认管理请求") { model.loadRemoteAdminPending() }
            ForEach(Array(model.remotePending.filter { ["course-provision", "audit-settle"].contains($0["payload"]["action"].text ?? "") }.enumerated()), id: \.offset) { _, item in
                HStack {
                    Text((item["payload"]["action"].text ?? "") + " · " + (item["phase"].text ?? "未知"))
                    Button("使用原请求重试") { confirm("确认以原请求标识重试管理操作？") { model.retryRemoteAdministration(item) } }
                }
            }
        }.disabled(model.remoteBusy)
    }
    private func readAudit(after: Int) {
        let audit = model.remoteAudit
        let checkpoint: MacRemoteJSON = audit["audit_head_seq"].integer == nil ? .null : .object(["seq": audit["audit_head_seq"], "sha256": audit["audit_head_sha256"]])
        model.remoteAdministration("audit-review", values: ["after": .number(Double(after)), "limit": .number(50), "checkpoint": checkpoint])
    }
    private func instanceSection(_ context: MacRemoteContext) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("服务器：\(context.saved.server)").font(.caption).textSelection(.enabled)
            HStack {
                Picker("分配实例", selection: Binding(get: { model.remoteInstance }, set: { model.selectRemoteInstance($0) })) {
                    Text("请选择").tag("")
                    ForEach(context.instances, id: \.self) { Text($0).tag($0) }
                }.disabled(model.remoteBusy)
                Button("读取 / 刷新当前状态") { model.refreshRemote() }.disabled(model.remoteBusy || model.remoteInstance.isEmpty)
            }
            if model.remoteView != .null {
                Text("当前状态：\(model.remoteView["status"]["state"].text ?? "未核验") · 代次 \(model.remoteView["generation"].integer ?? 0)")
                HStack {
                    ForEach(["prepare", "start", "stop", "reset", "recover", "cancel"], id: \.self) { operation in
                        Button(names[operation] ?? operation) {
                            confirm("确认向当前实例请求\(names[operation] ?? operation)？") { model.performRemote(operation) }
                        }.disabled(!model.remoteAllowed(operation))
                    }
                }
                if context.leases { leaseSection }
                GroupBox("节点显示") {
                    ForEach(Array(model.remoteView["topology"]["nodes"].items.enumerated()), id: \.offset) { _, node in
                        HStack {
                            Text(node["id"].text ?? "未核验节点")
                            Button("请求显示窗口") { model.requestRemoteDisplay(node["id"].text ?? "") }
                                .disabled(!model.remoteDisplayAllowed(node["id"].text ?? ""))
                        }
                    }
                    Text("需要当前活动租约；窗口请求返回不等于连接成功。剪贴板/文件传输不开启。").font(.caption)
                }
            }
            if !model.remotePending.isEmpty {
                GroupBox("本地未决请求（不自动发送）") {
                    ForEach(Array(model.remotePending.enumerated()), id: \.offset) { _, item in
                        HStack {
                            Text("原请求 \(String((item["id"].text ?? "").prefix(8))) · \(item["phase"].text ?? "未知")")
                            Button("明确使用原标识重试") {
                                confirm("使用原请求、原幂等键重试？") { model.retryRemote(item) }
                            }.disabled(model.remoteBusy || item["payload"]["instance_uuid"].text != model.remoteInstance)
                        }
                    }
                }
            }
            transferSection(context)
        }
    }
    private var leaseSection: some View {
        GroupBox("资源租约") {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Picker("当前租约", selection: $model.remoteLease) {
                        Text("请选择").tag("")
                        ForEach(Array(model.remoteLeases["leases"].items.enumerated()), id: \.offset) { _, row in
                            Text(String((row["lease_id"].text ?? "").prefix(8)) + " · " + (row["time_state"].text ?? "未知")).tag(row["lease_id"].text ?? "")
                        }
                    }
                    TextField("期限（秒）", text: $model.remoteTTL).frame(width: 120)
                    ForEach([("lease-acquire", "申请"), ("lease-renew", "续期"), ("lease-release", "释放")], id: \.0) { action, label in
                        Button(label) { confirm("按当前策略\(label)资源租约？释放需服务器确认全部停止，磁盘引用保留。") { model.changeRemoteLease(action) } }.disabled(!leaseEnabled(action))
                    }
                }.disabled(model.remoteBusy)
                if model.remoteLeases["expiry_action"].text == "request-stop" {
                    Toggle("我理解此租约允许到期处理时请求正常停止；本界面不会运行调度。", isOn: $model.remoteStopConsent)
                }
                Text("权限/状态读取失败时不开放新变更；未决请求需先核验或明确原标识重试。").font(.caption)
            }.padding(6)
        }
    }
    private func transferSection(_ context: MacRemoteContext) -> some View {
        DisclosureGroup("许可资产与封存证据") {
            VStack(alignment: .leading, spacing: 8) {
                Button("读取本机传输记录") { model.refreshRemoteTransferHistory() }
                if context.assets {
                    HStack {
                        TextField("许可索引来源标识", text: $model.remoteAssetSource)
                        TextField("原始资产文件", text: $model.remoteAssetFile)
                        Button("选择资产…") { model.chooseRemoteAsset() }
                        Button("明确上传") { confirm("上传当前原始资产到已连接运行器？服务器仍需当前许可。") { model.uploadRemoteAsset() } }
                            .disabled(model.remoteBusy || model.remoteAssetFile.isEmpty || model.remoteAssetSource.isEmpty)
                    }.disabled(model.remoteBusy)
                }
                if let active = model.remoteTransferID {
                    Button("暂停本次传输") { model.remoteTransferAction(active.kind == "asset" ? "asset-cancel" : "evidence-cancel", kind: active.kind, identity: active.id) }
                }
                ForEach(Array(model.remoteUploads.enumerated()), id: \.offset) { _, row in
                    HStack {
                        Text("上传 \(String((row["upload_id"].text ?? "").prefix(8))) · \(row["received"].integer ?? 0)/\(row["size"].integer ?? 0) · \(row["phase"].text ?? "未知")")
                        Button("明确续传") { model.remoteTransferAction("asset-resume", kind: "asset", identity: row["upload_id"].text ?? "") }.disabled(model.remoteBusy || !context.assets || row["phase"].text == "verified")
                        Button("当前远端核对") { model.remoteTransferAction("asset-probe", kind: "asset", identity: row["upload_id"].text ?? "") }.disabled(model.remoteBusy || !context.assets)
                    }
                }
                if context.evidence {
                    Button("明确列出当前实例封存证据") { model.listRemoteEvidence() }.disabled(model.remoteBusy || model.remoteInstance.isEmpty)
                    ForEach(Array(model.remoteExports.enumerated()), id: \.offset) { _, export in
                        ForEach(Array(export["files"].items.enumerated()), id: \.offset) { _, file in
                            HStack {
                                Text(file["name"].text ?? "未知文件")
                                Button("下载私有副本") { confirm("下载此封存文件？原件不改，不自动打开或解包。") { model.downloadRemoteEvidence(export: export, file: file) } }.disabled(model.remoteBusy)
                            }
                        }
                    }
                }
                ForEach(Array(model.remoteDownloads.filter { $0["instance_uuid"].text == model.remoteInstance }.enumerated()), id: \.offset) { _, row in
                    HStack {
                        Text("下载 \(row["file"].text ?? "") · \(row["received"].integer ?? 0)/\(row["size"].integer ?? 0) · \(row["phase"].text ?? "未知")")
                        Button("明确续传") { model.remoteTransferAction("evidence-resume", kind: "evidence", identity: row["download_id"].text ?? "") }.disabled(model.remoteBusy || !context.evidence || row["phase"].text == "verified")
                    }
                    if let path = row["local_path"].text { Text("私有副本：" + path).font(.caption).textSelection(.enabled) }
                }
                Text("传输verified为历史记录，不代表当前远端/本机文件已重新核验。关闭页面不停止实验，不自动续传、打开或执行内容。").font(.caption).foregroundStyle(.secondary)
            }.padding(8)
        }
    }
}

private final class MacScenarioPresentation: ObservableObject {
    @Published var setupOpen = false
}

private struct MacScenarioSheet: View {
    @ObservedObject var model: GuiModel
    var embedded = false
    var configurationOnly = false
    @StateObject private var presentation = MacScenarioPresentation()
    @Environment(\.dismiss) private var dismiss
    private func confirm(_ action: String, _ title: String) {
        let alert = NSAlert(); alert.messageText = title
        alert.informativeText = "仅操作当前实例。旧资产保留，正常停止超时不强杀；结果未知时先读取状态，不自动重发。"
        alert.addButton(withTitle: "确认"); alert.addButton(withTitle: "取消")
        if alert.runModal() == .alertFirstButtonReturn { model.sceneRequest(action) }
    }
    private func confirmCustom(_ title: String, action: () -> Void) {
        let alert = NSAlert(); alert.messageText = title
        alert.informativeText = "只处理当前通用实例的明确请求；结果未知时保留现场，不自动重发。"
        alert.addButton(withTitle: "确认"); alert.addButton(withTitle: "取消")
        if alert.runModal() == .alertFirstButtonReturn { action() }
    }
    private var configurationControls: some View {
            HStack {
                Button("选择私有运行时配置…") { model.chooseSceneFile("profile") }
                Text(model.sceneRuntimeProfile.isEmpty ? "未选择" : URL(fileURLWithPath: model.sceneRuntimeProfile).lastPathComponent)
                Button("建立通用实例") { confirm("configure", "按已预览清单建立新通用实例？") }
                    .disabled(model.scenePlan == nil || !MacRemoteRules.digest(model.sceneManifestSHA) || model.sceneRuntimeProfile.isEmpty)
                Button("导出校验清单") { model.sceneExport() }.disabled(model.scenePlan == nil)
                Button("编辑拓扑草稿") { model.sceneLoadDraft(); model.sceneGraphOpen = model.sceneDraft != .null }
                    .disabled(model.sceneLocalView == nil || model.sceneWorkspaceBusy)
            }
    }
    private var genericControls: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let view = model.sceneLocalView {
                Text("当前代次 \(view["generation"].integer ?? 0) · 操作记录 \(localLabel(view["status"]["state"].text))")
                if !MacObservationWindow.fresh(view) { Text(view["freshness"]["reason"].text == "changed-during-sampling" ? "采样期间实验已变化，请重新读取；设计信息保留，运行状态待核验。" : "状态已过期或采样不完整，请重新读取；设计信息保留，运行状态待核验。").font(.caption).foregroundStyle(.orange) }
                MacRuntimeTopology(view: view)
                HStack {
                    Button("读取外部攻击机状态") { model.sceneGenericCall(["action": .string("external-attach-status")]) }
                        .disabled(model.sceneWorkspaceBusy)
                }
                MacExternalAttachCard(model: model, summary: (try? MacExternalAttachSummary(model.sceneExternalAttach ?? .null))
                    ?? (try? MacExternalAttachSummary(view["external_attach"])) ?? nil)
                DisclosureGroup("持续监督历史（非当前运行状态）") {
                    Text("读取已保存采样，不启动监督或重放操作；进程现在的状态以重新读取为准。").font(.caption)
                    if view["supervision_history"]["unavailable"].flag == true {
                        Text("历史记录暂不可核验，现场已保留。").foregroundStyle(.orange)
                    }
                    ForEach(Array(view["supervision_history"]["watches"].items.suffix(16).reversed().enumerated()), id: \.offset) { _, item in
                        Text("代次 \(item["generation"].integer ?? 0) · \(item["ticks"].integer ?? 0)次 · \(item["sampled_at"].text ?? "尚无采样") · " + (item["coherent"].flag == true && item["complete"].flag == true ? "末次完整一致（历史）" : "末次待核验（历史）"))
                            .font(.caption).textSelection(.enabled)
                    }
                }
                if view["runtime"]["dependencies"]["tls_control"].flag == false { Text("当前运行时缺少认证控制依赖；设计和准备可用，启动须使用完整通用运行时。").font(.caption).foregroundStyle(.orange) }
                HStack {
                    Button("查询原请求") { model.sceneQueryOriginal() }.disabled(!model.sceneCanQueryOriginal)
                    Button("取消后续操作") { confirm("cancel", "取消当前操作尚未执行的后续步骤？") }.disabled(!model.sceneGenericAllowed("cancel"))
                    if MacObservationWindow.fresh(view), view["dispatch"]["resume_allowed"].flag == true {
                        Button("继续派发原请求") { confirmCustom("明确继续尚未领取的原请求？") { model.sceneRecoverPreparation("resume-dispatch") } }
                    }
                    if MacObservationWindow.fresh(view), view["preparation"]["restart_allowed"].flag == true {
                        Button("保留现场，重新准备") { confirmCustom("保留旧半成品，以全新操作重新准备？") { model.sceneRecoverPreparation("restart-preparation") } }
                    }
                }
                DisclosureGroup("已保存操作（历史）") {
                    Text("从原操作账本只读读取；不显示请求参数或幂等键；历史记录不代表当前运行状态，也不会自动重发或恢复。").font(.caption)
                    HStack {
                        Button("读取历史") { model.sceneHistoryLoad() }.disabled(model.sceneWorkspaceBusy)
                        Button("更早一页") { model.sceneHistoryNextPage() }.disabled(model.sceneWorkspaceBusy || !model.sceneHistoryHasNext)
                    }
                    ForEach(Array(model.sceneHistory.enumerated()), id: \.offset) { _, row in
                        HStack {
                            Text("\(row.operation) · \(row.status) · 代次 \(row.expectedGeneration.map(String.init) ?? "—")" + (row.cancelRequested ? " · 已记录取消意图" : ""))
                                .font(.caption).textSelection(.enabled)
                            Spacer()
                            Button("原响应") { model.sceneSavedRecord(row.operationID) }.disabled(model.sceneWorkspaceBusy)
                        }
                    }
                    if let record = model.sceneHistoryRecord {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("原响应（历史）：\(record.record.operation) · " + (record.response["result"].text ?? "无已保存响应；状态以重新读取为准。"))
                                .font(.caption).textSelection(.enabled)
                            if let code = record.response["error"]["code"].text {
                                Text("公开错误：\(code) · \(record.response["error"]["message"].text ?? "")").font(.caption).foregroundStyle(.orange)
                            }
                        }
                    }
                }
                DisclosureGroup("实验事件（严格游标）") {
                    Text("按序号连续性只读追加；出现缺口、实例不符或游标过期时清空本地时间线，并要求重新读取状态，不自动重发操作。").font(.caption)
                    Button("读取新事件") { model.sceneEventsRefresh() }.disabled(model.sceneWorkspaceBusy)
                    if !model.sceneEventNotice.isEmpty { Text(model.sceneEventNotice).font(.caption).foregroundStyle(.orange) }
                    ForEach(Array(model.sceneEvents.reversed().enumerated()), id: \.offset) { _, event in
                        Text("#\(event["sequence"].integer ?? 0) · \(event["stage"].text ?? "?") · \(localLabel(event["state"].text)) · 代次\(event["generation"].integer ?? 0) · \(event["timestamp"].text ?? "")")
                            .font(.caption).textSelection(.enabled)
                    }
                }
                ForEach(model.sceneNodeIDs, id: \.self) { node in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(node + " · " + localLabel(MacObservationWindow.fresh(view) ? view["observations"][node]["state"].text : "unknown")).bold()
                        HStack {
                            Button("打开 / 重连显示") { model.sceneDisplay(node) }.disabled(!MacObservationWindow.fresh(view) || view["observations"][node]["state"].text != "process-running" || view["runtime"]["dependencies"]["display"].flag == false)
                            Button("恢复退出观测") { confirmCustom("核验当前进程并补建退出观测？") { model.sceneRearm(node) } }
                                .disabled(!MacObservationWindow.fresh(view) || view["observations"][node]["state"].text != "process-running" || view["supervision"][node]["observer"].text == "running")
                        }
                        if view["supervision"][node]["logs"]["kind"].text == "posix-fifo-v1" {
                            Text("日志接收：" + (view["supervision"][node]["logs"]["receiver"].text == "lock-held" ? "接收锁已占用" : "尚未确认接收") + "；历史可能有缺口。").font(.caption)
                            Button("重接日志接收器") { confirmCustom("保留旧片段，重接当前日志通道？不重启或停止实验。") { model.sceneRearmLog(node) } }
                                .disabled(!MacLogRecovery.allowed(view,node:node,busy:model.sceneWorkspaceBusy))
                        }
                        if view["guest_agents"][node] != .null {
                            HStack {
                                Button("配置实验网络") { confirmCustom("按固定策略配置来宾实验网络？") { model.sceneGuest(node, "network-apply") } }
                                Button("启动DNS与时间") { confirmCustom("启动本代次DNS与时间服务？") { model.sceneGuest(node, "services-start") } }
                                Button("停止基础服务") { confirmCustom("保存并停止本代次基础服务？") { model.sceneGuest(node, "services-stop") } }
                                Button("读取来宾状态") { model.sceneGuest(node, "status") }
                            }.disabled(!model.sceneGenericAllowed("guest"))
                            if view["guest_agents"][node]["containers"].flag == true {
                                HStack {
                                    Button("准备容器") { confirmCustom("准备本代次容器？") { model.sceneGuest(node, "containers-prepare") } }
                                    Button("启动容器") { confirmCustom("启动本代次容器？") { model.sceneGuest(node, "containers-start") } }
                                    Button("保存并停止容器") { confirmCustom("保存并停止本代次容器？") { model.sceneGuest(node, "containers-stop") } }
                                }.disabled(!model.sceneGenericAllowed("guest"))
                                MacGuestRecoveryView(model: model,node: node)
                                    .id(model.sceneInstance + ":" + String(view["generation"].integer ?? 0) + ":" + node)
                            }
                            if view["guest_agents"][node]["analysis"].flag == true {
                                Button("离线分析并封存") { confirmCustom("使用本代次固定分析器处理证据？") { model.sceneGuest(node, "analysis-run") } }.disabled(!model.sceneGenericAllowed("guest"))
                            }
                        }
                    }.padding(8).background(Color.secondary.opacity(0.06)).cornerRadius(6)
                }
            }
        }
    }
    private func localLabel(_ value: String?) -> String {
        ["unknown":"尚未核验", "prepared":"已准备", "stopped":"已停止", "process-running":"进程运行，服务待验", "recovery-required":"需要恢复核验", "preparing":"正在准备", "starting":"正在启动", "stopping":"正在停止", "resetting":"正在创建新代次", "recovering":"正在核验", "failed":"未完成"][value ?? "unknown"] ?? "待核对"
    }
    private func label(_ value: String?) -> String {
        switch value { case "stopped-observed": return "已观测停止"; case "running-observed": return "仍有进程运行"
        case "recovery-required": return "需要恢复核验"; case "committed-observed": return "已选定代次"
        case "old-active-preserved": return "旧代次已保留"; default: return "待核对" }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack { Text(configurationOnly ? "场景设计与配置" : "实验运行").font(.title2).bold(); Spacer(); if !embedded { Button("关闭面板") { dismiss() } } }
            Text("选择原固定三节点或新版通用场景。通用模式支持ARM原生与明确确认的x86仿真；设计、进程、服务和课程验收分别记录。")
                .font(.caption).foregroundStyle(.secondary)
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Picker("运行链", selection: $model.sceneGeneric) { Text("原固定三节点").tag(false); Text("新版通用v2").tag(true) }.pickerStyle(.segmented)
                    HStack { TextField("实例UUID", text: $model.sceneInstance)
                        Button("新实例") { model.sceneInstance = UUID().uuidString.lowercased(); model.sceneSnapshot = nil }
                        Button("列出已有场景") { model.sceneRequest("status", list: true) }
                        Button("读取此实例状态") { model.sceneRequest("status") } }
                    if !configurationOnly {
                        TimelineView(.periodic(from: .now, by: 1)) { _ in
                        HStack(spacing: 20) {
                            Label(model.sceneGeneric ? "通用实验" : "Wintermute", systemImage: "cube")
                            if let view = model.sceneLocalView {
                                Text("代次 \(view["generation"].integer ?? 0)").bold()
                                Text(MacObservationWindow.fresh(view) ? "当前采样 · " + localLabel(view["status"]["state"].text) : "状态待核验 · 请重新读取").foregroundStyle(.secondary)
                            } else { Text("尚未读取此实例状态").foregroundStyle(.secondary) }
                        }.padding(18).frame(maxWidth: .infinity, alignment: .leading).background(.blue.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
                        }
                    }
                    if !configurationOnly {
                    HStack {
                        Button("准备独立副本") { confirm("prepare", "准备当前实例的独立副本？") }.disabled(model.sceneGeneric ? !model.sceneGenericAllowed("prepare") : !model.sceneHasCurrent || model.scenePlan == nil)
                        Button("启动场景") { confirm("start", "启动当前场景？") }.disabled(model.sceneGeneric ? !model.sceneGenericAllowed("start") : !model.sceneHasCurrent || !model.sceneEmulation)
                        Button("正常停止") { confirm("stop", "核验身份并请求正常停止当前场景？") }.disabled(model.sceneGeneric ? !model.sceneGenericAllowed("stop") : !model.sceneHasCurrent)
                        Button(model.sceneGeneric ? "恢复核验" : "收口中断重置") { confirm("recover", "只读核验当前实例并收口可确认的中断？") }.disabled(model.sceneGeneric ? !model.sceneGenericAllowed("recover") : !model.sceneHasCurrent)
                    }
                    HStack { if !model.sceneGeneric { TextField("新代次", text: $model.sceneNewGeneration).frame(width: 90) }
                        Button("整场景重置到新代次") { confirm("reset", "保留旧代次并创建新代次？") }.disabled(model.sceneGeneric ? !model.sceneGenericAllowed("reset") : !model.sceneHasCurrent) }
                    }
                    DisclosureGroup(configurationOnly ? "清单、资产与运行配置" : "新建实验 / 调整准备配置", isExpanded: Binding(get: { configurationOnly || presentation.setupOpen }, set: { presentation.setupOpen = $0 })) {
                        if model.sceneGeneric { configurationControls }
                    HStack { Button("选择场景清单…") { model.chooseSceneFile("manifest") }
                        Text(model.sceneManifest.isEmpty ? "未选择" : URL(fileURLWithPath: model.sceneManifest).lastPathComponent)
                        Button("查看设计") { model.sceneRequest("preview") }.disabled(model.sceneManifest.isEmpty) }
                    ForEach(model.sceneNodeIDs, id: \.self) { node in
                        HStack { Text(node).bold(); Text("\(model.scenePlan?["manifest"]["nodes"][node]["cpus"].integer ?? 0) vCPU · \(model.scenePlan?["manifest"]["nodes"][node]["memory_mb"].integer ?? 0) MiB").foregroundStyle(.secondary) }
                    }
                    ForEach(model.sceneNetworkIDs, id: \.self) { network in
                        VStack(alignment: .leading) {
                            let cidr = model.scenePlan?["manifest"]["networks"][network]["cidr"].text ?? ""
                            Text(network + " · " + cidr).bold()
                            Text(model.sceneMembers(network))
                            Text("设计连接与地址，不代表实际互通；无物理局域网出口。").font(.caption).foregroundStyle(.secondary)
                        }.padding(10).background(Color.blue.opacity(0.06)).cornerRadius(6)
                    }
                    ForEach(model.sceneAssetIDs, id: \.self) { id in
                        HStack { Text("基盘 · " + id); Button(model.sceneAssets[id].map { URL(fileURLWithPath: $0).lastPathComponent } ?? "选择只读基盘…") { model.chooseSceneFile("asset", id: id) } }
                    }
                    ForEach(model.sceneUEFINodes, id: \.self) { node in
                        HStack { Text(node + " · UEFI"); ForEach(model.sceneGeneric ? [1] : [0, 1], id: \.self) { role in
                            Button((model.sceneFirmware[node]?[role]).flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: $0).lastPathComponent } ?? (role == 0 ? "选择code固件…" : "选择vars模板…")) { model.chooseSceneFile("firmware", id: node, role: role) }
                        } }
                    }
                    Toggle("明确允许本场景中的x86软件仿真（含x86节点时必选，ARM仍用原生加速）", isOn: $model.sceneEmulation)
                    }
                    if model.sceneGeneric && !configurationOnly {
                        DisclosureGroup("节点、外部接入与操作记录") { TimelineView(.periodic(from: .now, by: 1)) { _ in genericControls } }
                    }
                    ForEach(Array((model.sceneReply?["reports"].items ?? []).enumerated()), id: \.offset) { _, report in
                        VStack(alignment: .leading) {
                            HStack { Text(report["instance_uuid"].text ?? "未知实例").font(.caption).textSelection(.enabled)
                                Button("选择此实例") { model.sceneInstance = report["instance_uuid"].text ?? ""; model.sceneSnapshot = nil } }
                            Text("代次 \(report["active"]["generation"].integer.map(String.init) ?? "未选定") · 节点：\(label(report["nodes"]["state"].text)) · 网络服务：\(label(report["services"]["state"].text))")
                        }.padding(8).background(Color.secondary.opacity(0.08)).cornerRadius(6)
                    }
                }.disabled(model.sceneWorkspaceBusy)
            }
            if model.sceneWorkspaceBusy { ProgressView("正在处理本次请求；关闭面板不自动停止场景。") }
            Text(model.sceneMessage).font(.callout).textSelection(.enabled)
        }.padding(embedded ? 0 : 20).frame(minWidth: embedded ? 0 : 820, minHeight: embedded ? 0 : 650)
            .sheet(isPresented: $model.sceneGraphOpen) { MacGraphSheet(model: model) }
            .onChange(of: model.sceneInstance) { _, _ in model.sceneSnapshot = nil; model.sceneLocalView = nil }
            .onChange(of: model.sceneGeneric) { _, _ in model.sceneSnapshot = nil; model.sceneLocalView = nil; model.scenePlan = nil; model.sceneSourceManifest = nil; model.sceneManifestSHA = ""; model.sceneInstance = UUID().uuidString.lowercased() }
            .onChange(of: model.sceneInstance) { _, _ in model.sceneResetReadonly() }
    }
}

/// 设计画布与运行状态分离，连接操作只更新值副本，后端校验后才开放导出。
private struct MacGraphFramesKey: PreferenceKey {
    static let defaultValue: [String:CGRect] = [:]
    static func reduce(value: inout [String:CGRect],nextValue: () -> [String:CGRect]) { value.merge(nextValue()) { _,new in new } }
}
private final class MacGraphCanvasState: ObservableObject {
    @Published var frames: [String:CGRect] = [:]
    @Published var positions: [String:MacRemoteJSON] = [:]
    @Published var origins: [String:MacRemoteJSON] = [:]
}
private struct MacGraphSheet: View {
    @ObservedObject var model: GuiModel
    var embedded = false
    @Environment(\.dismiss) private var dismiss
    @StateObject private var layoutState = MacGraphCanvasState()
    private var positions: [String:MacRemoteJSON] { get { layoutState.positions } nonmutating set { layoutState.positions = newValue } }
    private var origins: [String:MacRemoteJSON] { get { layoutState.origins } nonmutating set { layoutState.origins = newValue } }
    @GestureState private var isDragging = false
    private var draft: MacRemoteJSON { model.sceneDraft }
    private func location(_ key: String, _ x: CGFloat, _ y: CGFloat) -> CGPoint {
        let value = positions[key]; return CGPoint(x: value?["x"].integer.map { CGFloat($0) } ?? x, y: value?["y"].integer.map { CGFloat($0) } ?? y)
    }
    private func nodePoint(_ node: String) -> CGPoint { location("node:" + node, 18, y(node)) }
    private func networkPoint(_ network: String) -> CGPoint { location("network:" + network, 590, 16 + CGFloat((networks.firstIndex(of: network) ?? 0) * 112)) }
    private func allPositions() -> [String:MacRemoteJSON] {
        var result: [String:MacRemoteJSON] = [:]
        for node in nodes { let p = nodePoint(node); result["node:" + node] = try? MacGraphLayout.point(p.x,p.y) }
        for network in networks { let p = networkPoint(network); result["network:" + network] = try? MacGraphLayout.point(p.x,p.y) }
        return result
    }
    private var boardWidth: CGFloat { max(900, max(nodes.map { nodePoint($0).x + 390 }.max() ?? 0, networks.map { networkPoint($0).x + 300 }.max() ?? 0)) }
    private func move(_ key: String, point: CGPoint, dx: CGFloat, dy: CGFloat) {
        if let value = try? MacGraphLayout.point(point.x + dx,point.y + dy) { positions[key] = value }
    }
    private func grip(_ key: String, _ label: String, point: CGPoint) -> some View {
        Text("⠿ " + label).bold().padding(4).contentShape(Rectangle()).accessibilityLabel("移动" + label)
            .background(GeometryReader { proxy in Color.clear.preference(key:MacGraphFramesKey.self,value:[("grip:" + key):proxy.frame(in:.named("mac-graph-board"))]) })
            .gesture(DragGesture(minimumDistance: 3,coordinateSpace: .named("mac-graph-board")).updating($isDragging) { _, active, _ in active = true }.onChanged { event in
                if origins[key] == nil { origins[key] = try? MacGraphLayout.point(point.x,point.y) }
                let origin = origins[key]; move(key,point: CGPoint(x: origin?["x"].integer.map { CGFloat($0) } ?? point.x, y: origin?["y"].integer.map { CGFloat($0) } ?? point.y), dx: event.translation.width, dy: event.translation.height)
            }.onEnded { _ in origins.removeValue(forKey: key) })
            .contextMenu { Button("向左移动") { move(key,point: point,dx: -10,dy: 0) }; Button("向右移动") { move(key,point: point,dx: 10,dy: 0) }; Button("向上移动") { move(key,point: point,dx: 0,dy: -10) }; Button("向下移动") { move(key,point: point,dx: 0,dy: 10) } }
    }
    private func saveLayout() {
        let original = draft, panel = NSSavePanel(); panel.nameFieldStringValue = "ctflab-graph-layout.json"
        guard panel.runModal() == .OK, let url = panel.url, draft == original else { return }
        do { let value = try MacGraphLayout.export(draft,positions: allPositions()); try Data(value.encoded().utf8).write(to: url,options: .withoutOverwriting); model.sceneMessage = "布局已导出，实验配置保持原样。" }
        catch { model.sceneMessage = "布局未导出，已有文件保留。" }
    }
    private func loadLayout() {
        let original = draft, panel = NSOpenPanel(); panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url, draft == original else { return }
        do { let file = try FileHandle(forReadingFrom: url); defer { try? file.close() }; let data = try file.read(upToCount: 65537) ?? Data()
            guard data.count <= 65536, let text = String(data: data,encoding: .utf8) else { throw MacRemoteError.invalid }
            let next = try MacGraphLayout.load(draft,text: text); origins = [:]; positions = next; model.sceneMessage = "布局已载入，实验配置保持原样。"
        } catch { model.sceneMessage = "布局未载入：核对草稿标识、元素及坐标；当前布局保留。" }
    }
    private var nodes: [String] { MacGraphDraft.keys(draft["nodes"]) }
    private var networks: [String] { MacGraphDraft.keys(draft["networks"]) }
    private func height(_ node: String) -> CGFloat { layoutState.frames["card:" + node]?.height ?? CGFloat(178 + draft["nodes"][node]["interfaces"].items.count * 42) }
    private func y(_ node: String) -> CGFloat { 16 + nodes.prefix(while: { $0 != node }).reduce(CGFloat(0)) { $0 + height($1) + 18 } }
    private var boardHeight: CGFloat { max(200, max(nodes.map { nodePoint($0).y + height($0) + 18 }.max() ?? 0, networks.map { networkPoint($0).y + 112 }.max() ?? 0)) }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack { Text("拓扑草稿").font(.title2).bold(); Spacer(); if !embedded { Button("关闭草稿") { dismiss() } } }
            Group {
            Text("设计连线不代表实测可达。编辑不改变当前清单、运行代次或虚拟机；完整后端校验通过后可导出，供新实例使用。").font(.caption)
            HStack { Button("撤销配置") { model.sceneMoveDraft(false) }.disabled(model.sceneDraftHistory?.canUndo != true); Button("重做配置") { model.sceneMoveDraft(true) }.disabled(model.sceneDraftHistory?.canRedo != true); Text("保留最近20步配置编辑；布局单独导出").font(.caption) }
            HStack { Button("自动排列") { positions = [:]; origins = [:] }; Button("导出布局") { saveLayout() }; Button("载入布局") { loadLayout() }; Text("拖动标题，或在标题菜单选择移动方向").font(.caption) }
            ScrollView([.horizontal, .vertical]) {
                ZStack(alignment: .topLeading) {
                    Canvas { context, _ in
                        for node in nodes {
                            for nic in draft["nodes"][node]["interfaces"].items {
                                guard let target = nic["network"].text, networks.contains(target) else { continue }
                                guard let source = layoutState.frames["nic:" + node + "/" + (nic["id"].text ?? "")], let destination = layoutState.frames["grip:network:" + target] else { continue }
                                let start = CGPoint(x:source.maxX,y:source.midY), end = CGPoint(x:destination.minX,y:destination.midY)
                                var path = Path(); path.move(to: start); path.addCurve(to: end, control1: CGPoint(x: start.x + 62, y: start.y), control2: CGPoint(x: end.x - 60, y: end.y))
                                context.stroke(path, with: .color(.blue.opacity(0.65)), lineWidth: 2)
                            }
                        }
                    }.frame(width: boardWidth, height: boardHeight).accessibilityLabel("草稿中的设计连接，不代表实际网络")
                    ForEach(nodes, id: \.self) { node in nodeCard(node).frame(width:360).fixedSize(horizontal:false,vertical:true)
                        .background(GeometryReader { proxy in Color.clear.preference(key:MacGraphFramesKey.self,value:[("card:" + node):proxy.frame(in:.named("mac-graph-board"))]) })
                        .offset(x:nodePoint(node).x,y:nodePoint(node).y) }
                    ForEach(Array(networks.enumerated()), id: \.element) { index, network in
                        VStack(alignment: .leading) {
                            grip("network:" + network,network,point: networkPoint(network)); Text(draft["networks"][network]["cidr"].text ?? "")
                            Text("无物理出口 · 设计网段").font(.caption)
                            Button("移除空闲草稿网段") { model.sceneEditDraft { try MacGraphDraft.removeNetwork($0, name: network) } }
                                .disabled(nodes.contains { node in draft["nodes"][node]["interfaces"].items.contains { $0["network"].text == network } })
                        }.padding(10).frame(width: 270, height: 90, alignment: .leading).background(.green.opacity(0.08)).cornerRadius(8).offset(x: networkPoint(network).x, y: networkPoint(network).y)
                    }
                }.frame(width: boardWidth, height: boardHeight).coordinateSpace(name: "mac-graph-board")
                    .onPreferenceChange(MacGraphFramesKey.self) { frames in if frames.count <= 512 && layoutState.frames != frames { layoutState.frames = frames } }
            }.background(.gray.opacity(0.03))
            HStack {
                TextField("新节点标识", text: $model.sceneDraftNodeName).frame(width: 150)
                Picker("已有资产", selection: $model.sceneDraftAsset) { Text("请选择").tag(""); ForEach(MacGraphDraft.keys(draft["assets"]), id: \.self) { Text($0).tag($0) } }.frame(width: 240)
                Button("添加草稿节点") { model.sceneEditDraft { try MacGraphDraft.addNode($0, name: model.sceneDraftNodeName, asset: model.sceneDraftAsset) } }.disabled(model.sceneDraftNodeName.isEmpty || model.sceneDraftAsset.isEmpty)
            }
            HStack {
                TextField("新网段标识", text: $model.sceneDraftNetworkName).frame(width: 150); TextField("私有网段，如10.90.0.0/24", text: $model.sceneDraftCIDR).frame(width: 240)
                Button("添加草稿网段") { model.sceneEditDraft { try MacGraphDraft.addNetwork($0, name: model.sceneDraftNetworkName, cidr: model.sceneDraftCIDR) } }.disabled(model.sceneDraftNetworkName.isEmpty || model.sceneDraftCIDR.isEmpty)
            }
            HStack {
                Button("重新载入当前清单") { model.sceneLoadDraft() }
                Button("后端校验与差异") { model.sceneValidateDraft() }
                Button("导出已校验草稿") { model.sceneExportDraft() }.disabled(model.sceneDraftDiff["manifest"] != draft)
                Text("差异 \(model.sceneDraftDiff["changes"].items.count) 项").font(.caption)
            }
            ScrollView { VStack(alignment: .leading) {
                ForEach(Array(model.sceneDraftDiff["changes"].items.enumerated()), id: \.offset) { _, change in
                    Text((change["path"].text ?? "") + ": " + ((try? change["before"].encoded()) ?? "") + " → " + ((try? change["after"].encoded()) ?? "")).font(.caption).textSelection(.enabled)
                }
            } }.frame(maxHeight: 90)
            Text(model.sceneMessage).font(.caption).foregroundStyle(.secondary)
            }.disabled(model.sceneWorkspaceBusy || model.sceneDraftContext != model.sceneInstance || !model.sceneGeneric)
        }.padding(18).frame(minWidth: embedded ? 0 : 950, minHeight: embedded ? 0 : 680)
            .onChange(of: isDragging) { _, active in if !active { for (key,value) in origins { positions[key] = value }; origins = [:] } }
            .onChange(of: draft["scenario_id"]) { _, _ in positions = [:]; origins = [:] }
            .onChange(of: model.sceneInstance) { _, _ in positions = [:]; origins = [:] }
            .onChange(of: MacGraphLayout.keys(draft)) { _, keys in positions = positions.filter { keys.contains($0.key) }; origins = [:] }
    }
    private func resourceControls(_ node: String) -> some View {
        let cpus = draft["nodes"][node]["cpus"].integer ?? 1, memory = draft["nodes"][node]["memory_mb"].integer ?? 512
        let selected = draft["nodes"][node]["depends_on"].items.compactMap(\.text)
        return VStack(alignment: .leading, spacing: 4) {
            HStack {
                Stepper("CPU \(cpus)", value: Binding(get: { cpus }, set: { count in model.sceneEditDraft { try MacGraphDraft.resources($0, node: node, cpus: count, memory: memory) } }), in: 1...64)
                Text("内存MiB").font(.caption)
                Picker("内存MiB", selection: Binding(get: { memory }, set: { size in model.sceneEditDraft { try MacGraphDraft.resources($0, node: node, cpus: cpus, memory: size) } })) {
                    ForEach(Array(Set([256,512,1024,2048,4096,8192,16384,32768,65536,131072,262144,memory])).sorted(), id: \.self) { Text(String($0)).tag($0) }
                }.labelsHidden().frame(width: 100).accessibilityLabel(node + "内存MiB")
            }
            Menu("启动依赖（\(selected.count)）") {
                ForEach(nodes.filter { $0 != node }, id: \.self) { dependency in
                    Toggle(dependency, isOn: Binding(get: { selected.contains(dependency) }, set: { enabled in
                        model.sceneEditDraft { try MacGraphDraft.dependencies($0, node: node, selected: enabled ? selected + [dependency] : selected.filter { $0 != dependency }) }
                    }))
                }
            }
        }
    }
    private func nodeCard(_ node: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack { grip("node:" + node,node,point: nodePoint(node)); Spacer(); Button("移除草稿节点") { model.sceneEditDraft { try MacGraphDraft.removeNode($0, name: node) } } }
            resourceControls(node)
            ForEach(Array(draft["nodes"][node]["interfaces"].items.enumerated()), id: \.offset) { _, nic in
                HStack {
                    Text(nic["id"].text ?? "")
                    Picker("连接", selection: Binding(get: { nic["network"].text ?? "" }, set: { network in model.sceneEditDraft { try MacGraphDraft.connect($0, node: node, nic: nic["id"].text, network: network) } })) {
                        ForEach(networks, id: \.self) { Text($0).tag($0) }
                    }.labelsHidden()
                    Button("断开") { model.sceneEditDraft { try MacGraphDraft.disconnect($0, node: node, nic: nic["id"].text ?? "") } }
                    Text(nic["address"].text ?? "").font(.caption)
                }.frame(height: 36)
                    .background(GeometryReader { proxy in Color.clear.preference(key:MacGraphFramesKey.self,value:[("nic:" + node + "/" + (nic["id"].text ?? "")):proxy.frame(in:.named("mac-graph-board"))]) })
            }
            Picker("新增网卡到", selection: Binding(get: { "" }, set: { network in if !network.isEmpty { model.sceneEditDraft { try MacGraphDraft.connect($0, node: node, nic: nil, network: network) } } })) {
                Text("选择网段").tag(""); ForEach(networks, id: \.self) { Text($0).tag($0) }
            }
        }.padding(10).background(.blue.opacity(0.06)).cornerRadius(8)
    }
}


private final class MacGuestRecoverySelection: ObservableObject {
    @Published var target = ""
}
private struct MacGuestRecoveryView: View {
    @ObservedObject var model: GuiModel
    let node: String
    @StateObject private var selection = MacGuestRecoverySelection()
    private var view: MacRemoteJSON { model.sceneLocalView ?? .null }
    private var records: [MacRemoteJSON] { view["guest_agents"][node]["preparation_records"].items }
    private var target: String { selection.target.isEmpty ? records.first?["operation_id"].text ?? "" : selection.target }
    private var snapshot: MacRemoteJSON { view["guest_agents"][node]["last_action"].text == "preparation-inspect" ? view["guest_agents"][node]["last_result"] : .null }
    private func enabled(_ resume: Bool) -> Bool { model.sceneGenericAllowed("guest") && (try? MacGuestRecovery.parameters(view,node: node,target: target,resume: resume)) != nil }
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("准备中断后，先恢复核验实验进程，再核对原准备记录。旧记录不代表来宾当前状态。").font(.caption)
            if !records.isEmpty {
                Picker("原准备记录",selection: Binding(get: { target },set: { selection.target = $0 })) {
                    if !records.contains(where: { $0["operation_id"].text == target }) { Text("手动选择的记录").tag(target) }
                    ForEach(records.compactMap { $0["operation_id"].text },id: \.self) { operation in Text(String(operation.prefix(8))).tag(operation) }
                }
            }
            TextField("准备记录标识",text: Binding(get: { target },set: { selection.target = String($0.prefix(36)).trimmingCharacters(in: .whitespacesAndNewlines) }))
                .accessibilityLabel(node + "准备记录标识")
            HStack {
                Button("核对容器准备现场") { model.sceneGuestPreparation(node,target: target,resume: false) }.disabled(!enabled(false))
                Button("保留现场，继续准备") {
                    let alert = NSAlert(); alert.messageText = "保留旧文件和数据，只续建已核对的未完成准备？"
                    alert.informativeText = "可能创建缺少的容器，但保持停止；结果未知的装载或创建不会重发。"; alert.addButton(withTitle: "继续准备"); alert.addButton(withTitle: "取消")
                    if alert.runModal() == .alertFirstButtonReturn { model.sceneGuestPreparation(node,target: target,resume: true) }
                }.disabled(!enabled(true))
            }
            if snapshot["operation_id"].text == target {
                if snapshot["state"].text == "completed" { Text("该准备操作已有完成记录；本次核对未重放操作，真实服务仍需另行验收。").font(.caption) }
                if snapshot["state"].text == "preparation-observed" {
                    Text(snapshot["can_resume"].flag == true ? "可以继续未完成的准备；不会启动容器。" : "当前现场不允许续建，请保留记录。").font(.caption)
                    ForEach(Array(snapshot["steps"].items.enumerated()),id: \.offset) { _,step in
                        Text((step["step"].text ?? "") + " · " + (["recorded":"身份与记录一致","observed-unrecorded":"资源存在，记录未闭合","not-started":"尚未开始","unknown-absent":"结果未知且未找到资源","recorded-missing":"已有记录但资源缺失"][step["state"].text ?? ""] ?? "待核对")).font(.caption)
                    }
                }
            }
        }.padding(8)
    }
}


/// 只读运行拓扑：设计连线与已绑定进程采样分开，不推断地址或可达性。
private struct MacRuntimeTopology: View {
    let view: MacRemoteJSON
    var expanded = false
    private var nodes: [MacRemoteJSON] { view["topology"]["nodes"].items }
    private var networks: [String] { MacGraphDraft.keys(view["topology"]["networks"]) }
    private func height(_ node: MacRemoteJSON) -> CGFloat { CGFloat(62 + 22 * node["interfaces"].items.count) }
    private func top(_ index: Int) -> CGFloat { 12 + nodes.prefix(index).reduce(CGFloat(0)) { $0 + height($1) + 16 } }
    private var boardHeight: CGFloat { max(160,max(nodes.reduce(CGFloat(24)) { $0 + height($1) + 16 },CGFloat(100 * networks.count + 24))) }
    var body: some View {
        VStack(alignment: .leading,spacing: 5) {
            Text("设计连接与现场采样").font(.headline)
            Text("连线和地址来自计划；进程采样不代表来宾、服务或网络隔离已验收。").font(.caption)
            ScrollView([.horizontal,.vertical]) {
                ZStack(alignment: .topLeading) {
                    Canvas { context,_ in
                        for (index,node) in nodes.enumerated() {
                            for (nicIndex,nic) in node["interfaces"].items.enumerated() {
                                if let network = networks.firstIndex(of: nic["network"].text ?? "") {
                                    var line = Path();line.move(to:CGPoint(x:350,y:top(index)+45+CGFloat(nicIndex*22)))
                                    line.addLine(to:CGPoint(x:520,y:CGFloat(network*100)+42));context.stroke(line,with:.color(.secondary.opacity(0.5)),lineWidth:1)
                                }
                            }
                        }
                    }.frame(width:810,height:boardHeight)
                    ForEach(Array(nodes.enumerated()),id: \.offset) { index,node in
                        VStack(alignment:.leading,spacing:0) {
                            let state = MacObservationWindow.fresh(view) ? node["state"].text : "unknown"
                            Text((node["id"].text ?? "") + " · " + (["stopped":"已观测停止","process-running":"进程运行中"][state ?? ""] ?? "未取得当前状态")).bold().lineLimit(1).frame(height:24,alignment:.leading)
                            ForEach(Array(node["interfaces"].items.enumerated()),id: \.offset) { _,nic in
                                Text((nic["id"].text ?? "") + " → " + (nic["network"].text ?? "") + " · " + (nic["planned_address"].text ?? "") + "（设计）").font(.caption).lineLimit(1).frame(height:22,alignment:.leading)
                            }
                        }.padding(10).frame(width:338,height:height(node),alignment:.topLeading).background(.blue.opacity(0.06)).cornerRadius(6).offset(x:12,y:top(index))
                    }
                    ForEach(Array(networks.enumerated()),id: \.element) { index,network in
                        VStack(alignment:.leading,spacing:5) { Text(network).bold().lineLimit(1);Text(view["topology"]["networks"][network]["cidr"].text ?? "").font(.caption);Text("隔离及可达性待实测").font(.caption2) }
                            .padding(10).frame(width:270,height:82,alignment:.leading).background(.green.opacity(0.08)).cornerRadius(6).offset(x:520,y:CGFloat(index*100)+12)
                    }
                }.frame(width:810,height:boardHeight)
            }.frame(maxHeight: expanded ? .infinity : 350)
        }
    }
}

/// 外部攻击机卡片：登记、环境检查、网段选择、连接、断开、材料、终端入口与恢复说明。
/// 全部动作经 sceneGenericCall 走同一桥接契约；连接按前置条件开放，未知状态如实显示。
struct MacExternalAttachCard: View {
    let model: GuiModel
    let summary: MacExternalAttachSummary?
    private func field(_ key: String) -> Binding<String> {
        Binding(get: { self.model.sceneAttachForm[key] ?? "" },
                set: { self.model.sceneAttachForm[key] = $0 })
    }
    private var attachStatus: MacRemoteJSON { model.sceneExternalAttach ?? .null }
    private var attachSessionState: String { attachStatus["session"]["state"].text ?? "idle" }

    private func isAbsoluteInput(_ value: String) -> Bool {
        return value.hasPrefix("/") || value.contains(":\\\\") || value.contains(":/")
            || (value.count >= 3 && value[value.index(value.startIndex, offsetBy: 1)] == ":"
                && (value[value.index(value.startIndex, offsetBy: 2)] == "/" || value[value.index(value.startIndex, offsetBy: 2)] == "\\"))
    }

    private var name: Binding<String> { field("name") }
    private var host: Binding<String> { field("host") }
    private var port: Binding<String> { field("port") }
    private var user: Binding<String> { field("user") }
    private var identity: Binding<String> { field("identity") }
    private var machineUUID: Binding<String> { field("machineUUID") }
    private var vendor: Binding<String> { field("vendor") }
    private var product: Binding<String> { field("product") }
    private var assistantSHA: Binding<String> { field("assistantSHA") }
    private var selectedNetwork: Binding<String> { field("selectedNetwork") }
    private var sshConfigPath: Binding<String> { field("sshConfigPath") }
    private var materialsPath: Binding<String> { field("materialsPath") }

    private func call(_ payload: [String: MacRemoteJSON], refresh: Bool = true) {
        model.sceneGenericCall(payload)
        if refresh {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                model.sceneGenericCall(["action": .string("external-attach-status")])
            }
        }
    }

    private var registrationJSON: MacRemoteJSON? {
        guard !name.wrappedValue.isEmpty, !identity.wrappedValue.isEmpty,
              !machineUUID.wrappedValue.isEmpty,
              let portValue = Int(port.wrappedValue), (1...65535).contains(portValue),
              assistantSHA.wrappedValue.count == 64 else { return nil }
        let ssh: [String: MacRemoteJSON] = ["host": .string(host.wrappedValue),
                                            "port": .number(Double(portValue)),
                                            "user": .string(user.wrappedValue),
                                            "identity": .string(identity.wrappedValue)]
        let registration: [String: MacRemoteJSON] = [
            "schema": .number(1), "kind": .string("kali-l2-v1"), "name": .string(name.wrappedValue),
            "node_uuid": .string(UUID().uuidString.lowercased()),
            "machine_uuid": .string(machineUUID.wrappedValue), "vendor": .string(vendor.wrappedValue),
            "product": .string(product.wrappedValue), "ssh": .object(ssh),
            "assistant_sha256": .string(assistantSHA.wrappedValue.lowercased())]
        return .object(registration)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("外部攻击机").font(.headline)
                Button("读取状态") {
                    model.sceneGenericCall(["action": .string("external-attach-status")])
                }.disabled(model.sceneWorkspaceBusy)
            }
            Text("Kali 的启动、暂停、关机、快照和磁盘仍由原虚拟机软件管理；CTFLab 只提供指定实验网段的受控接入。普通桌面程序不进入实验网络。").font(.caption)
            if let summary {
                Text(summary.bindingText).font(.subheadline)
                    .foregroundStyle(summary.bindingStale ? .orange : .primary)
                if summary.slots.isEmpty {
                    Text("当前计划未声明外部接入口；运行中的旧实验不热改，下次创建实验代次生效。").font(.caption)
                } else {
                    ForEach(Array(summary.slots.enumerated()), id: \.offset) { _, slot in
                        HStack {
                            Image(systemName: selectedNetwork.wrappedValue == slot.network ? "largecircle.fill.circle" : "circle")
                                .onTapGesture { selectedNetwork.wrappedValue = slot.network }
                            Text("\(slot.network) · \(slot.address) · \(slot.mac)（静态预约，\(slot.cidr)）").font(.caption)
                        }
                    }
                    Text("实验地址（靶机回连目标）：\(summary.slots.first?.address ?? "-") · 仅对本网段有效").font(.caption).textSelection(.enabled)
                }
                if attachStatus["session"] != .null {
                    let state = attachSessionState
                    Text("会话：\(state)" + (attachStatus["session"]["identity_state"].text.map { " · 身份：\($0)" } ?? "")).font(.caption)
                        .foregroundStyle(state == "unknown" ? .orange : .primary)
                }
                Text(summary.note).font(.caption2).foregroundStyle(.secondary)
                if let note = model.sceneExternalAttach?["note"].text {
                    Text(note).font(.caption2).foregroundStyle(.secondary)
                }
                DisclosureGroup("登记 / 连接 / 断开") {
                    VStack(alignment: .leading, spacing: 6) {
                        TextField("显示名称", text: name).textFieldStyle(.roundedBorder)
                        HStack {
                            TextField("SSH地址", text: host).textFieldStyle(.roundedBorder)
                            TextField("端口", text: port).textFieldStyle(.roundedBorder).frame(width: 70)
                            TextField("SSH用户", text: user).textFieldStyle(.roundedBorder).frame(width: 130)
                        }
                        TextField("本地私钥绝对路径（/… 或 C:/…）", text: identity).textFieldStyle(.roundedBorder)
                        HStack {
                            TextField("机器UUID（Kali内读取）", text: machineUUID).textFieldStyle(.roundedBorder)
                            TextField("助手SHA-256", text: assistantSHA).textFieldStyle(.roundedBorder)
                        }
                        HStack {
                            TextField("厂商", text: vendor).textFieldStyle(.roundedBorder)
                            TextField("产品", text: product).textFieldStyle(.roundedBorder)
                        }
                        HStack {
                            Button("保存登记") {
                                guard let registration = registrationJSON, !selectedNetwork.wrappedValue.isEmpty else { return }
                                call(["action": .string("external-attach-save"),
                                      "registration": registration,
                                      "network": .string(selectedNetwork.wrappedValue)])
                            }
                            .disabled(model.sceneWorkspaceBusy || selectedNetwork.wrappedValue.isEmpty || registrationJSON == nil)
                            Button("清除登记") {
                                call(["action": .string("external-attach-clear")])
                            }.disabled(model.sceneWorkspaceBusy)
                        }
                        HStack {
                            TextField("SSH配置JSON绝对路径", text: sshConfigPath).textFieldStyle(.roundedBorder)
                            Button("连接") {
                                call(["action": .string("external-attach-connect"),
                                      "ssh_config": .string(sshConfigPath.wrappedValue)])
                            }
                            .disabled(model.sceneWorkspaceBusy || !isAbsoluteInput(sshConfigPath.wrappedValue)
                                      || !summary.connectSupported
                                      || attachStatus["binding"]["prepared"] == .null
                                      || attachStatus["binding"]["prepared"]["used"] == .bool(true)
                                      || !["idle", "disconnected", "unknown"].contains(attachSessionState))
                            Button("断开") {
                                call(["action": .string("external-attach-disconnect")])
                            }.disabled(model.sceneWorkspaceBusy
                                       || !["connecting", "connected", "unknown"].contains(attachSessionState))
                        }
                    }.padding(.vertical, 4)
                }
                if let setup = attachStatus["binding"]["prepared"]["setup_command"].text {
                    Text("Kali 内管理员执行：\(setup)").font(.caption).textSelection(.enabled)
                    if let shell = attachStatus["binding"]["prepared"]["shell_command"].text {
                        Text("实验终端：\(shell)").font(.caption).textSelection(.enabled)
                    }
                    if let teardown = attachStatus["binding"]["prepared"]["teardown_command"].text {
                        Text("撤网：\(teardown)").font(.caption).textSelection(.enabled)
                    }
                    // 设计§4.3持久批准：连接前须把登记摘要与本机材料清单绑定入账本。
                    Text("连接前须完成助手安装批准（未批准会按身份未核验拒绝）：在终端运行 `ctflab external-attach approve --registration <登记JSON> --materials-manifest <材料目录>/manifest.json`。")
                        .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                }
                DisclosureGroup("Kali 助手材料与实验终端") {
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            TextField("材料输出目录绝对路径", text: materialsPath).textFieldStyle(.roundedBorder)
                            Button("生成材料") {
                                call(["action": .string("external-attach-materials"),
                                      "destination": .string(materialsPath.wrappedValue)])
                            }.disabled(model.sceneWorkspaceBusy || materialsPath.wrappedValue.isEmpty)
                        }
                        Text("安装与账户准备见材料内 INSTALL.md；安装属独立部署动作。").font(.caption2)
                        Text("会话创建（Kali 内 root）：先生成材料，按 manifest.json 的 prepared.setup_command 创建会话；prepared.shell_command 进入实验终端，prepared.teardown_command 撤网。").font(.caption2).textSelection(.enabled)
                    }.padding(.vertical, 4)
                }
                Text("恢复说明：断开只撤中转通道，不停止 VM、不结束 Kali 内工具；残留进程与命名空间以助手 status 为准。会话 unknown 时先核对进程再重试或显式清除；快照/代次变化后旧接入失效，需重新预览。").font(.caption2).foregroundStyle(.secondary)
            } else {
                Text("状态未读取。点击「读取状态」获取登记、槽位与会话信息。").font(.caption)
            }
        }.padding(10).frame(maxWidth: .infinity, alignment: .leading)
            .background(.blue.opacity(0.05)).cornerRadius(8)
    }
}
