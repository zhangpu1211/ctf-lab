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
            state.configuredProfileIDs = Set(LabNode.required.map(\.rawValue))
            state.selectedProfileIDs = state.configuredProfileIDs
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
                        self.state.selectedProfileIDs = Set(baseProfiles)
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
        state.selectedProfileIDs = Set(profileIDs)
        state.phase = .importing
        importNext(profileIDs: profileIDs, index: 0, layout: layout)
    }

    private func importNext(profileIDs: [String], index: Int, layout: DistributionLayout) {
        guard index < profileIDs.count else {
            state.phase = .imported
            state.progressText = ""
            appendLog("\(profileIDs.count) 个节点导入完成。可随时追加启动未运行节点；Kali 图形启动默认联网并自动适配分辨率。")
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

    func setNodeSelected(_ profileID: String, selected: Bool) {
        guard !state.phase.isBusy else { return }
        if selected {
            state.selectedProfileIDs.insert(profileID)
        } else {
            state.selectedProfileIDs.remove(profileID)
        }
    }

    func startSelected() {
        guard state.canStartSelected else {
            state.lastError = state.selectedProfileIDs.isEmpty
                ? "请至少选择一个节点。"
                : "所选节点尚未全部导入，或所选节点均已在运行。"
            return
        }
        let selected = LabNode.orderedProfileIDs(state.startableSelectedProfileIDs)
        state.phase = .busy
        state.progressText = "正在启动 \(selected.count) 个未运行节点…（Kali 默认联网并自动适配分辨率）"
        run(.runProfiles(profileIDs: selected)) { [weak self] outcome in
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

    /// 单节点操作给课程扩容留下入口：已运行的其他节点不会阻塞它。
    func startProfile(_ profileID: String) {
        guard !state.phase.isBusy, state.importedProfileIDs.contains(profileID),
              !state.runningProfileIDs.contains(profileID) else { return }
        state.phase = .busy
        state.progressText = "正在启动 \(LabNode.displayName(for: profileID))…"
        run(.runProfiles(profileIDs: [profileID])) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            if case .failure(let message) = outcome { self.state.lastError = message }
            self.refreshStatus()
        }
    }

    func stopProfile(_ profileID: String) {
        guard !state.phase.isBusy, state.runningProfileIDs.contains(profileID) else { return }
        state.phase = .busy
        state.progressText = "正在停止 \(LabNode.displayName(for: profileID))…"
        run(.stopProfiles(profileIDs: [profileID])) { [weak self] outcome in
            guard let self else { return }
            self.state.phase = .idle
            self.state.progressText = ""
            if case .failure(let message) = outcome { self.state.lastError = message }
            self.refreshStatus()
        }
    }

    func stopAll() {
        guard state.canStop else { return }
        state.phase = .busy
        state.progressText = "正在停止全部实例…"
        run(.stopAll) { [weak self] outcome in
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
            Button("启动未运行的所选节点") { model.startSelected() }
                .disabled(!model.state.canStartSelected)
            Button("检查状态") { model.checkStatus() }
                .disabled(!model.state.canCheckStatus)
            Button("停止全部") { model.stopAll() }
                .disabled(!model.state.canStop)
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
            Text("启动选择")
                .font(.headline)
            ForEach(LabNode.orderedProfileIDs(model.state.configuredProfileIDs), id: \.self) { profileID in
                Toggle(LabNode.displayName(for: profileID),
                       isOn: Binding(
                           get: { model.state.selectedProfileIDs.contains(profileID) },
                           set: { model.setNodeSelected(profileID, selected: $0) }
                       ))
                .toggleStyle(.checkbox)
                // 已有节点运行时仍可选择其余节点并追加启动；运行中的节点会被启动动作略过。
                .disabled(model.state.phase.isBusy || !model.state.importedProfileIDs.contains(profileID))
            }
            Spacer()
            Text("运行中的节点不会阻塞追加启动；Kali 默认联网 + 自动分辨率")
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
                    TableColumn("已导入") { row in Text(row.imported ? "是" : "否") }
                    TableColumn("运行中") { row in Text(row.running ? "PID \(row.pid ?? 0)" : "否") }
                    TableColumn("健康") { row in
                        Text(model.state.healthyProfileIDs.contains(row.id)
                             ? "通过" : (model.state.pendingHealthProfileIDs.contains(row.id)
                                         ? "等待" : (row.running ? "待检查" : "—")))
                    }
                    TableColumn("操作") { row in
                        HStack(spacing: 6) {
                            if row.running {
                        Button("停止") { model.stopProfile(row.id) }
                            .disabled(model.state.phase.isBusy)
                            } else {
                                Button("启动") { model.startProfile(row.id) }
                                    .disabled(!row.imported || model.state.phase.isBusy)
                            }
                        }
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
