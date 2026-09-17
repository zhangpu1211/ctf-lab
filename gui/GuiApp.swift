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
    @Published var showResetConfirmation = false
    @Published var showImageOnboarding = false
    @Published var onboardingSourcePath = ""
    @Published var onboardingProfileID = ""
    @Published var onboardingReport: ImageInspectionReport?
    @Published var onboardingImportedProfileID: String?
    @Published var onboardingMessage = ""

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

    // MARK: 持久状态恢复

    func refreshStatus() {
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
        }
    }

    private static func profileIDs(_ profiles: [StatusProfile]) -> Set<String> {
        Set(profiles.map(\.id))
    }

    /// 运行管理展示 CLI 已登记的全部 profile。未知课程节点只使用 profile ID，不让 GUI
    /// 猜测其硬件参数；实际白名单仍由 CLI/profile YAML 决定。
    private func applyStatusReport(_ report: StatusReport) {
        nodes = report.profiles
        state.importedProfileIDs = Self.profileIDs(report.profiles.filter(\.imported))
        state.runningProfileIDs = Self.profileIDs(report.profiles.filter(\.running))
        // 状态刷新后必须丢弃上一次健康结果；否则重启后的节点会被显示成“通过”。
        state.healthyProfileIDs.removeAll()
        state.pendingHealthProfileIDs.removeAll()
    }

    // MARK: 动作

    func chooseDistributionDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "选择分发目录"
        panel.message = "选择包含 DISTRIBUTION.json、SHA256SUMS 与课程基盘的分发目录"
        if panel.runModal() == .OK, let url = panel.url {
            state.distDir = url.path
            state.report = nil
            verifyRows = []
            // 导入状态属于状态目录，不等于新选择的分发目录已经导入；切换目录后必须重新导入。
            state.importedProfileIDs.removeAll()
            state.configuredProfileIDs.removeAll()
            state.selectedProfileID = nil
            state.healthyProfileIDs.removeAll()
            state.pendingHealthProfileIDs.removeAll()
            state.phase = .idle
            state.lastError = nil
            let layout = DistributionLayout(dir: url.path)
            let detection = layout.detect()
            appendLog("已选择分发目录：\(url.path)")
            if detection.missing.isEmpty {
                appendLog("自动识别：DISTRIBUTION.json、SHA256SUMS 与 \(detection.found.count - 2) 个载荷文件齐全，请点击“校验分发目录”。")
            } else {
                appendLog("自动识别：缺少 \(detection.missing.joined(separator: "、"))；校验将给出详细原因。")
            }
        }
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
        onboardingSourcePath = url.path
        onboardingProfileID = ImageOnboardingRules.suggestedProfileID(sourcePath: url.path)
        onboardingReport = nil
        onboardingImportedProfileID = nil
        onboardingMessage = "原始镜像只读；请先执行“只读识别”，确认候选硬件后再导入。"
        showImageOnboarding = true
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

    func verifyDistribution() {
        guard let dir = state.distDir, !dir.isEmpty else {
            state.lastError = "请先选择分发目录"
            return
        }
        state.phase = .verifying
        state.progressText = "正在校验分发目录…"
        run(.distVerify(dir: dir)) { [weak self] outcome in
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
        state.phase = .importing
        importNext(profileIDs: profileIDs, index: 0, layout: layout)
    }

    private func importNext(profileIDs: [String], index: Int, layout: DistributionLayout) {
        guard index < profileIDs.count else {
            state.phase = .imported
            state.progressText = ""
            appendLog("\(profileIDs.count) 个节点导入完成。请选择一个节点再启动；Kali 默认使用稳定的固定显示。")
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
        state.progressText = "正在启动 \(LabNode.displayName(for: selectedProfileID))…（Kali 默认固定显示）"
        run(.runProfiles(profileIDs: [selectedProfileID])) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            if case .failure(let message) = outcome { self.state.lastError = message }
            self.refreshStatus()
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

    func requestReset() {
        guard state.canReset else { return }
        showResetConfirmation = true
    }

    func confirmReset() {
        let plan = ResetGate.plan(state: state, confirmed: true)
        showResetConfirmation = false
        guard let plan else { return }
        state.phase = .busy
        resetSequence(plan: plan, index: 0)
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
            nodeSelection
            nodeTable
            logPanel
        }
        .padding(16)
        .frame(minWidth: 980, minHeight: 720)
        .alert(GuiMessages.resetConfirmationTitle, isPresented: $model.showResetConfirmation) {
            Button(GuiMessages.resetCancelButton, role: .cancel) {}
            Button(GuiMessages.resetConfirmButton, role: .destructive) { model.confirmReset() }
        } message: {
            Text(GuiMessages.resetConfirmationBody)
        }
        .sheet(isPresented: $model.showImageOnboarding) {
            ImageOnboardingSheet(model: model)
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
            Text("分发目录")
            Text(model.state.distDir ?? "（未选择）")
                .textSelection(.enabled)
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(6)
                .background(Color(nsColor: .textBackgroundColor))
                .cornerRadius(4)
            Button("选择…") { model.chooseDistributionDirectory() }
        }
    }

    private var actionRow: some View {
        HStack(spacing: 10) {
            Button("校验分发目录") { model.verifyDistribution() }
                .disabled(!model.state.canVerify)
            Button("导入实验环境") { model.importAll() }
                .disabled(!model.state.canImport)
            Button("添加 x86 镜像…") { model.chooseX86Image() }
                .disabled(model.state.phase.isBusy)
            Button("启动所选节点") { model.startSelected() }
                .disabled(!model.state.canStartSelected)
            Button("检查状态") { model.checkStatus() }
                .disabled(!model.state.canCheckStatus)
            Button("停止所选节点") { model.stopSelected() }
                .disabled(!model.state.canStopSelected)
            Button("重置…") { model.requestReset() }
                .disabled(!model.state.canReset)
            Spacer()
            if model.state.phase.isBusy || !model.state.progressText.isEmpty {
                ProgressView().controlSize(.small)
                Text(model.state.progressText).font(.caption)
            }
        }
    }

    private var nodeSelection: some View {
        HStack(spacing: 12) {
            Text("当前节点")
                .font(.headline)
            Picker("当前节点", selection: Binding(
                get: { model.state.selectedProfileID ?? "" },
                set: { model.selectNode($0.isEmpty ? nil : $0) }
            )) {
                Text("请选择…").tag("")
                ForEach(LabNode.orderedProfileIDs(model.state.configuredProfileIDs), id: \.self) { profileID in
                    let imported = model.state.importedProfileIDs.contains(profileID)
                    Text("\(LabNode.displayName(for: profileID))（\(imported ? "本机已登记" : "未导入")）")
                        .tag(profileID)
                }
            }
            .labelsHidden()
            .pickerStyle(.menu)
            .disabled(model.state.phase.isBusy || model.state.configuredProfileIDs.isEmpty)
            Spacer()
            Text("一次只操作一个节点；Kali 默认联网 + 固定显示")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
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

    private var verifyTable: some View {
        Group {
            if model.verifyRows.isEmpty {
                Text("尚未校验：选择分发目录后点击“校验分发目录”。")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
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

    private var nodeTable: some View {
        Group {
            if model.nodes.isEmpty {
                Text("节点状态：点击“检查状态”读取（重新打开 App 会自动刷新）。")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                Table(model.nodes) {
                    TableColumn("节点") { row in
                        Text(row.name ?? LabNode.displayName(for: row.id))
                    }
                    TableColumn("本机基盘") { row in
                        Text(row.imported ? "已登记" :
                             (row.importState == "missing-base" ? "记录失效" : "未导入"))
                    }
                    TableColumn("运行中") { row in Text(row.running ? "PID \(row.pid ?? 0)" : "否") }
                    TableColumn("健康") { row in
                        Text(model.state.healthyProfileIDs.contains(row.id)
                             ? "通过" : (model.state.pendingHealthProfileIDs.contains(row.id)
                                         ? "等待" : (row.running ? "待检查" : "—")))
                    }
                    TableColumn("提示") { row in
                        if row.running { Text("选择后可停止") }
                        else if row.imported { Text("选择后可启动") }
                        else { Text("需先导入") }
                    }
                    TableColumn("日志") { row in
                        Text(row.logPath ?? "—").textSelection(.enabled).lineLimit(1)
                    }
                }
                .frame(minHeight: 140)
            }
        }
    }

    private var logPanel: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("CLI 输出").font(.headline)
                Spacer()
                Button("复制错误信息") { model.copyError() }
                Button("清空") { model.log = "" }
            }
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
