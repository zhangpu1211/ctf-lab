// CTFLab 图形入口（SwiftUI/AppKit，GUI 框架 macOS 13+；课堂 App 随包运行时要求 macOS 15.0+）。
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

    private static func nodesToSet(_ profiles: [StatusProfile]) -> Set<LabNode> {
        Set(profiles.compactMap { LabNode(rawValue: $0.id) })
    }

    /// 表格只展示三个实验节点；其余 profile（例如适配候选）不进入图形界面。
    private func applyStatusReport(_ report: StatusReport) {
        let required = Set(LabNode.required.map(\.rawValue))
        nodes = report.profiles.filter { required.contains($0.id) }
        state.importedNodes = Self.nodesToSet(report.profiles.filter(\.imported))
        state.runningNodes = Self.nodesToSet(report.profiles.filter(\.running))
        // 状态刷新后必须丢弃上一次健康结果；否则重启后的节点会被显示成“通过”。
        state.healthyNodes.removeAll()
        state.pendingHealthNodes.removeAll()
    }

    // MARK: 动作

    func chooseDistributionDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "选择分发目录"
        panel.message = "选择包含 DISTRIBUTION.json、SHA256SUMS 与三个基盘的分发目录"
        if panel.runModal() == .OK, let url = panel.url {
            state.distDir = url.path
            state.report = nil
            verifyRows = []
            // 导入状态属于状态目录，不等于新选择的分发目录已经导入；切换目录后必须重新导入。
            state.importedNodes.removeAll()
            state.selectedNodes = Set(LabNode.required)
            state.healthyNodes.removeAll()
            state.pendingHealthNodes.removeAll()
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
        var missing: [String] = []
        for node in LabNode.required where layout.basePath(for: node) == nil {
            missing.append(node.displayName)
        }
        guard missing.isEmpty else {
            state.lastError = "分发清单里缺少这些节点的基盘条目：\(missing.joined(separator: "、"))"
            appendLog(state.lastError ?? "")
            return
        }
        state.phase = .importing
        importNext(nodes: LabNode.required, index: 0, layout: layout)
    }

    private func importNext(nodes: [LabNode], index: Int, layout: DistributionLayout) {
        guard index < nodes.count else {
            state.phase = .imported
            state.progressText = ""
            appendLog("三个节点导入完成。请选择要启动的节点。Kali 图形启动默认联网并自动适配分辨率。")
            refreshStatus()
            return
        }
        let node = nodes[index]
        state.progressText = state.importProgressText(index: index, total: nodes.count, node: node)
        guard let sourcePath = layout.basePath(for: node) else {
            state.phase = .failed
            state.lastError = "分发清单里缺少 \(node.displayName) 的基盘条目"
            return
        }
        run(.importNode(node: node, sourcePath: sourcePath,
                        manifestPath: layout.manifestPath)) { [weak self] outcome in
            guard let self else { return }
            switch outcome {
            case .success:
                self.state.importedNodes.insert(node)
                self.appendLog("\(node.displayName) 导入完成")
                self.importNext(nodes: nodes, index: index + 1, layout: layout)
            case .failure(let message):
                self.state.phase = .failed
                self.state.progressText = ""
                self.state.lastError = message
                self.appendLog(message)
            }
        }
    }

    func setNodeSelected(_ node: LabNode, selected: Bool) {
        guard !state.phase.isBusy && !state.anyRunning else { return }
        if selected {
            state.selectedNodes.insert(node)
        } else {
            state.selectedNodes.remove(node)
        }
    }

    func startSelected() {
        guard state.canStartSelected else {
            state.lastError = state.selectedNodes.isEmpty
                ? "请至少选择一个节点。"
                : "所选节点尚未全部导入，或当前仍有节点运行。"
            return
        }
        let selected = LabNode.required.filter { state.selectedNodes.contains($0) }
        state.phase = .busy
        state.progressText = "正在启动所选节点…（Kali 默认联网并自动适配分辨率）"
        run(.run(nodes: selected)) { [weak self] outcome in
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
        state.healthyNodes.removeAll()
        state.pendingHealthNodes.removeAll()
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
            let activeNodes = LabNode.required.filter { self.state.runningNodes.contains($0) }
            self.checkHealthSequence(nodes: activeNodes, index: 0)
        }
    }

    private func checkHealthSequence(nodes: [LabNode], index: Int) {
        guard index < nodes.count else {
            state.phase = .idle
            state.progressText = ""
            appendLog("状态与健康检查完成。")
            return
        }
        let node = nodes[index]
        run(.health(node: node)) { [weak self] outcome in
            guard let self else { return }
            switch outcome {
            case .success(let text), .failure(let text):
                if let report = GuiParsing.decodeHealth(text) {
                    if report.isPending {
                        self.state.pendingHealthNodes.insert(node)
                        self.state.healthyNodes.remove(node)
                    } else if report.ok {
                        self.state.pendingHealthNodes.remove(node)
                        self.state.healthyNodes.insert(node)
                    } else {
                        self.state.pendingHealthNodes.remove(node)
                        self.state.healthyNodes.remove(node)
                    }
                    let detail = report.checks.map {
                        "\($0.ok == true ? "OK" : ($0.ok == nil ? "WAIT" : "FAIL")) \($0.name)"
                    }.joined(separator: ", ")
                    let label = report.isPending ? "等待" : (report.ok ? "通过" : "未通过")
                    self.appendLog("\(node.displayName) 健康检查：\(label)（\(detail)）")
                } else {
                    self.appendLog(text)
                }
            }
            self.checkHealthSequence(nodes: nodes, index: index + 1)
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
            appendLog("重置完成：三个节点的 overlay 已删除，基础镜像未受影响。")
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
            Button("启动所选节点") { model.startSelected() }
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
            Text("启动节点")
                .font(.headline)
            ForEach(LabNode.required) { node in
                Toggle(node.displayName,
                       isOn: Binding(
                           get: { model.state.selectedNodes.contains(node) },
                           set: { model.setNodeSelected(node, selected: $0) }
                       ))
                .toggleStyle(.checkbox)
                .disabled(model.state.phase.isBusy || model.state.anyRunning
                          || !model.state.importedNodes.contains(node))
            }
            Spacer()
            Text("Kali 图形启动默认联网 + 自动分辨率")
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
                    TableColumn("节点") { row in Text(row.name ?? row.id) }
                    TableColumn("已导入") { row in Text(row.imported ? "是" : "否") }
                    TableColumn("运行中") { row in Text(row.running ? "PID \(row.pid ?? 0)" : "否") }
                    TableColumn("健康") { row in
                        Text(model.state.healthyNodes.contains(where: { $0.rawValue == row.id })
                             ? "通过" : (model.state.pendingHealthNodes.contains(where: { $0.rawValue == row.id })
                                         ? "等待" : (row.running ? "待检查" : "—")))
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
