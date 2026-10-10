// CTFLab 图形入口（SwiftUI/AppKit，课堂 App 与随包运行时统一要求 macOS 26.0+）。
//
// 只做三件事：驱动现有 CLI（dist verify / import --manifest / run / status / health /
// stop --all / reset）、展示结果、按状态机门禁按钮。所有业务逻辑在 GuiCore.swift。

import AppKit
import SwiftUI

// MARK: - 运行模型

enum CliOutcome {
    case success(String)
    case failure(String)
}

/// 子进程输出的线程安全缓冲（读取句柄与结束回调可能在不同队列）。
final class OutputBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()

    func append(_ chunk: Data) {
        lock.lock()
        data.append(chunk)
        lock.unlock()
    }

    func text() -> String {
        lock.lock()
        defer { lock.unlock() }
        return String(data: data, encoding: .utf8) ?? ""
    }
}

@MainActor
final class GuiModel: ObservableObject {
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
    private func importMissingFromManifest() {
        guard let dir = state.distDir else { return }
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
        guard let report = onboardingReport, report.candidate.architecture == "x86_64" else {
            onboardingMessage = "请先完成 x86_64 只读识别。"
            return
        }
        guard ImageOnboardingRules.validProfileID(onboardingProfileID) else {
            onboardingMessage = "配置 ID 只能用小写字母、数字和连字符，长度 1～49，且不能以连字符开头或结尾。"
            return
        }
        if nodes.contains(where: { $0.id == onboardingProfileID }) {
            onboardingMessage = "该配置 ID 已存在，不能覆盖。请修改 ID（例如添加 -2）后重试。"
            return
        }
        state.phase = .importing
        state.progressText = "正在创建候选配置并导入派生基盘…"
        run(.onboardX86(sourcePath: onboardingSourcePath, profileID: onboardingProfileID)) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            switch outcome {
            case .success:
                self.onboardingImportedProfileID = self.onboardingProfileID
                self.state.configuredProfileIDs.insert(self.onboardingProfileID)
                self.state.selectedProfileID = self.onboardingProfileID
                // 该文件已导入：从“文件夹新增”分组退选，右侧切到新导入的节点。
                if self.selectedFilePath == self.onboardingSourcePath {
                    self.selectedFilePath = nil
                }
                self.onboardingMessage = "候选配置和派生基盘已创建；尚未启动验证，请执行“启动探测”。"
                self.appendLog("x86_64 候选 \(self.onboardingProfileID) 已导入；原始镜像保持不变。")
                self.refreshStatus()
            case .failure(let message):
                self.onboardingMessage = "候选导入失败；原始镜像未修改。若已生成候选 profile，可修正后重试。"
                self.state.lastError = message
            }
        }
    }

    func probeOnboardingCandidate(matrix: Bool) {
        guard let profileID = onboardingImportedProfileID, !state.phase.isBusy else { return }
        state.phase = .busy
        state.progressText = matrix ? "正在运行受控启动回退矩阵…" : "正在启动探测候选镜像…"
        run(.probeProfile(profileID: profileID, matrix: matrix)) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            switch outcome {
            case .success:
                self.onboardingMessage = matrix
                    ? "回退矩阵完成：命中结果仅对本次探测有效，请查看截图和报告后再人工固化配置。"
                    : "启动探测完成：请查看日志中的截图、网络和服务证据；这不等同于已验证交付。"
            case .failure(let message):
                self.onboardingMessage = matrix
                    ? "回退矩阵未找到可用候选，或需要人工查看失败截图；原始镜像未修改。"
                    : "首次启动探测未通过；可运行受控回退矩阵，不会自动改写候选配置。"
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
            defer { completion?() }
            guard let self else { return }
            switch outcome {
            case .success(let text), .failure(let text):
                if let report = GuiParsing.decodeDistReport(text) {
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
                    self.state.lastError = report.ok ? nil : GuiMessages.verifyFailedBanner
                    let summary = report.summary.map {
                        "通过 \($0.ok)/\($0.total)"
                    } ?? ""
                    self.appendLog(report.ok
                        ? "分发目录校验通过（\(summary)）"
                        : "分发目录校验失败：\(report.problems.joined(separator: "；"))")
                } else {
                    self.state.phase = .failed
                    self.state.progressText = ""
                    self.state.lastError = text
                    self.appendLog(text)
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

    func exportDiagnostics() {
        guard !state.phase.isBusy else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "ctflab-diagnostics-\(UUID().uuidString.prefix(8)).json"
        panel.message = "包含运行状态、路径与脱敏日志尾行；不含口令和剪贴板正文。请检查后再分享。"
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

    // MARK: CLI 调用

    private func run(_ action: CliAction, completion: @escaping (CliOutcome) -> Void) {
        let arguments = action.arguments(stateDir: stateDirOverride)
        appendLog("$ \(action.displayCommand)")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: cliPath)
        process.arguments = arguments
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
        process.environment = environment
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        let handle = pipe.fileHandleForReading
        let buffer = OutputBuffer()
        handle.readabilityHandler = { [weak self] fileHandle in
            let chunk = fileHandle.availableData
            guard !chunk.isEmpty else { return }
            buffer.append(chunk)
            if let text = String(data: chunk, encoding: .utf8) {
                Task { @MainActor [weak self] in self?.appendLog(text) }
            }
        }
        process.terminationHandler = { [weak self] finished in
            handle.readabilityHandler = nil
            // terminationHandler 可能先于 readabilityHandler 收到最后一批字节；显式 drain，
            // 避免 JSON 尾部丢失导致 GUI 把一次成功误报为“无法解析输出”。
            let trailing = handle.readDataToEndOfFile()
            if !trailing.isEmpty {
                buffer.append(trailing)
                if let text = String(data: trailing, encoding: .utf8) {
                    Task { @MainActor [weak self] in self?.appendLog(text) }
                }
            }
            let output = buffer.text()
            Task { @MainActor [weak self] in
                guard self != nil else { return }
                if finished.terminationStatus == 0 {
                    completion(.success(output))
                } else {
                    let label = action.displayCommand
                    let message = GuiMessages.failureMessage(
                        action: label, exitCode: finished.terminationStatus, output: output)
                    completion(.failure(message))
                }
            }
        }
        do {
            try process.run()
        } catch {
            let message = "无法启动内置 CLI：\(error.localizedDescription)\n（\(cliPath)）"
            appendLog(message)
            completion(.failure(message))
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

struct ContentView: View {
    @ObservedObject var model: GuiModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            directoryRow
            actionRow
            if let error = model.state.lastError {
                errorBanner(error)
            }
            verifyTable
            mainSplit
            logPanel
        }
        .padding(16)
        .frame(minWidth: 1080, minHeight: 760)
        .alert(GuiMessages.resetConfirmationTitle, isPresented: $model.showResetConfirmation) {
            Button(GuiMessages.resetCancelButton, role: .cancel) {}
            Button(GuiMessages.resetConfirmButton, role: .destructive) { model.confirmReset() }
        } message: {
            Text(GuiMessages.resetConfirmationBody)
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
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            model.refreshAutomatically()
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("CTFLab 实验环境").font(.title2).bold()
            Text(model.state.statusLine).foregroundStyle(.secondary)
            Text("状态目录：\(model.stateDirLabel)").font(.caption).foregroundStyle(.secondary)
        }
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
                Button("导出脱敏诊断…") { model.exportDiagnostics() }
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
                Button("停止后续导入") { model.stopRemainingImports() }
                    .disabled(model.stopImportQueueRequested)
            }
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
                Text("镜像").font(.headline)
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
        .padding(.trailing, 12)
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
        .padding(.vertical, 2)
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
            VStack(alignment: .leading, spacing: 8) {
                Text("当前状态").font(.headline)
                Text(model.nodes.filter(\.imported).isEmpty
                     ? "尚无已导入镜像：选择镜像文件夹会自动扫描并导入，或从“导入…”手动添加。"
                     : "从左侧选择一个镜像查看状态与操作。")
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding(.leading, 12)
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

    /// 成套分发校验结果：仅在已校验（有行）时出现；普通文件夹不占位。
    @ViewBuilder
    private var verifyTable: some View {
        if !model.verifyRows.isEmpty {
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
                Button("只读识别") { model.inspectOnboardingImage() }
                    .disabled(model.onboardingSourcePath.isEmpty || model.state.phase.isBusy)
                if model.state.phase.isBusy { ProgressView().controlSize(.small) }
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
                    Spacer()
                    Button("创建候选并导入") { model.importOnboardingCandidate() }
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
                }
                Text("矩阵仅尝试 BIOS/UEFI 与 SCSI、IDE、SATA、VirtIO 白名单组合；命中结果不会自动写回配置。")
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
