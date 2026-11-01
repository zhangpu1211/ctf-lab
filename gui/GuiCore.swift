// CTFLab 图形入口核心逻辑（无 UI 依赖，可单独编译测试）。
//
// 职责：状态机、按钮门禁、CLI 命令拼接、CLI JSON 解析、错误文案。
// 约束：只调用现有 CLI 能力（dist verify / import --manifest / run / status / health /
// stop --all / reset / inspect / onboard / probe），不自行实现导入逻辑，不暴露任意 QEMU 参数；启动动作只把用户
// 选中的节点交给 CLI。Kali 的联网和图形分辨率由 CLI 的默认运行策略统一管理。

import Foundation

enum CliOutcome: Equatable, Sendable {
    case success(String)
    case failure(String)
}

struct CLIOutputSnapshot: Sendable {
    let text: String
    let complete: Bool
    let candidateCreated: Bool
    let capturedBytes: Int
}

/// 原始回复有界保留；进度和候选标记独立扫描，不能从截断JSON推断成功。
final class OutputBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()
    private var window = Data()
    private let limit: Int
    private var overflow = false
    private var failed = false
    private var candidate = false
    private var markerTail = Data()
    private let marker = Data("候选配置已生成：".utf8)
    init(limit: Int = 16 * 1024 * 1024) { precondition(limit > 0); self.limit = limit }

    func append(_ chunk: Data) {
        lock.lock(); defer { lock.unlock() }
        if chunk.count > limit - data.count { overflow = true }
        if !overflow { data.append(chunk) }
        var scan = markerTail; scan.append(chunk.prefix(marker.count - 1))
        if scan.range(of: marker) != nil || chunk.range(of: marker) != nil { candidate = true }
        markerTail = chunk.count >= marker.count - 1 ? Data(chunk.suffix(marker.count - 1)) : Data(scan.suffix(marker.count - 1))
        if chunk.count >= 65536 { window = Data(chunk.suffix(65536)) }
        else {
            if window.count + chunk.count > 65536 { window.removeFirst(window.count + chunk.count - 65536) }
            window.append(chunk)
        }
    }
    func markReadFailure() { lock.lock(); failed = true; lock.unlock() }
    var overflowed: Bool { lock.lock(); defer { lock.unlock() }; return overflow }
    func latestProgress() -> ImportProgress? {
        lock.lock(); let bytes = window; lock.unlock()
        return ImportProgress.latest(in: String(decoding: bytes, as: UTF8.self))
    }
    func snapshot() -> CLIOutputSnapshot {
        lock.lock(); defer { lock.unlock() }
        let text: String
        let complete: Bool
        if overflow { text = "响应超出上限；结果未确认，不自动重发。"; complete = false }
        else if failed { text = "响应读取未确认；后台可能继续执行，请先核对原操作。"; complete = false }
        else if let decoded = String(data: data, encoding: .utf8) { text = decoded; complete = true }
        else { text = "响应编码无法核验；结果未确认，不自动重发。"; complete = false }
        return CLIOutputSnapshot(text: text, complete: complete, candidateCreated: candidate, capturedBytes: data.count)
    }
}

enum CLIReadStatus { case received, eof, failed }

/// 所有读取及append串行，避免退出drain与readability回调交换字节次序。
final class CLIPipeCollector: @unchecked Sendable {
    private let lock = NSLock()
    private let handle: FileHandle
    private let descriptor: Int32
    private let buffer: OutputBuffer
    private var storage = [UInt8](repeating: 0, count: 65536)
    private var eof = false
    private var failed = false
    init(handle: FileHandle, buffer: OutputBuffer) {
        self.handle = handle; self.buffer = buffer
        var value = Darwin.fcntl(handle.fileDescriptor, F_DUPFD_CLOEXEC, 0)
        while value < 0 && errno == EINTR { value = Darwin.fcntl(handle.fileDescriptor, F_DUPFD_CLOEXEC, 0) }
        descriptor = value
        if value < 0 { failed = true; buffer.markReadFailure() }
    }
    deinit { if descriptor >= 0 { _ = Darwin.close(descriptor) } }
    var canObserve: Bool { descriptor >= 0 }
    func receive(_ onChunk: (Data) -> Void) -> CLIReadStatus {
        lock.lock(); defer { lock.unlock() }
        if eof { return .eof }
        if failed { return .failed }
        while true {
            let count = storage.withUnsafeMutableBytes { Darwin.read(descriptor, $0.baseAddress, $0.count) }
            if count < 0 && errno == EINTR { continue }
            if count < 0 { failed = true; buffer.markReadFailure(); return .failed }
            if count == 0 { eof = true; return .eof }
            let bytes = Data(storage.prefix(count))
            buffer.append(bytes); onChunk(bytes); return .received
        }
    }
    func drain(_ onChunk: (Data) -> Void) -> Bool {
        while true {
            switch receive(onChunk) {
            case .received: continue
            case .eof: return true
            case .failed: return false
            }
        }
    }
}

/// 显示通知合并成一个待处理批次，不能为每个chunk排入完整回复副本。
final class CLIOutputUpdates: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()
    private var progress: ImportProgress?
    private var scheduled = false
    func offer(_ chunk: Data, progress next: ImportProgress?) -> Bool {
        lock.lock(); defer { lock.unlock() }
        if chunk.count >= 65536 { data = Data(chunk.suffix(65536)) }
        else {
            if data.count + chunk.count > 65536 { data.removeFirst(data.count + chunk.count - 65536) }
            data.append(chunk)
        }
        if let next { progress = next }
        if scheduled { return false }
        scheduled = true; return true
    }
    func take() -> (text: String, progress: ImportProgress?) {
        lock.lock(); defer { lock.unlock() }
        let value = (String(decoding: data, as: UTF8.self), progress)
        data = Data(); progress = nil; scheduled = false
        return value
    }
}

final class CLIRequestSlots: @unchecked Sendable {
    static let shared = CLIRequestSlots(maximum: 8)
    private let lock = NSLock()
    private let maximum: Int
    private var count = 0
    init(maximum: Int) { precondition(maximum > 0); self.maximum = maximum }
    func acquire() -> CLIRequestTicket? {
        lock.lock(); defer { lock.unlock() }
        guard count < maximum else { return nil }
        count += 1; return CLIRequestTicket(slots: self)
    }
    fileprivate func release() { lock.lock(); count -= 1; lock.unlock() }
    var active: Int { lock.lock(); defer { lock.unlock() }; return count }
}
final class CLIRequestTicket: @unchecked Sendable {
    private let lock = NSLock()
    private let slots: CLIRequestSlots
    private var released = false
    fileprivate init(slots: CLIRequestSlots) { self.slots = slots }
    // 不在deinit释放：进程/EOF未核对时必须保留占用，不能假定后台结束。
    func release() {
        lock.lock(); defer { lock.unlock() }
        if !released { released = true; slots.release() }
    }
}

final class CLIRequestLifetime: @unchecked Sendable {
    private let lock = NSLock()
    private let ticket: CLIRequestTicket
    private var inputClosed: Bool
    private var processEnded = false
    private var outputClosed = false
    init(ticket: CLIRequestTicket, hasInput: Bool) { self.ticket = ticket; inputClosed = !hasInput }
    func inputFinished() {
        lock.lock(); defer { lock.unlock() }
        inputClosed = true; if processEnded && outputClosed { ticket.release() }
    }
    func processFinished(outputClosed: Bool) {
        lock.lock(); defer { lock.unlock() }
        processEnded = true; self.outputClosed = outputClosed
        if inputClosed && outputClosed { ticket.release() }
    }
}

final class CLIResponseOnce: @unchecked Sendable {
    private let lock = NSLock()
    private var callback: (@Sendable (CliOutcome) -> Void)?
    private var timer: DispatchSourceTimer?
    init(_ callback: @escaping @Sendable (CliOutcome) -> Void) { self.callback = callback }
    func startTimeout(seconds: Double) {
        lock.lock(); defer { lock.unlock() }
        guard callback != nil, timer == nil else { return }
        let source = DispatchSource.makeTimerSource(queue: .global(qos: .userInitiated))
        timer = source
        source.setEventHandler { [weak self] in
            _ = self?.finish(.failure("等待已超时，原操作可能继续执行；请先核对原标识，不自动重发。"))
        }
        source.schedule(deadline: .now() + max(0, seconds)); source.activate()
    }
    @discardableResult func finish(_ outcome: CliOutcome) -> Bool {
        lock.lock()
        guard let action = callback else { lock.unlock(); return false }
        callback = nil; let source = timer; timer = nil; lock.unlock()
        source?.cancel(); source?.setEventHandler {}
        action(outcome); return true
    }
}

/// 恢复点名称必须与 CLI 白名单一致，不接受路径或 shell 字符。
public enum RecoveryRules {
    public static func validName(_ name: String) -> Bool {
        name.range(of: "^[a-z0-9][a-z0-9._-]{0,31}$", options: .regularExpression) != nil
    }
    public static func checkpointName() -> String {
        "before-" + UUID().uuidString.lowercased().prefix(12)
    }
}
public struct RecoverySnapshot: Codable, Identifiable {
    public let tag: String
    public let date: String
    public var id: String { tag }
}
public struct RecoveryBackup: Codable, Identifiable {
    public let name: String
    public let complete: Bool
    public var id: String { name }
}
public struct SnapshotReport: Codable { public let snapshots: [RecoverySnapshot] }
public struct BackupReport: Codable { public let backups: [RecoveryBackup] }
public struct DisplayOpenReport: Codable { public let pid: Int; public let reconnected: Bool }
public struct PreflightReport: Codable {
    public struct Check: Codable { public let name: String; public let ok: Bool; public let detail: String; public let hint: String? }
    public let ok: Bool
    public let checks: [Check]
    public var guidance: String { checks.filter { !$0.ok }.map { $0.detail + "\n" + ($0.hint ?? "") }.joined(separator: "\n\n") }
    public static func decode(_ text: String) -> PreflightReport? {
        guard let start = text.firstIndex(of: "{"), let end = text.lastIndex(of: "}"), start <= end else { return nil }
        return try? JSONDecoder().decode(Self.self, from: Data(text[start...end].utf8))
    }
}
public struct DisplayDiagnosisReport: Codable { public let state: String; public let hint: String }

/// 内置三节点只是首个课程包的显示别名和默认顺序；运行管理不再限定这三个 ID。
public enum LabNode: String, CaseIterable, Identifiable {
    case kali = "kali-arm64"
    case smoke = "smoke"
    case basic = "basic-pentesting-2"

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .kali: return "Kali Linux ARM64"
        case .smoke: return "Smoke"
        case .basic: return "Basic Pentesting 2"
        }
    }

    /// 顺序即导入/重置顺序：Kali 优先（其 NVRAM 模板来自分发目录）。
    public static let required: [LabNode] = [.kali, .smoke, .basic]

    /// 后续课程包可以登记更多 profile。未知 ID 仍可被 GUI 管理，只是显示原始 ID，
    /// 不猜测其硬件或 QEMU 参数。
    public static func displayName(for profileID: String) -> String {
        LabNode(rawValue: profileID)?.displayName ?? profileID
    }

    /// 列表与选择器的唯一标签：登记名与 profile ID 不同时附上 ID，
    /// 避免多个同名登记（例如内置 Webserver 与历史 e2e 登记）无法区分。
    public static func displayLabel(for profileID: String, name: String? = nil) -> String {
        let display = (name?.isEmpty == false) ? name! : displayName(for: profileID)
        return display == profileID ? display : "\(display)（\(profileID)）"
    }

    /// 统一排序：保留课堂三节点的依赖顺序，其余已登记节点按 ID 稳定排列。
    public static func orderedProfileIDs<S: Sequence>(_ profileIDs: S) -> [String]
    where S.Element == String {
        let unique = Set(profileIDs)
        let known = required.map(\.rawValue).filter { unique.contains($0) }
        return known + unique.subtracting(Set(known)).sorted()
    }
}

/// .app 内固定布局（与 tools/ctflab_app.py 的常量保持一致；有守卫测试比对）。
public enum AppLayout {
    public static let cliRelativePath = "Contents/Resources/bin/ctflab-cli"

    public static func cliPath(bundleURL: URL) -> String {
        bundleURL.appendingPathComponent(cliRelativePath).path
    }
}

// MARK: - 分发目录报告

public struct DistEntry: Codable, Identifiable, Hashable {
    public let file: String
    public let profile: String?
    public let role: String?
    public let size: Int64?
    public let expectedSize: Int64?
    public let expectedSha256: String?
    public let status: String
    public let problem: String?
    public var id: String { file }

    enum CodingKeys: String, CodingKey {
        case file, profile, role, size, status, problem
        case expectedSize = "expected_size"
        case expectedSha256 = "expected_sha256"
    }

    public var statusText: String {
        switch status {
        case "ok": return "通过"
        case "missing": return "缺失"
        case "size-mismatch": return "大小不符"
        case "sha256-mismatch": return "哈希不符"
        default: return status
        }
    }

    public var isOK: Bool { status == "ok" }
}

public struct DistSummary: Codable, Hashable {
    public let total: Int
    public let ok: Int
    public let failed: Int
}

/// 内容包（schema 2 分发目录）在 `dist verify --json` 报告中的 `pack` 摘要。
/// 本机冲突状态来自 CLI 的只读预览；导入决定仍以 dist install 的实际校验为准。
public struct PackLocalStatus: Codable, Hashable {
    public let kind: String
    public let sha256: String?
}

public struct PackNode: Codable, Hashable {
    public let profile: String
    public let hasBase: Bool
    public let hasNvram: Bool
    public let name: String?
    public let architecture: String?
    public let firmware: String?
    public let memoryMb: Int?
    public let cpus: Int?
    public let local: PackLocalStatus?

    enum CodingKeys: String, CodingKey {
        case profile, name, architecture, firmware, cpus, local
        case hasBase = "has_base"
        case hasNvram = "has_nvram"
        case memoryMb = "memory_mb"
    }
}

public struct PackSummary: Codable, Hashable {
    public let id: String
    public let name: String
    public let version: String
    public let requiresRunner: String
    public let runner: String?
    public let runnerSatisfied: Bool?
    public let notes: [String]?
    public let nodes: [PackNode]
    public let docs: [String]?
    public let claims: [String]?
    public let claimsNote: String?

    enum CodingKeys: String, CodingKey {
        case id, name, version, notes, nodes, docs, claims
        case requiresRunner = "requires_runner"
        case runner = "runner"
        case runnerSatisfied = "runner_satisfied"
        case claimsNote = "claims_note"
    }
}

/// `dist install --json` 的结果（成功时打印；失败走通用错误通道）。
public struct PackInstallReport: Codable, Hashable {
    public let ok: Bool
    public let pack: PackSummary?
    public let installed: [String]?
    public let skippedIdentical: [String]?
    public let imported: [String]?
    public let docs: [String]?
    public let record: String?

    enum CodingKeys: String, CodingKey {
        case ok, pack, installed, imported, docs, record
        case skippedIdentical = "skipped_identical"
    }

    public static func parse(_ text: String) -> PackInstallReport? {
        // stdout 可能混有导入进度行；从后往前找能整体解码成 JSON 的花括号起点。
        var positions: [String.Index] = []
        var index = text.startIndex
        while let brace = text[index...].firstIndex(of: "{") {
            positions.append(brace)
            index = text.index(after: brace)
        }
        for brace in positions.reversed() {
            if let data = String(text[brace...]).data(using: .utf8),
               let report = try? JSONDecoder().decode(PackInstallReport.self, from: data) {
                return report
            }
        }
        return nil
    }
}

public struct DistReport: Codable, Hashable {
    public let ok: Bool
    public let entries: [DistEntry]
    public let problems: [String]
    public let summary: DistSummary?
    public let dir: String?
    public let manifest: String?
    /// schema 2 内容包摘要；旧分发目录（schema 1）为 nil，解码缺键时也为 nil。
    public var pack: PackSummary? = nil
}

// MARK: - 状态与健康检查

/// `status --json` 的启动阶段摘要（CLI 端 boot_stage_summary 的 UI 子集）。
/// 四阶段由 CLI 依据进程、健康检查与显示客户端日志推导；GUI 只展示，不自行判断。
public struct BootStage: Codable, Hashable {
    public let name: String
    public let ok: Bool?
    public let detail: String?
}

public struct BootDiagnosis: Codable, Hashable {
    public let message: String?
    public let failedChecks: [String]?
    public let logPath: String?
    public let clientLogPath: String?
    public let hint: String?

    enum CodingKeys: String, CodingKey {
        case message, hint
        case failedChecks = "failed_checks"
        case logPath = "log_path"
        case clientLogPath = "client_log_path"
    }
}

public struct BootSummary: Codable, Hashable {
    public let phase: String
    public let phaseLabel: String
    /// ready / booting / timeout；与阶段名分开，避免把整体超时误当第五阶段。
    public let overall: String
    public let elapsedSeconds: Int?
    public let readinessTimeoutSeconds: Int?
    public let stages: [BootStage]?
    public let diagnosis: BootDiagnosis?

    enum CodingKeys: String, CodingKey {
        case phase, overall, stages, diagnosis
        case phaseLabel = "phase_label"
        case elapsedSeconds = "elapsed_seconds"
        case readinessTimeoutSeconds = "readiness_timeout_seconds"
    }

    public var isTimedOut: Bool { overall == "timeout" }

    /// 表格单元显示：阶段标签 + 计时；超时附标记，诊断细节由提示列/日志承担。
    public var displayText: String {
        let elapsed = elapsedSeconds.map(String.init) ?? "?"
        let limit = readinessTimeoutSeconds.map(String.init) ?? "?"
        var text = "\(phaseLabel)（\(elapsed)s/\(limit)s）"
        if isTimedOut { text += " · 超时" }
        return text
    }
}

/// 显示客户端状态（与虚拟机状态分列展示，第 8 项）。
public struct SpiceClientStatus: Codable, Hashable {
    public let pid: Int?
    public let alive: Bool?
    public let displayReady: Bool?
    public var lastTransitionReason: String? = nil

    enum CodingKeys: String, CodingKey {
        case pid, alive
        case displayReady = "display_ready"
        case lastTransitionReason = "last_transition_reason"
    }

    /// 客户端列文案：已连接（display 通道就绪）/ 连接中（进程在、画面未就绪）/
    /// 未连接（进程不在）/ —（非 SPICE 节点）。
    public static func columnText(_ status: SpiceClientStatus?) -> String {
        guard let status else { return "—" }
        if status.alive == false { return "未连接" }
        if status.displayReady == true { return "已连接" }
        if status.alive == true { return "连接中" }
        return "未连接"
    }
}

public struct NodeResourceStatus: Codable, Hashable {
    public let memoryMB: Int?
    public let cpus: Int?
    public let cpuPercent: Double?
    public let rssMB: Double?
    public let acceleration: String?
    enum CodingKeys: String, CodingKey {
        case cpus, acceleration
        case memoryMB = "memory_mb"
        case cpuPercent = "cpu_percent"
        case rssMB = "rss_mb"
    }
}

public struct StatusProfile: Codable, Hashable, Identifiable {
    public let id: String
    public let name: String?
    /// 是否随包内置的课程配置；内置节点不能被移除登记。
    public let builtin: Bool?
    public let imported: Bool
    public let importState: String?
    /// 导入来源路径（image.json 记录）；扫描导入用它做幂等判断。
    public let sourcePath: String?
    public let running: Bool
    public let pid: Int?
    public let logPath: String?
    public let baseSHA256: String?
    public let stalePid: Int?
    public let boot: BootSummary?
    public let spiceClient: SpiceClientStatus?
    public var resources: NodeResourceStatus? = nil

    enum CodingKeys: String, CodingKey {
        case id, name, builtin, imported, running, pid, boot, resources
        case importState = "import_state"
        case sourcePath = "source_path"
        case logPath = "log_path"
        case baseSHA256 = "base_sha256"
        case stalePid = "stale_pid"
        case spiceClient = "spice_client"
    }
}

/// 仅解释已知进程/通道状态；不以显示就绪推断登录、解锁或可见窗口。
public enum DisplaySessionGuidance {
    public static func message(for profile: StatusProfile) -> String? {
        guard profile.running, let client = profile.spiceClient else { return nil }
        if client.alive == false {
            return "显示窗口未连接，但虚拟机仍在运行。点“重新打开显示窗口”即可恢复连接，无需再次启动或重启节点。"
        }
        if client.lastTransitionReason == "timeout" {
            return "上一次分辨率过渡超时，不等同虚拟机死机。可先诊断显示，再只重连显示；不会自动重启来宾。"
        }
        if client.alive == true && client.displayReady != true {
            return "正在连接或重建显示画面；虚拟机仍在运行，请先等待。长时间没有画面时可点“重连显示”，不会重启虚拟机。"
        }
        if client.displayReady == true {
            return "显示通道已连接，不代表已登录或已解锁。窗口被隐藏或最小化时，点“打开显示窗口”可找回；画面卡住可点“重连显示”。"
        }
        return "显示状态尚不明确；可打开显示窗口查看，不必重复启动节点。"
    }

    public static func actionTitle(for profile: StatusProfile) -> String {
        profile.spiceClient?.alive == false ? "重新打开显示窗口" : "打开显示窗口"
    }

    public static func canReconnect(_ profile: StatusProfile) -> Bool {
        profile.running && profile.spiceClient != nil
    }

    public static func loginHelp(for profile: StatusProfile) -> String? {
        guard ["kali-arm64", "kali"].contains(profile.id) else { return nil }
        return "冷启动、重启或注销后是登录界面；会话锁屏后通常只需密码解锁。“Kali User”是显示名称，不一定是登录用户名。关闭显示窗口不会自动关机；重新打开会回到原会话。请使用安装时设置的账号和密码。"
    }

    public static func sleepHelp(for profile: StatusProfile) -> String? {
        guard ["kali-arm64", "kali"].contains(profile.id) else { return nil }
        return "睡眠恢复尚未通过验收，请暂用“锁定屏幕”或正常关机。重新打开显示窗口只恢复显示连接，不能保证唤醒来宾；不要把睡眠黑屏当作已关机。"
    }
}

/// 节点统一运行状态（第 8 项）：由 status 字段推导，GUI 不做第二套探测。
public enum NodeOperationalState: String, CaseIterable {
    case notImported = "未导入"
    case baseMissing = "基盘失效"
    case stopped = "已停止"
    case booting = "启动中"
    case running = "运行中"
    case timedOut = "启动超时"
    case stale = "状态残留"

    public var isProblem: Bool { self == .timedOut || self == .stale || self == .baseMissing }

    /// 推导规则：残留 > 导入态 > 运行细分（超时 > 启动中 > 就绪）。
    public static func state(for profile: StatusProfile) -> NodeOperationalState {
        if profile.stalePid != nil { return .stale }
        if !profile.imported {
            return profile.importState == "missing-base" ? .baseMissing : .notImported
        }
        if !profile.running { return .stopped }
        switch profile.boot?.overall {
        case "timeout": return .timedOut
        case "ready": return .running
        default: return .booting
        }
    }

    /// 状态列详情：启动中附带当前阶段标签，其余附 PID 或恢复提示。
    public static func detailText(for profile: StatusProfile) -> String {
        switch state(for: profile) {
        case .booting:
            return profile.boot.map { "阶段：\($0.phaseLabel)" } ?? "等待阶段信息"
        case .running:
            return profile.pid.map { "PID \($0)" } ?? "PID?"
        case .timedOut:
            return "查看诊断与日志后可 stop（只影响该节点）"
        case .stale:
            return "进程已退出，状态文件待清理（stop --all）"
        case .baseMissing:
            return "导入登记失效：基盘被移动或删除"
        case .stopped, .notImported:
            return ""
        }
    }
}

/// 节点搜索（第 8 项）：匹配 profile ID、登记名或显示名，大小写不敏感；
/// 空查询匹配全部；分组与收藏由独立的本地管理元数据提供。
public enum NodeSearch {
    public static func matches(_ profile: StatusProfile, query: String) -> Bool {
        let trimmed = query.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return true }
        let haystacks = [profile.id,
                         profile.name ?? "",
                         LabNode.displayName(for: profile.id)]
        let needle = trimmed.lowercased()
        return haystacks.contains { $0.lowercased().contains(needle) }
    }

    public static func filter(_ profiles: [StatusProfile], query: String) -> [StatusProfile] {
        profiles.filter { matches($0, query: query) }
    }
}

public enum NodeStatusFilter: String, CaseIterable {
    case all = "全部状态", active = "正在运行", stopped = "已停止", problems = "需要处理"
    public func matches(_ node: StatusProfile) -> Bool {
        switch self {
        case .all: return true
        case .active: return node.running
        case .stopped: return node.imported && !node.running && node.stalePid == nil
        case .problems: return NodeOperationalState.state(for: node).isProblem
        }
    }
}

/// 管理元数据不修改 profile、镜像或网络，编码为独立状态目录作用域的本地偏好。
public struct NodeLibraryPreferences: Codable, Equatable {
    public var favorites: Set<String> = []
    public var groups: [String: String] = [:]
    public var lastUsed: [String: Date] = [:]
    public var courses: [NodeCourse] = []
    public init() {}

    public mutating func setGroup(_ value: String, for id: String) {
        let group = String(value.trimmingCharacters(in: .whitespacesAndNewlines).prefix(64))
        groups[id] = group.isEmpty ? nil : group
    }

    public func ordered(_ profiles: [StatusProfile], recentFirst: Bool) -> [StatusProfile] {
        profiles.sorted { left, right in
            if favorites.contains(left.id) != favorites.contains(right.id) {
                return favorites.contains(left.id)
            }
            if recentFirst {
                let a = lastUsed[left.id] ?? .distantPast
                let b = lastUsed[right.id] ?? .distantPast
                if a != b { return a > b }
            }
            return left.id < right.id
        }
    }
}

public struct NodeCourse: Codable, Equatable, Identifiable {
    public let id: String
    public let name: String
    public let profileIDs: [String]
    public init(name: String, profileIDs: [String], id: String = UUID().uuidString) {
        self.id = id
        self.name = String(name.trimmingCharacters(in: .whitespacesAndNewlines).prefix(64))
        self.profileIDs = LabNode.orderedProfileIDs(Array(Set(profileIDs)))
    }
}

public enum CourseLaunchRules {
    /// 全组合先校验，缺节点拒绝；已在运行节点不重复启动，失败不停止已有节点。
    public static func pending(_ course: NodeCourse, profiles: [StatusProfile]) throws -> [String] {
        guard !course.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !course.profileIDs.isEmpty else {
            throw NSError(domain: "CTFLab.Course", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "课程组合需要名称和至少一个节点。"])
        }
        var result: [String] = []
        for id in LabNode.orderedProfileIDs(Array(Set(course.profileIDs))) {
            guard let profile = profiles.first(where: { $0.id == id }), profile.imported else {
                throw NSError(domain: "CTFLab.Course", code: 2,
                              userInfo: [NSLocalizedDescriptionKey: "组合中的 \(id) 未导入或已被移除，请先修正组合。"])
            }
            if !profile.running { result.append(id) }
        }
        return result
    }
}

public struct StatusReport: Codable, Hashable {
    public let profiles: [StatusProfile]
    public let stateDir: String?

    enum CodingKeys: String, CodingKey {
        case profiles
        case stateDir = "state_dir"
    }
}

public struct HealthCheck: Codable, Hashable {
    public let name: String
    public let ok: Bool?
    public let detail: String?
}

public struct HealthReport: Codable, Hashable {
    public let profile: String
    public let ok: Bool
    /// 启动窗口内检查项可能仍为 null；CLI 以 pending 明确表达“尚未失败但尚未就绪”。
    public let pending: Bool?
    public let checks: [HealthCheck]

    public var isPending: Bool {
        pending == true || checks.contains { $0.ok == nil }
    }
}

// MARK: - 新镜像只读识别

/// `inspect --json` 的 UI 必需子集。候选硬件与置信度必须并列展示，不能把推测降格为事实。
public struct ImageCandidate: Codable, Hashable {
    public let architecture: String
    public let firmware: String
    public let machine: String
    public let memoryMB: Int
    public let cpus: Int
    public let diskBus: String
    public let diskController: String?
    public let networkAdapter: String

    enum CodingKeys: String, CodingKey {
        case architecture, firmware, machine, cpus
        case memoryMB = "memory_mb"
        case diskBus = "disk_bus"
        case diskController = "disk_controller"
        case networkAdapter = "network_adapter"
    }
}

public struct InspectionConfidence: Codable, Hashable {
    public let level: String
    public let reason: String
}

public struct InspectionConfidenceSet: Codable, Hashable {
    public let architecture: InspectionConfidence
    public let firmware: InspectionConfidence
    public let disk: InspectionConfidence
    public let network: InspectionConfidence
}

public struct ImageInspectionReport: Codable, Hashable {
    public let sourcePath: String
    public let format: String?
    public let virtualSize: Int64?
    public let sourceSHA256: String?
    public let candidate: ImageCandidate
    public let confidence: InspectionConfidenceSet
    public let warnings: [String]

    enum CodingKeys: String, CodingKey {
        case format, candidate, confidence, warnings
        case sourcePath = "source_path"
        case virtualSize = "virtual_size"
        case sourceSHA256 = "source_sha256"
    }
}

public enum ImageOnboardingRules {
    /// 同名登记只是 ID 冲突，不代表镜像已经导入；为新来源生成可编辑候选 ID。
    public static func availableProfileID(sourcePath: String, existingIDs: Set<String>) -> String {
        let base = suggestedProfileID(sourcePath: sourcePath)
        if !existingIDs.contains(base) { return base }
        var index = 2
        while true {
            let suffix = "-\(index)"
            let candidate = String(base.prefix(49 - suffix.count)) + suffix
            if !existingIDs.contains(candidate) { return candidate }
            index += 1
        }
    }

    public static func pendingImages(_ entries: [ImageLibraryEntry], nodes: [StatusProfile]) -> [ImageLibraryEntry] {
        let importedSources = Set(nodes.filter(\.imported).compactMap(\.sourcePath))
        return entries.filter { !importedSources.contains($0.path) }
    }
    /// 从文件名给出可编辑的安全 id；CLI 仍会做最终校验与排他写入。
    public static func suggestedProfileID(sourcePath: String) -> String {
        let name = URL(fileURLWithPath: sourcePath).deletingPathExtension().lastPathComponent.lowercased()
        let normalized = name.map { character in
            character.isASCII && (character.isLetter || character.isNumber) ? String(character) : "-"
        }.joined()
        let compact = normalized.split(separator: "-", omittingEmptySubsequences: true).joined(separator: "-")
        let trimmed = String(compact.prefix(49)).trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        return trimmed.isEmpty ? "x86-lab" : trimmed
    }

    public static func validProfileID(_ profileID: String) -> Bool {
        guard !profileID.isEmpty, profileID.count <= 49,
              profileID.first != "-", profileID.last != "-" else { return false }
        return profileID.allSatisfy {
            $0.isASCII && ($0.isLowercase || $0.isNumber || $0 == "-")
        }
    }
}

// MARK: - 镜像文件夹扫描

/// 镜像文件夹顶层发现的磁盘镜像（只登记，不识别、不导入）。
public struct ImageLibraryEntry: Identifiable, Hashable {
    public let fileName: String
    public let path: String
    public let sizeBytes: Int64?

    public var id: String { path }
}

/// 只读扫描镜像文件夹的顶层磁盘镜像。空文件夹是合法状态（返回空数组）；
/// 目录遍历失败同样返回空数组，由调用方决定如何提示。
public enum ImageFolderScanner {
    public static let supportedExtensions = ["qcow2", "ova", "vmdk", "vdi", "vhd", "vhdx", "img", "raw"]

    public static func scan(_ dir: String, fileManager: FileManager = .default) -> [ImageLibraryEntry] {
        guard !dir.isEmpty, let names = try? fileManager.contentsOfDirectory(atPath: dir) else {
            return []
        }
        let root = URL(fileURLWithPath: dir)
        return names
            .filter { supportedExtensions.contains(
                URL(fileURLWithPath: $0).pathExtension.lowercased()) }
            .sorted { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }
            .map { name in
                let path = root.appendingPathComponent(name).path
                let attributes = try? fileManager.attributesOfItem(atPath: path)
                let size = (attributes?[.size] as? NSNumber)?.int64Value
                return ImageLibraryEntry(fileName: name, path: path, sizeBytes: size)
            }
    }
}

// MARK: - 状态机

public enum GuiPhase: Equatable {
    case idle
    case verifying
    case verified
    case importing
    case imported
    case busy          // 启动/停止/检查等命令执行中
    case failed

    public var isBusy: Bool { self == .verifying || self == .importing || self == .busy }
}

public struct GuiState: Equatable {
    public var distDir: String?
    public var report: DistReport?
    public var phase: GuiPhase = .idle
    /// 所有集合都使用 profile ID，而非固定枚举：后续课程包的节点可被同一个管理器启动、
    /// 停止和重置，不需要为每台靶机重新编译 GUI。
    /// 当前已校验的分发清单或已创建的候选配置。内置 profile 只是“可识别的配置”，
    /// 不是已导入节点，因此初始值必须为空。
    public var configuredProfileIDs: Set<String> = []
    public var importedProfileIDs: Set<String> = []
    public var runningProfileIDs: Set<String> = []
    /// 图形入口一次只操作一个明确选中的节点，避免批量启动/停止的意外影响。
    public var selectedProfileID: String?
    public var healthyProfileIDs: Set<String> = []
    public var pendingHealthProfileIDs: Set<String> = []
    public var lastError: String?
    public var progressText: String = ""

    public init() {}

    public var verificationPassed: Bool { report?.ok == true }
    public var allImported: Bool { configuredProfileIDs.isSubset(of: importedProfileIDs) }
    public var anyRunning: Bool { !runningProfileIDs.isEmpty }
    public var canVerify: Bool { !(distDir ?? "").isEmpty && !phase.isBusy }
    public var canImport: Bool { verificationPassed && !anyRunning && !phase.isBusy }
    /// 启动只依赖状态目录里已导入的节点：镜像文件夹可以只是普通文件夹（可为空、
    /// 无分发清单），不要求先通过成套分发的校验。
    public var canStartSelected: Bool {
        guard let selectedProfileID else { return false }
        return importedProfileIDs.contains(selectedProfileID)
            && !runningProfileIDs.contains(selectedProfileID)
            && !phase.isBusy
    }
    public var canStart: Bool { canStartSelected }
    public var canCheckStatus: Bool { !phase.isBusy }
    public var canStopSelected: Bool {
        guard let selectedProfileID else { return false }
        return runningProfileIDs.contains(selectedProfileID) && !phase.isBusy
    }
    public var canStop: Bool { canStopSelected }
    public var canReset: Bool { !configuredProfileIDs.isEmpty && allImported && !anyRunning && !phase.isBusy }

    /// 导入按钮的进度文案（导入中显示第几个节点）。
    public func importProgressText(index: Int, total: Int, profileID: String) -> String {
        "正在导入 \(LabNode.displayName(for: profileID))（\(index + 1)/\(total)）…"
    }

    public var statusLine: String {
        if let lastError { return "失败：\(lastError)" }
        if phase.isBusy { return progressText.isEmpty ? "执行中…" : progressText }
        if anyRunning { return "实验环境运行中" }
        if verificationPassed && allImported && !configuredProfileIDs.isEmpty {
            return "实验环境已就绪（未运行）"
        }
        if verificationPassed { return "镜像文件夹已通过校验" }
        return "选择镜像文件夹，或直接启动已导入的节点"
    }
}

// MARK: - CLI 命令拼接

/// 分享只从已经显示的状态快照重新构建字段，不复制路径、标识、日志或自由文本。
public struct MacPublicDiagnostics: Identifiable {
    public let id = UUID()
    public let data: Data
    public let text: String

    public static func preview(_ profiles: [StatusProfile], version: String, machine: String) throws -> MacPublicDiagnostics {
        guard profiles.count <= 256 else { throw CocoaError(.fileReadTooLarge) }
        let validVersion = version.range(of: #"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}(?:-preview\.[0-9]{8})?$"#, options: .regularExpression) != nil
        let allowedMachines = ["arm64", "aarch64", "x86_64", "AMD64"]
        let phases = ["process", "guest-boot", "display", "network"]
        let nodes: [[String: String]] = profiles.enumerated().map { index, profile in
            let phase = profile.boot?.phase ?? "unknown"
            return ["node": "node-\(index + 1)",
                    "state": profile.stalePid != nil ? "unknown" : (profile.running ? "running" : "stopped"),
                    "boot_phase": phases.contains(phase) ? phase : "unknown"]
        }
        let value: [String: Any] = [
            "schema": 1, "kind": "share-preview", "scope": "sanitized-summary-only",
            "ctflab_version": validVersion ? version : "unknown",
            "host": ["system": "Darwin", "machine": allowedMachines.contains(machine) ? machine : "unknown"],
            "profiles": nodes, "observation": "displayed-snapshot", "may_be_stale": true,
            "omitted": ["raw-logs", "private-paths", "identifiers", "addresses", "process-ids", "environment", "free-text"],
            "uploaded": false
        ]
        var bytes = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .prettyPrinted])
        bytes.append(10)
        guard bytes.count <= 65536, let text = String(data: bytes, encoding: .utf8) else { throw CocoaError(.fileReadTooLarge) }
        return MacPublicDiagnostics(data: bytes, text: text)
    }

    /// 排他新建0600文件，只写预览持有的原字节；失败保留本次文件，不覆盖、重采集或上传。
    public func save(to url: URL) throws {
        guard url.isFileURL else { throw CocoaError(.fileWriteUnsupportedScheme) }
        let fd = Darwin.open(url.path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, S_IRUSR | S_IWUSR)
        guard fd >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close() }
        try handle.write(contentsOf: data)
        try handle.synchronize()
    }

    private init(data: Data, text: String) { self.data = data; self.text = text }
}

public enum CliAction: Equatable {
    case remoteClient(json: String)
    case scenarioClient(json: String)
    case genericClient(json: String)
    case distVerify(dir: String)
    case distInstall(dir: String)
    case importNode(node: LabNode, sourcePath: String, manifestPath: String)
    case run(nodes: [LabNode])
    case importProfile(profileID: String, sourcePath: String, manifestPath: String)
    case runProfiles(profileIDs: [String], clipboard: Bool, displayQuality: String? = nil,
                     fileTransfer: Bool = false, resourcePreset: String? = nil)
    case showDisplay(profileID: String)
    case reconnectDisplay(profileID: String)
    case diagnostics(path: String)
    case preflight(profileID: String, resourcePreset: String? = nil)
    case displayDiagnose(profileID: String)
    case updateStage(source: String, sha256: String)
    case updateSelect(slot: String)
    case updateRollback
    case updateLaunch
    case status
    case health(node: LabNode)
    case healthProfile(profileID: String)
    case stopAll
    case stopProfiles(profileIDs: [String])
    case resetNode(node: LabNode)
    case resetProfile(profileID: String)
    case deregisterProfile(profileID: String)
    case removeImage(profileID: String)
    case inspectImage(sourcePath: String)
    case onboardX86(sourcePath: String, profileID: String)
    case retryOnboard(sourcePath: String, profileID: String)
    /// 扫描自动导入：不指定架构，由 CLI 的 inspect 证据推断（x86_64 与 aarch64 都支持）。
    case onboardAuto(sourcePath: String, profileID: String)
    case probeProfile(profileID: String, matrix: Bool)
    case applyMatrixCandidate(profileID: String, reportPath: String)
    case reviewMatrixCandidate(profileID: String, reportPath: String, attempt: Int)
    case snapshot(profileID: String, operation: String, name: String? = nil)
    case backupReset(profileID: String, name: String = RecoveryRules.checkpointName())
    case scenarioStatus
    case scenarioStop
    case scenarioRecover(closeReset: Bool, releaseOrphan: Bool)

    /// 参数数组：不做 shell 拼接，路径（含空格）保持为单个参数。
    public func arguments(stateDir: String? = nil) -> [String] {
        var args: [String] = []
        if let stateDir, !stateDir.isEmpty {
            args += ["--state-dir", stateDir]
        }
        switch self {
        case .remoteClient:
            args += ["remote-client"]
        case .scenarioClient:
            args += ["scenario-client"]
        case .genericClient:
            args += ["generic-client"]
        case .distVerify(let dir):
            // --conflicts 提供内容包冲突预览（只读）；schema 1 目录不受影响。
            args += ["dist", "verify", "--dir", dir, "--json", "--conflicts"]
        case .distInstall(let dir):
            // 内容包一次性安装：校验→装配置→导基盘→复制说明；与 import 共用取消通道。
            args += ["dist", "install", "--dir", dir, "--json"]
        case .importNode(let node, let sourcePath, let manifestPath):
            // 与 CLI 一致：基盘是位置参数，--manifest 负责哈希校验并配对同目录的 NVRAM 模板。
            args += ["import", node.rawValue, sourcePath, "--manifest", manifestPath]
        case .run(let nodes):
            args += ["run"] + LabNode.orderedProfileIDs(nodes.map(\.rawValue))
        case .importProfile(let profileID, let sourcePath, let manifestPath):
            args += ["import", profileID, sourcePath, "--manifest", manifestPath]
        case .runProfiles(let profileIDs, let clipboard, let displayQuality, let fileTransfer, let resourcePreset):
            args += ["run"] + LabNode.orderedProfileIDs(profileIDs)
            if clipboard {
                // 文本剪贴板共享是显式授权项：只有用户打开开关才传给 CLI。
                args += ["--clipboard"]
            }
            if let displayQuality {
                args += ["--display-quality", displayQuality]
            }
            if fileTransfer { args += ["--file-transfer"] }
            if let resourcePreset { args += ["--resource-preset", resourcePreset] }
        case .showDisplay(let profileID):
            args += ["show", profileID]
        case .reconnectDisplay(let profileID):
            args += ["show", profileID, "--reconnect"]
        case .diagnostics(let path):
            args += ["doctor", "--diagnostics", path]
        case .preflight(let profileID, let preset):
            args += ["preflight", profileID]
            if let preset { args += ["--resource-preset", preset] }
        case .displayDiagnose(let profileID):
            args += ["display-diagnose", profileID]
        case .updateStage(let source, let sha256):
            args += ["update", "stage", source, "--sha256", sha256, "--allow-local-candidate"]
        case .updateSelect(let slot): args += ["update", "select", slot]
        case .updateRollback: args += ["update", "rollback"]
        case .updateLaunch: args += ["update", "launch"]
        case .status:
            args += ["status", "--json"]
        case .snapshot(let profileID, let operation, let name):
            args += ["snapshot", operation, profileID]
            if let name { args.append(name) }
            if operation == "list" || operation == "list-backups" { args.append("--json") }
        case .backupReset(let profileID, let name):
            args += ["reset", profileID, "--backup", name]
        case .health(let node):
            args += ["health", node.rawValue, "--json"]
        case .healthProfile(let profileID):
            args += ["health", profileID, "--json"]
        case .stopAll:
            args += ["stop", "--all"]
        case .stopProfiles(let profileIDs):
            args += ["stop"] + LabNode.orderedProfileIDs(profileIDs)
        case .resetNode(let node):
            args += ["reset", node.rawValue]
        case .resetProfile(let profileID):
            args += ["reset", profileID]
        case .deregisterProfile(let profileID):
            args += ["deregister", profileID]
        case .removeImage(let profileID):
            args += ["remove", profileID]
        case .inspectImage(let sourcePath):
            // 向导只展示硬件候选；正式导入独立计算并登记来源哈希。
            args += ["inspect", sourcePath, "--json", "--no-hash"]
        case .onboardX86(let sourcePath, let profileID):
            // x86 向导只明确架构；固件、磁盘控制器、网卡仍由 inspect 证据生成候选，
            // 不在 GUI 中拼接任意 QEMU 原始参数。
            args += ["onboard", sourcePath, "--id", profileID, "--architecture", "x86_64"]
        case .onboardAuto(let sourcePath, let profileID):
            // 扫描自动导入：不指定架构，由 CLI 的 inspect 证据推断（x86_64/aarch64 均可）。
            args += ["onboard", sourcePath, "--id", profileID]
        case .retryOnboard(let sourcePath, let profileID):
            args += ["onboard", sourcePath, "--id", profileID, "--resume"]
        case .probeProfile(let profileID, let matrix):
            args += ["probe", profileID]
            if matrix { args += ["--matrix"] }
        case .applyMatrixCandidate(let profileID, let reportPath):
            args += ["probe", profileID, "--apply-matrix-report", reportPath, "--confirm-apply"]
        case .reviewMatrixCandidate(let profileID, let reportPath, let attempt):
            args += ["probe", profileID, "--apply-matrix-report", reportPath,
                     "--review-attempt", String(attempt), "--confirm-apply"]
        case .scenarioStatus:
            // 场景状态与单机 profile 状态分属不同入口：独立状态根，只读查询。
            args += ["scenario", "status", "--json"]
        case .scenarioStop:
            args += ["scenario", "stop"]
        case .scenarioRecover(let closeReset, let releaseOrphan):
            args += ["scenario", "recover"]
            if closeReset { args.append("--close-reset") }
            if releaseOrphan { args.append("--release-orphan") }
        }
        return args
    }

    public var displayCommand: String {
        if case .remoteClient = self { return "ctflab remote-client（私有请求，内容不写入日志）" }
        if case .scenarioClient = self { return "ctflab scenario-client（私有请求，内容不写入日志）" }
        if case .genericClient = self { return "ctflab generic-client（私有请求，内容不写入日志）" }
        return (["ctflab"] + arguments()).joined(separator: " ")
    }

    public var privateRequest: Data? {
        if case .remoteClient(let json) = self { return json.data(using: .utf8) }
        if case .scenarioClient(let json) = self { return json.data(using: .utf8) }
        if case .genericClient(let json) = self { return json.data(using: .utf8) }
        return nil
    }

    public var controlsImport: Bool {
        switch self {
        case .importNode, .importProfile, .onboardX86, .onboardAuto, .retryOnboard, .distInstall: return true
        default: return false
        }
    }

    /// `dist verify` 失败时仍打印结构化 JSON；GUI 需要原文解码出红色校验行与具体问题，
    /// 不能套用“命令失败 + 尾部截断”的通用文案（那会破坏 JSON 解码）。
    public var preservesRawOutputOnFailure: Bool {
        if case .distVerify = self { return true }
        if case .remoteClient = self { return true }
        if case .scenarioClient = self { return true }
        if case .genericClient = self { return true }
        return false
    }
}

/// 校验结果到导入动作的决策门：失败一律中止，包走单次安装，旧清单逐节点导入。
/// 独立可测：verify 失败/输出不可解码时绝不能回退到普通镜像 onboard 路径。
public enum DistImportGate {
    public enum Decision: Equatable {
        case installPack
        case importMissing
        case abort
    }

    public static func decide(report: DistReport?, manifestExists: Bool) -> Decision {
        guard let report, report.ok, manifestExists else { return .abort }
        if report.pack != nil { return .installPack }
        return .importMissing
    }

    /// 包节点冲突预览文案：按本机候选与包内配置的实际哈希区分“一致将跳过”与
    /// “不同将拒绝覆盖”，避免内容一致时仍显示误导性的冲突警告。
    public static func conflictNote(local: PackLocalStatus?, profilePackSha256: String?) -> String? {
        switch local?.kind {
        case "builtin":
            return "与内置课程同名，导入会被拒绝"
        case "user":
            if let pack = profilePackSha256, local?.sha256 == pack {
                return "同名候选内容一致，重复导入将跳过"
            }
            return "已有同名候选配置；内容不同将拒绝覆盖"
        default:
            return nil
        }
    }
}

/// 从人读 CLI 输出提取“矩阵成功 + 报告路径”这一最小事实。
/// 失败矩阵也会打印报告路径，因此只有同时出现成功结论时才允许 GUI 显示固化按钮。
public struct MatrixProbeResult: Equatable {
    public let summary: String
    public let reportPath: String
    public let reviewAttempt: Int?
    public let screenshotPath: String?

    public static func parse(_ output: String) -> MatrixProbeResult? {
        var summary: String?
        var reportPath: String?
        var reviewAttempt: Int?
        var screenshotPath: String?
        for rawLine in output.components(separatedBy: .newlines) {
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            if line.hasPrefix("矩阵结论："), line.contains(" 可以启动（") {
                summary = line
            } else if line.hasPrefix("矩阵待人工复核：") {
                let value = line.dropFirst("矩阵待人工复核：".count).split(separator: "（").first
                if let value, let index = Int(value), index > 0 {
                    reviewAttempt = index
                    summary = line
                }
            } else if line.hasPrefix("复核截图：") {
                let value = String(line.dropFirst("复核截图：".count)).trimmingCharacters(in: .whitespaces)
                if value.hasPrefix("/") { screenshotPath = value }
            } else if line.hasPrefix("矩阵报告：") {
                let value = String(line.dropFirst("矩阵报告：".count))
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                if value.hasPrefix("/") { reportPath = value }
            }
        }
        guard let summary, let reportPath else { return nil }
        if reviewAttempt != nil && screenshotPath == nil { return nil }
        return MatrixProbeResult(summary: summary, reportPath: reportPath,
                                 reviewAttempt: reviewAttempt, screenshotPath: screenshotPath)
    }
}

/// CLI 独立进度行；未收到完整行时等待，避免管道拆分 JSON 被误读。
public struct ImportProgress: Decodable, Sendable {
    public let stage: String
    public let done: Int64?
    public let total: Int64?
    public let elapsed_seconds: Double
    public let cancellable: Bool

    public static func latest(in output: String) -> ImportProgress? {
        let lines = output.components(separatedBy: "\n").dropLast()
        let prefix = "CTFLAB_IMPORT_PROGRESS "
        for line in lines.reversed() where line.hasPrefix(prefix) {
            if let data = String(line.dropFirst(prefix.count)).data(using: .utf8),
               let progress = try? JSONDecoder().decode(ImportProgress.self, from: data) {
                return progress
            }
        }
        return nil
    }

    public var label: String {
        let percent = total.flatMap { total in
            total > 0 ? done.map { " \(Int(min(100.0, max(0.0, Double($0) / Double(total) * 100))))%" } : nil
        } ?? ""
        let elapsed = elapsed_seconds.isFinite && elapsed_seconds >= 0 && elapsed_seconds < Double(Int.max)
            ? "\(Int(elapsed_seconds)) 秒" : "耗时未知"
        return "\(stage)\(percent) · \(elapsed)"
    }
}

/// 分发目录里的清单与四类关键文件。
public struct DistributionLayout {
    public let dir: String
    public init(dir: String) { self.dir = dir }

    public var manifestPath: String {
        URL(fileURLWithPath: dir).appendingPathComponent("DISTRIBUTION.json").path
    }

    public var sumsPath: String {
        URL(fileURLWithPath: dir).appendingPathComponent("SHA256SUMS").path
    }

    /// 关键文件是否齐全（DISTRIBUTION.json、SHA256SUMS、三个基盘与 Kali NVRAM），
    /// 只在磁盘上做存在性检查；权威判定仍以 `dist verify` 为准。
    public func detect() -> (missing: [String], found: [String]) {
        var missing: [String] = []
        var found: [String] = []
        for name in ["DISTRIBUTION.json", "SHA256SUMS"] {
            let path = URL(fileURLWithPath: dir).appendingPathComponent(name).path
            FileManager.default.fileExists(atPath: path) ? found.append(name) : missing.append(name)
        }
        for path in expectedPayloadPaths() {
            FileManager.default.fileExists(atPath: path)
                ? found.append(URL(fileURLWithPath: path).lastPathComponent)
                : missing.append(URL(fileURLWithPath: path).lastPathComponent)
        }
        return (missing, found)
    }

    /// 从清单解析出的载荷文件名（无法解析时退化为空数组，由 `dist verify` 报错）。
    public func expectedPayloadPaths() -> [String] {
        manifestEntries().compactMap { $0["file"] as? String }.map {
            pathInsideDistribution($0)
        }.compactMap { $0 }
    }

    /// 只接纳 role=base 的 profile；NVRAM 等附属文件不会生成重复节点。
    public func baseProfileIDs() -> [String] {
        LabNode.orderedProfileIDs(manifestEntries().compactMap { entry in
            guard (entry["role"] as? String) == "base",
                  let profile = entry["profile"] as? String,
                  !profile.isEmpty,
                  let file = entry["file"] as? String else {
                return nil
            }
            return pathInsideDistribution(file) == nil ? nil : profile
        })
    }

    private func manifestEntries() -> [[String: Any]] {
        guard let data = FileManager.default.contents(atPath: manifestPath),
              let manifest = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let entries = manifest["entries"] as? [[String: Any]] else {
            return []
        }
        return entries
    }

    /// 某个节点在分发目录里的基盘文件路径（role = base）；找不到返回 nil。
    public func basePath(for node: LabNode) -> String? {
        basePath(forProfileID: node.rawValue)
    }

    /// 后续 profile 与首批三节点共用同一条白名单路径校验。
    public func basePath(forProfileID profileID: String) -> String? {
        let match = manifestEntries().first { entry in
            (entry["profile"] as? String) == profileID
                && (entry["role"] as? String) == "base"
                && (entry["file"] as? String) != nil
        }
        guard let file = match?["file"] as? String else { return nil }
        return pathInsideDistribution(file)
    }

    /// 清单是外部输入：基盘只能落在用户选中的分发目录内，拒绝绝对路径和 `..` 越界。
    private func pathInsideDistribution(_ file: String) -> String? {
        guard !file.isEmpty, !file.hasPrefix("/") else { return nil }
        let root = URL(fileURLWithPath: dir).standardizedFileURL.path
        let candidate = URL(fileURLWithPath: file, relativeTo: URL(fileURLWithPath: dir))
            .standardizedFileURL.path
        let rootPrefix = root.hasSuffix("/") ? root : root + "/"
        guard candidate.hasPrefix(rootPrefix) else { return nil }
        return candidate
    }
}

// MARK: - 解析与错误处理

public enum GuiParsing {
    public static func decodeDistReport(_ text: String) -> DistReport? {
        guard let data = text.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(DistReport.self, from: data)
    }

    public static func decodeStatus(_ text: String) -> StatusReport? {
        guard let data = text.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(StatusReport.self, from: data)
    }

    public static func decodeHealth(_ text: String) -> HealthReport? {
        guard let data = text.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(HealthReport.self, from: data)
    }

    public static func decodeInspection(_ text: String) -> ImageInspectionReport? {
        guard let data = text.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(ImageInspectionReport.self, from: data)
    }
}

public enum GuiMessages {
    public static let resetConfirmationTitle = "确认重置实验环境？"
    public static let resetConfirmationBody =
        "重置会删除各节点的运行 overlay，overlay 中的实验改动（安装的软件、产生的文件、"
        + "被攻击后的状态）会全部丢失；基础镜像不受影响。是否继续？"
    public static let resetConfirmButton = "重置并丢弃改动"
    public static let resetCancelButton = "取消"
    public static let verifyFailedBanner = "分发目录未通过校验：导入与启动已禁用，请先修复不一致项。"
    public static let importAllFailedPrefix = "导入失败"
    public static let notVerifiedPrefix = "尚未校验分发目录"

    /// 把 CLI 输出压缩成可复制的一段错误文本（保留最后若干行）。
    public static func failureMessage(action: String, exitCode: Int32, output: String,
                                      tailLines: Int = 12) -> String {
        let lines = output.split(separator: "\n", omittingEmptySubsequences: false).suffix(tailLines)
        let tail = lines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        return "\(action)失败（退出码 \(exitCode)）\n\(tail)"
    }
}

/// 重置门禁：未确认时不允许产生任何 reset 命令（GUI 必须先弹确认框）。
public enum ResetGate {
    public static func plan(state: GuiState, confirmed: Bool) -> [CliAction]? {
        guard confirmed, !state.configuredProfileIDs.isEmpty, state.allImported else { return nil }
        return LabNode.orderedProfileIDs(state.configuredProfileIDs).map {
            .resetProfile(profileID: $0)
        }
    }
}


// MARK: - Wintermute 场景状态（独立状态根；不并入单机 profile 状态机）

/// `ctflab scenario status --json` 的报告数组元素。
/// 字段与 CLI 输出一一对应；state 文案不把进程存活说成题目可用。
public struct ScenarioReport: Codable, Equatable {
    public struct ActiveGeneration: Codable, Equatable {
        public let generation: Int
        public let descriptor: String
    }

    public struct ResetState: Codable, Equatable {
        public let state: String
        public let generation: Int?
        public let problem: String?
    }

    public struct RecoverySection: Codable, Equatable {
        public let state: String
        public let live: [String]?
        public let absent: [String]?
        public let unknown: [String]?
        public let problem: String?
    }

    public let instance_uuid: String
    public let state_root: String
    public let active: ActiveGeneration?
    public let reset: ResetState?
    public let services: RecoverySection?
    public let nodes: RecoverySection?
    public let reservations: [ReservationInfo]?
    public let next: [String]?

    public struct ReservationInfo: Codable, Equatable {
        public let token: String
        public let generation: Int
        public let ports: [Int]
    }

    public static func decode(_ text: String) -> [ScenarioReport]? {
        guard let data = text.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode([ScenarioReport].self, from: data)
    }

    /// 单一实例的诚实概括：待恢复 > 仍存活 > 已停止 > 未初始化。
    public var summaryState: String {
        let sections = [services, nodes].compactMap { $0 }
        if sections.contains(where: { $0.state == "recovery-required" }) { return "待恢复" }
        if sections.contains(where: { !($0.live ?? []).isEmpty }) { return "仍存活（进程已核验）" }
        if sections.contains(where: { $0.state == "recovery-required" }) { return "待恢复" }
        if !sections.isEmpty && sections.allSatisfy({ $0.state == "stopped-observed" }) { return "已停止" }
        if active != nil { return "已准备" }
        return "未初始化"
    }

    public var stateDetail: String {
        var parts: [String] = []
        if let active {
            parts.append("代次 \(active.generation)（\(active.descriptor)）")
        } else {
            parts.append("活动代次未初始化")
        }
        if let services { parts.append("双网：\(services.state)") }
        if let nodes { parts.append("节点：\(nodes.state)") }
        if let unknown = services?.unknown, !unknown.isEmpty { parts.append("服务不明：\(unknown.joined(separator: ", "))") }
        if let unknown = nodes?.unknown, !unknown.isEmpty { parts.append("节点不明：\(unknown.joined(separator: ", "))") }
        return parts.joined(separator: "；")
    }
}

// MARK: - Mac原生远程工作区（共享受限Runner，未知不重发）
public indirect enum MacRemoteJSON: Codable, Equatable, Sendable {
    case object([String: MacRemoteJSON]), array([MacRemoteJSON]), string(String), number(Double), bool(Bool), null
    public init(from decoder: Decoder) throws {
        let box = try decoder.singleValueContainer()
        if box.decodeNil() { self = .null }
        else if let v = try? box.decode(Bool.self) { self = .bool(v) }
        else if let v = try? box.decode(String.self) { self = .string(v) }
        else if let v = try? box.decode([String: MacRemoteJSON].self) { self = .object(v) }
        else if let v = try? box.decode([MacRemoteJSON].self) { self = .array(v) }
        else { self = .number(try box.decode(Double.self)) }
    }
    public func encode(to encoder: Encoder) throws {
        var box = encoder.singleValueContainer()
        switch self {
        case .object(let v): try box.encode(v)
        case .array(let v): try box.encode(v)
        case .string(let v): try box.encode(v)
        case .number(let v): try box.encode(v)
        case .bool(let v): try box.encode(v)
        case .null: try box.encodeNil()
        }
    }
    public subscript(_ key: String) -> MacRemoteJSON { if case .object(let v) = self { return v[key] ?? .null }; return .null }
    public var text: String? { if case .string(let v) = self { return v }; return nil }
    public var flag: Bool? { if case .bool(let v) = self { return v }; return nil }
    public var items: [MacRemoteJSON] { if case .array(let v) = self { return v }; return [] }
    public var integer: Int? {
        if case .number(let v) = self, v.isFinite, v >= 0, v <= 9_007_199_254_740_991, v.rounded() == v { return Int(v) }; return nil
    }
    public static func decode(_ text: String) throws -> MacRemoteJSON {
        guard let bytes = text.data(using: .utf8), bytes.count <= 4 * 1024 * 1024 else { throw MacRemoteError.invalid }
        return try JSONDecoder().decode(Self.self, from: bytes)
    }
    public func encoded() throws -> String {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(self)
        guard data.count <= 65536, let text = String(data: data, encoding: .utf8) else { throw MacRemoteError.invalid }
        return text
    }
}
public enum MacRemoteError: Error { case invalid }
public struct MacSavedTarget: Identifiable, Equatable {
    public let id: String, label: String, target: String, server: String
    public init(_ value: MacRemoteJSON) throws {
        guard let id = value["id"].text, MacRemoteRules.uuid(id), let label = value["label"].text,
              !label.isEmpty, label.count <= 96, let target = value["target"].text, MacRemoteRules.digest(target),
              let server = value["server_uuid"].text, MacRemoteRules.uuid(server) else { throw MacRemoteError.invalid }
        self.id = id; self.label = label; self.target = target; self.server = server
    }
}
public struct MacRemoteContext: Equatable {
    public let saved: MacSavedTarget
    public let instances: [String]
    public let leases: Bool
    public let display: Bool, assets: Bool, evidence: Bool
    public let role: String, courses: Bool, audit: Bool
    public init(saved: MacSavedTarget, reply: MacRemoteJSON) throws {
        let value = reply["result"]
        guard reply["error"] == .null, reply["target"].text == saved.target,
              value["server_uuid"].text == saved.server,
              ["student", "teacher", "administrator"].contains(value["role"].text ?? ""),
              let leases = value["resource_leases"].flag,
              case .array(let rows) = value["instances"], rows.count <= 1024 else { throw MacRemoteError.invalid }
        let instances = rows.compactMap(\.text)
        guard instances.count == rows.count, Set(instances).count == rows.count, instances.allSatisfy(MacRemoteRules.uuid) else { throw MacRemoteError.invalid }
        self.saved = saved; self.instances = instances; self.leases = leases
        self.display = value["display_available"].flag == true
        self.assets = value["asset_upload"].flag == true
        self.evidence = value["evidence_available"].flag == true
        self.role = value["role"].text ?? "student"
        self.courses = value["course_management"].flag == true && ["teacher", "administrator"].contains(self.role)
        self.audit = value["audit_management"].flag == true && self.role == "administrator"
    }
}
public enum MacRemoteRules {
    public static func uuid(_ value: String) -> Bool { UUID(uuidString: value)?.uuidString.lowercased() == value }
    public static func digest(_ value: String) -> Bool { value.count == 64 && value.allSatisfy { "0123456789abcdef".contains($0) } }
    public static func administration(_ action: String, context: MacRemoteContext, values: [String: MacRemoteJSON]) throws -> MacRemoteJSON {
        var fields: Set<String> = []
        if action.hasPrefix("course-") {
            guard context.courses else { throw MacRemoteError.invalid }
            if action != "course-list" {
                guard ["course-preview", "course-provision"].contains(action), let offer = values["offer_id"]?.text,
                      offer.range(of: "^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$", options: .regularExpression) != nil,
                      let instance = values["instance_uuid"]?.text, context.instances.contains(instance) else { throw MacRemoteError.invalid }
                fields = ["offer_id", "instance_uuid"]
                if action == "course-provision" { fields.insert("mapping_sha256"); guard digest(values["mapping_sha256"]?.text ?? "") else { throw MacRemoteError.invalid } }
            }
        } else {
            guard context.audit else { throw MacRemoteError.invalid }
            if action == "audit-review" {
                fields = ["after", "limit", "checkpoint"]
                guard let after = values["after"]?.integer, after >= 0, let limit = values["limit"]?.integer, (1...100).contains(limit) else { throw MacRemoteError.invalid }
                if let checkpoint = values["checkpoint"], checkpoint != .null {
                    guard case .object(let c) = checkpoint, Set(c.keys) == ["seq", "sha256"], let seq = c["seq"]?.integer,
                          seq >= 0, digest(c["sha256"]?.text ?? "") else { throw MacRemoteError.invalid }
                }
            } else {
                guard ["audit-settlement-preview", "audit-settle"].contains(action), uuid(values["attempt_id"]?.text ?? "") else { throw MacRemoteError.invalid }
                fields = ["attempt_id"]
                if action == "audit-settle" { fields.insert("review_sha256"); guard digest(values["review_sha256"]?.text ?? "") else { throw MacRemoteError.invalid } }
            }
        }
        guard Set(values.keys) == fields else { throw MacRemoteError.invalid }
        var payload = values; payload["action"] = .string(action); payload["target"] = .string(context.saved.target)
        return .object(payload)
    }
    public static func administrationResult(_ reply: MacRemoteJSON, payload: MacRemoteJSON, context: MacRemoteContext) throws -> MacRemoteJSON {
        guard reply["error"] == .null, reply["target"].text == context.saved.target, case .object = reply["result"] else { throw MacRemoteError.invalid }
        let result = reply["result"], action = payload["action"].text ?? ""
        if ["course-preview", "course-provision"].contains(action) {
            guard result["instance_uuid"] == payload["instance_uuid"], digest(result["mapping_sha256"].text ?? ""),
                  action != "course-provision" || result["mapping_sha256"] == payload["mapping_sha256"] else { throw MacRemoteError.invalid }
        }
        if ["audit-settlement-preview", "audit-settle"].contains(action) {
            guard result["attempt_id"] == payload["attempt_id"], result["original_worker_result"].text == "unknown",
                  result["vm_observed"].flag == false, result["automatic_replay"].flag == false else { throw MacRemoteError.invalid }
        }
        return result
    }
    public static func activeLease(_ status: MacRemoteJSON, selected: String, instance: String) -> Bool {
        guard uuid(selected), uuid(instance), case .array(let rows) = status["leases"] else { return false }
        return rows.contains { $0["lease_id"].text == selected && $0["instance_uuid"].text == instance
            && $0["state"].text == "active" && $0["time_state"].text == "active" }
    }
    public static func overview(_ reply: MacRemoteJSON, context: MacRemoteContext, instance: String, previous: MacRemoteJSON) throws -> MacRemoteJSON {
        let next = reply["result"], status = next["status"]
        guard context.instances.contains(instance), reply["target"].text == context.saved.target, reply["error"] == .null,
              next["instance_uuid"].text == instance, status["instance_uuid"].text == instance,
              let generation = next["generation"].integer else { throw MacRemoteError.invalid }
        let initial = generation == 0 && status["state"].text == "unknown" && status["generation"] == .null && status["state_revision"] == .null
        guard initial || status["state_revision"].integer != nil else { throw MacRemoteError.invalid }
        if previous["instance_uuid"].text == instance, let old = previous["status"]["state_revision"].integer {
            if initial || old > (status["state_revision"].integer ?? -1) { return previous }
        }
        return next
    }
    public static func allowed(_ op: String, view: MacRemoteJSON, context: MacRemoteContext?, instance: String, lease: String, busy: Bool, pending: Bool) -> Bool {
        guard !busy, !pending, let context, context.instances.contains(instance), view["instance_uuid"].text == instance else { return false }
        let state = view["status"]["state"].text ?? ""
        if op == "cancel" { return uuid(view["status"]["operation_id"].text ?? "") && ["accepted", "unknown"].contains(view["status"]["result"].text ?? "") }
        if view["status"]["result"].text == "accepted" || view["execution"]["identity"].text == "running" { return false }
        if context.leases && !["stop", "recover"].contains(op) && !uuid(lease) { return false }
        switch op {
        case "prepare": return view["generation"].integer == 0 && state == "unknown"
        case "start", "reset": return ["prepared", "stopped"].contains(state)
        case "stop": return ["process-running", "guest-ready", "service-ready", "recovery-required"].contains(state)
        case "recover": return (view["generation"].integer ?? 0) > 0
        default: return false
        }
    }
    public static func operation(_ op: String, view: MacRemoteJSON, context: MacRemoteContext, instance: String, lease: String) throws -> MacRemoteJSON {
        guard allowed(op, view: view, context: context, instance: instance, lease: lease, busy: false, pending: false) else { throw MacRemoteError.invalid }
        let params: [String: MacRemoteJSON]
        switch op {
        case "prepare": params = ["course_id": .string("host"), "baseline_id": .string("host")]
        case "start": params = ["display": .string("headless"), "allow_emulation": .bool(false)]
        case "reset": params = ["baseline_id": .string("host")]
        case "cancel": params = ["operation_id": view["status"]["operation_id"]]
        default: params = [:]
        }
        let request: [String: MacRemoteJSON] = ["protocol": .string("ctflab-local"), "version": .number(1),
            "request_id": .string(UUID().uuidString.lowercased()), "idempotency_key": .string(UUID().uuidString.lowercased()),
            "operation": .string(op), "instance_uuid": .string(instance), "parameters": .object(params),
            "expected_generation": op == "prepare" ? .null : view["status"]["generation"],
            "expected_state_revision": op == "prepare" ? .null : view["status"]["state_revision"]]
        var payload: [String: MacRemoteJSON] = ["action": .string("submit"), "target": .string(context.saved.target),
            "instance_uuid": .string(instance), "request": .object(request)]
        if uuid(lease) { payload["lease_id"] = .string(lease) }
        return .object(payload)
    }
    public static func lease(_ action: String, status: MacRemoteJSON, context: MacRemoteContext, instance: String, selected: String, ttl: Int, consent: Bool) throws -> MacRemoteJSON {
        guard context.leases, context.instances.contains(instance), status["owner_actions"].flag == true,
              let maximum = status["max_ttl_seconds"].integer, maximum >= 10, maximum <= 86400,
              case .array(let rows) = status["leases"] else { throw MacRemoteError.invalid }
        let row = rows.first { $0["lease_id"].text == selected } ?? .null
        var payload: [String: MacRemoteJSON] = ["action": .string(action), "target": .string(context.saved.target), "instance_uuid": .string(instance)]
        if action == "lease-acquire" {
            let policy = status["expiry_action"].text ?? ""
            guard ["notify", "request-stop"].contains(policy), !rows.contains(where: { $0["state"].text != "released" }), policy != "request-stop" || consent else { throw MacRemoteError.invalid }
            payload["lease_id"] = .string(UUID().uuidString.lowercased()); payload["expiry_action"] = .string(policy)
        } else {
            guard uuid(selected), row != .null, row["state"].text != "released" else { throw MacRemoteError.invalid }
            payload["lease_id"] = .string(selected)
            if action == "lease-renew" {
                guard row["state"].text == "active", row["time_state"].text == "active" else { throw MacRemoteError.invalid }
                payload["renewal_id"] = .string(UUID().uuidString.lowercased())
            } else if action != "lease-release" { throw MacRemoteError.invalid }
        }
        if action != "lease-release" { guard ttl >= 10, ttl <= maximum else { throw MacRemoteError.invalid }; payload["ttl_seconds"] = .number(Double(ttl)) }
        return .object(payload)
    }
}

/// 原生拓扑草稿只编辑值副本；完整清单、差异及后端支持仍由Python核验。
public enum MacGraphDraft {
    private static func object(_ value: MacRemoteJSON) throws -> [String: MacRemoteJSON] {
        guard case .object(let result) = value else { throw MacRemoteError.invalid }; return result
    }
    private static func identifier(_ value: String) throws {
        guard value.range(of: "^[a-z][a-z0-9-]{0,47}$", options: .regularExpression) != nil else { throw MacRemoteError.invalid }
    }
    public static func keys(_ value: MacRemoteJSON) -> [String] { if case .object(let items) = value { return items.keys.sorted() }; return [] }
    public static func checked(_ value: MacRemoteJSON) throws -> MacRemoteJSON {
        guard value["schema"].integer == 2, try value.encoded().utf8.count <= 65536 else { throw MacRemoteError.invalid }
        let nodes = try object(value["nodes"]), networks = try object(value["networks"])
        guard nodes.count <= 32, networks.count <= 16 else { throw MacRemoteError.invalid }
        for name in nodes.keys { try identifier(name) }
        for name in networks.keys { try identifier(name) }
        for node in nodes.values {
            guard case .array(let nics) = node["interfaces"], nics.count <= 8 else { throw MacRemoteError.invalid }
            var ids = Set<String>()
            for nic in nics {
                guard Set(try object(nic).keys) == ["id", "address", "mac", "model", "network"], let id = nic["id"].text,
                      ids.insert(id).inserted, let network = nic["network"].text, networks[network] != nil else { throw MacRemoteError.invalid }
                try identifier(id)
            }
        }
        return value
    }
    private static func subnet(_ text: String) throws -> (UInt64, UInt64) {
        let parts = text.split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count == 2, let prefix = Int(parts[1]), String(prefix) == parts[1], (16...30).contains(prefix) else { throw MacRemoteError.invalid }
        let strings = parts[0].split(separator: ".", omittingEmptySubsequences: false)
        let bytes = strings.compactMap { UInt64($0) }
        guard strings.count == 4, bytes.count == 4, zip(strings, bytes).allSatisfy({ String($0.1) == $0.0 && $0.1 <= 255 }),
              bytes[0] == 10 || bytes[0] == 172 && (16...31).contains(bytes[1]) || bytes[0] == 192 && bytes[1] == 168 else { throw MacRemoteError.invalid }
        let address = bytes.reduce(UInt64(0)) { $0 * 256 + $1 }, size = UInt64(1) << (32 - prefix)
        guard address % size == 0 else { throw MacRemoteError.invalid }; return (address, size)
    }
    private static func ip(_ value: UInt64) -> String { [24,16,8,0].map { String((value >> $0) & 255) }.joined(separator: ".") }
    public static func connect(_ manifest: MacRemoteJSON, node: String, nic: String?, network: String) throws -> MacRemoteJSON {
        var root = try object(checked(manifest)), nodes = try object(manifest["nodes"])
        guard let original = nodes[node], let cidr = manifest["networks"][network]["cidr"].text else { throw MacRemoteError.invalid }
        var spec = try object(original), nics = original["interfaces"].items
        guard !nics.contains(where: { $0["network"].text == network && $0["id"].text != nic }) else { throw MacRemoteError.invalid }
        let position = nic.flatMap { id in nics.firstIndex(where: { $0["id"].text == id }) }
        if nic != nil && position == nil { throw MacRemoteError.invalid }
        if let position, nics[position]["network"].text == network { return manifest }
        var id = nic ?? "eth0"
        if nic == nil {
            guard nics.count < 8 else { throw MacRemoteError.invalid }
            var index = 0; while nics.contains(where: { $0["id"].text == "eth\(index)" }) { index += 1 }; id = "eth\(index)"
        }
        let (base, size) = try subnet(cidr)
        let used = Set(nodes.values.flatMap { $0["interfaces"].items.compactMap { $0["address"].text } })
        var address = base + 1; while address < base + size - 1 && used.contains(ip(address)) { address += 1 }
        guard address < base + size - 1 else { throw MacRemoteError.invalid }
        var entry: [String: MacRemoteJSON]
        if let position { entry = try object(nics[position]) }
        else { entry = ["id": .string(id), "mac": .string("derived"), "model": .string(manifest["assets"][original["asset"].text ?? ""]["architecture"].text == "aarch64" ? "virtio-net-pci" : "e1000")] }
        entry["network"] = .string(network); entry["address"] = .string(ip(address))
        if let position { nics[position] = .object(entry) } else { nics.append(.object(entry)) }
        spec["interfaces"] = .array(nics); nodes[node] = .object(spec); root["nodes"] = .object(nodes)
        return try checked(.object(root))
    }
    public static func disconnect(_ manifest: MacRemoteJSON, node: String, nic: String) throws -> MacRemoteJSON {
        var root = try object(checked(manifest)), nodes = try object(manifest["nodes"])
        guard let original = nodes[node], original["interfaces"].items.contains(where: { $0["id"].text == nic }) else { throw MacRemoteError.invalid }
        var spec = try object(original); spec["interfaces"] = .array(original["interfaces"].items.filter { $0["id"].text != nic })
        nodes[node] = .object(spec); root["nodes"] = .object(nodes); return try checked(.object(root))
    }
    public static func addNode(_ manifest: MacRemoteJSON, name: String, asset: String) throws -> MacRemoteJSON {
        try identifier(name); var root = try object(checked(manifest)), nodes = try object(manifest["nodes"])
        guard nodes[name] == nil, nodes.count < 32, manifest["assets"][asset] != .null else { throw MacRemoteError.invalid }
        let arm = manifest["assets"][asset]["architecture"].text == "aarch64"
        nodes[name] = .object(["asset": .string(asset), "cpus": .number(1), "memory_mb": .number(512),
            "firmware": .string(arm ? "uefi" : "bios"), "disk_bus": .string(arm ? "virtio" : "ide"), "interfaces": .array([]), "depends_on": .array([])])
        root["nodes"] = .object(nodes); return try checked(.object(root))
    }
    public static func removeNode(_ manifest: MacRemoteJSON, name: String) throws -> MacRemoteJSON {
        var root = try object(checked(manifest)), nodes = try object(manifest["nodes"])
        guard nodes.removeValue(forKey: name) != nil else { throw MacRemoteError.invalid }
        for key in Array(nodes.keys) {
            var node = try object(nodes[key] ?? .null); node["depends_on"] = .array(node["depends_on"]?.items.filter { $0.text != name } ?? []); nodes[key] = .object(node)
        }
        root["nodes"] = .object(nodes); return try checked(.object(root))
    }
    public static func resources(_ manifest: MacRemoteJSON, node: String, cpus: Int, memory: Int) throws -> MacRemoteJSON {
        var root = try object(checked(manifest)), nodes = try object(manifest["nodes"])
        guard let original = nodes[node], (1...64).contains(cpus), (256...262144).contains(memory) else { throw MacRemoteError.invalid }
        var spec = try object(original); spec["cpus"] = .number(Double(cpus)); spec["memory_mb"] = .number(Double(memory))
        nodes[node] = .object(spec); root["nodes"] = .object(nodes); return try checked(.object(root))
    }
    public static func dependencies(_ manifest: MacRemoteJSON, node: String, selected: [String]) throws -> MacRemoteJSON {
        var root = try object(checked(manifest)), nodes = try object(manifest["nodes"])
        guard let original = nodes[node], Set(selected).count == selected.count, selected.allSatisfy({ $0 != node && nodes[$0] != nil }) else { throw MacRemoteError.invalid }
        var spec = try object(original); spec["depends_on"] = .array(selected.sorted().map { .string($0) }); nodes[node] = .object(spec)
        var remaining = Set(nodes.keys), done = Set<String>()
        while !remaining.isEmpty {
            let ready = remaining.filter { name in
                guard case .array(let deps) = nodes[name]?["depends_on"], deps.allSatisfy({ $0.text != nil }) else { return false }
                return deps.allSatisfy { done.contains($0.text ?? "") }
            }
            guard !ready.isEmpty else { throw MacRemoteError.invalid }
            remaining.subtract(ready); done.formUnion(ready)
        }
        root["nodes"] = .object(nodes); return try checked(.object(root))
    }
    public static func removeNetwork(_ manifest: MacRemoteJSON, name: String) throws -> MacRemoteJSON {
        var root = try object(checked(manifest)), networks = try object(manifest["networks"])
        guard networks[name] != nil, !keys(manifest["nodes"]).contains(where: { node in manifest["nodes"][node]["interfaces"].items.contains { $0["network"].text == name } }) else { throw MacRemoteError.invalid }
        networks.removeValue(forKey: name); root["networks"] = .object(networks); return try checked(.object(root))
    }
    public static func addNetwork(_ manifest: MacRemoteJSON, name: String, cidr: String) throws -> MacRemoteJSON {
        try identifier(name); let (base, size) = try subnet(cidr)
        var root = try object(checked(manifest)), networks = try object(manifest["networks"])
        guard networks[name] == nil, networks.count < 16 else { throw MacRemoteError.invalid }
        for network in networks.values {
            let (old, count) = try subnet(network["cidr"].text ?? "")
            guard base + size <= old || old + count <= base else { throw MacRemoteError.invalid }
        }
        networks[name] = .object(["cidr": .string(cidr), "uplink": .string("none")]); root["networks"] = .object(networks)
        return try checked(.object(root))
    }
}

/// 布局旁车仅包含草稿标识和坐标，不能传入执行清单。
public enum MacGraphLayout {
    private static func object(_ value: MacRemoteJSON) throws -> [String:MacRemoteJSON] {
        guard case .object(let items) = value else { throw MacRemoteError.invalid }; return items
    }
    public static func scope(_ manifest: MacRemoteJSON) throws -> MacRemoteJSON {
        _ = try MacGraphDraft.checked(manifest)
        guard manifest["scenario_id"].text != nil else { throw MacRemoteError.invalid }
        return .object(["scenario_id":manifest["scenario_id"], "nodes":.array(MacGraphDraft.keys(manifest["nodes"]).map { .string($0) }),
                        "networks":.array(MacGraphDraft.keys(manifest["networks"]).map { .string($0) })])
    }
    public static func keys(_ manifest: MacRemoteJSON) -> [String] {
        MacGraphDraft.keys(manifest["nodes"]).map { "node:" + $0 } + MacGraphDraft.keys(manifest["networks"]).map { "network:" + $0 }
    }
    public static func point(_ x: Double, _ y: Double) throws -> MacRemoteJSON {
        guard x.isFinite, y.isFinite else { throw MacRemoteError.invalid }
        return .object(["x":.number(max(0,min(4000,x.rounded()))), "y":.number(max(0,min(32000,y.rounded())))])
    }
    public static func export(_ manifest: MacRemoteJSON, positions: [String:MacRemoteJSON]) throws -> MacRemoteJSON {
        let expected = Set(keys(manifest)); guard Set(positions.keys) == expected else { throw MacRemoteError.invalid }
        for value in positions.values {
            guard Set(try object(value).keys) == ["x","y"], let x = value["x"].integer, let y = value["y"].integer,
                  (0...4000).contains(x), (0...32000).contains(y) else { throw MacRemoteError.invalid }
        }
        return .object(["schema":.number(1), "kind":.string("ctflab-graph-layout"), "scope":try scope(manifest), "positions":.object(positions)])
    }
    public static func load(_ manifest: MacRemoteJSON, text: String) throws -> [String:MacRemoteJSON] {
        guard text.utf8.count <= 65536 else { throw MacRemoteError.invalid }
        let value = try MacRemoteJSON.decode(text)
        guard Set(try object(value).keys) == ["schema","kind","scope","positions"], value["schema"].integer == 1,
              value["kind"].text == "ctflab-graph-layout", value["scope"] == (try scope(manifest)) else { throw MacRemoteError.invalid }
        let positions = try object(value["positions"]); _ = try self.export(manifest, positions: positions); return positions
    }
}

/// 来宾准备续建只引用当前核对的原操作，不将旧记录当作现在仍未完成。
public enum MacGuestRecovery {
    public static func parameters(_ view: MacRemoteJSON, node: String, target: String, resume: Bool) throws -> MacRemoteJSON {
        guard MacRemoteRules.uuid(target), view["status"]["state"].text == "process-running",
              view["status"]["result"].text != "accepted", view["execution"]["identity"].text != "running",
              view["observations"][node]["state"].text == "process-running", view["guest_agents"][node]["containers"].flag == true else { throw MacRemoteError.invalid }
        var parameters: [String:MacRemoteJSON] = ["node":.string(node),"action":.string(resume ? "preparation-resume" : "preparation-inspect"),"target_operation_id":.string(target)]
        if resume {
            let info = view["guest_agents"][node], snapshot = info["last_result"]
            guard info["last_action"].text == "preparation-inspect", snapshot["state"].text == "preparation-observed",
                  snapshot["operation_id"].text == target, snapshot["can_resume"].flag == true, snapshot["automatic_replay"].flag == false,
                  let checksum = snapshot["resume_sha256"].text, MacRemoteRules.digest(checksum) else { throw MacRemoteError.invalid }
            parameters["expected_sha256"] = .string(checksum)
        }
        return .object(parameters)
    }
}

/// 本地只读采样的短时窗口；不将旧状态当作当前进程或来宾健康。
public enum MacObservationWindow {
    public static func fresh(_ view: MacRemoteJSON, now: Date = Date(), requireComplete: Bool = true) -> Bool {
        let value = view["freshness"]
        guard value["schema"].integer == 1, (!requireComplete || value["complete"].flag == true), value["coherent"].flag != false,
              let start = value["sampled_at"].text, let end = value["valid_until"].text else { return false }
        func parse(_ text: String) -> Date? {
            guard text.hasSuffix("Z") || text.range(of:"[+-][0-9]{2}:[0-9]{2}$",options:.regularExpression) != nil else { return nil }
            let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime,.withFractionalSeconds]
            if let date = formatter.date(from:text) { return date }
            formatter.formatOptions = [.withInternetDateTime]; return formatter.date(from:text)
        }
        guard let sampled = parse(start), let until = parse(end) else { return false }
        let duration = until.timeIntervalSince(sampled)
        return duration > 0 && duration <= 60.001 && sampled <= now && now <= until
    }
    public static func invalidated(_ view: MacRemoteJSON) -> MacRemoteJSON {
        guard case .object(var root) = view else { return .null }
        var window: [String:MacRemoteJSON] = [:]
        if case .object(let old) = root["freshness"] { window = old }
        window["complete"] = .bool(false); root["freshness"] = .object(window); return .object(root)
    }
}

/// 最近20步配置历史，不改变布局旁车或任何运行实例。
public struct MacGraphHistory: Equatable {
    public private(set) var past: [MacRemoteJSON] = []
    public private(set) var present: MacRemoteJSON
    public private(set) var future: [MacRemoteJSON] = []
    public var canUndo: Bool { !past.isEmpty }
    public var canRedo: Bool { !future.isEmpty }
    public init(_ source: MacRemoteJSON) throws { _ = try source.encoded(); present = source }
    public mutating func edit(_ next: MacRemoteJSON) throws {
        _ = try next.encoded(); if next == present { return }
        past.append(present); if past.count > 20 { past.removeFirst(past.count-20) }; present = next; future = []
    }
    public mutating func undo() { guard let previous = past.popLast() else { return }; future.insert(present,at:0); present = previous }
    public mutating func redo() { guard !future.isEmpty else { return }; past.append(present); present = future.removeFirst() }
}

/// 仅恢复已绑定日志，不借不完整采样开放生命周期/来宾操作。
public enum MacLogRecovery {
    public static func allowed(_ view: MacRemoteJSON, node: String, busy: Bool, now: Date = Date()) -> Bool {
        let logs = view["supervision"][node]["logs"]
        return !busy && view["freshness"]["coherent"].flag == true && MacObservationWindow.fresh(view, now: now, requireComplete: false)
            && (view["generation"].integer ?? 0) > 0 && view["generation"].integer == view["status"]["generation"].integer
            && view["status"]["operation_id"] == .null && view["status"]["result"].text == "completed"
            && view["execution"]["identity"].text != "running" && view["manifest"]["nodes"][node] != .null
            && logs["kind"].text == "posix-fifo-v1" && logs["rearm_allowed"].flag == true
            && logs["source_identity"].text == "running" && logs["receiver"].text == "not-receiving"
    }
}

/// 外部攻击机卡片展示模型：解析桥接 external-attach-status 白名单字段。
/// 解析失败或字段缺失时如实显示不可用，不虚构登记状态或连接能力。
public struct MacExternalAttachSummary: Equatable, Sendable {
    public struct Slot: Equatable, Sendable {
        public let network: String, address: String, mac: String, cidr: String
    }
    public let instanceUUID: String
    public let generation: Int
    public let slots: [Slot]
    public let bindingText: String
    public let bindingStale: Bool
    public let connectSupported: Bool
    public let note: String

    public init(_ value: MacRemoteJSON) throws {
        guard value["state"].text == "external-attach-status",
              let instance = value["instance_uuid"].text, MacRemoteRules.uuid(instance),
              let generation = value["generation"].integer, generation >= 1,
              let connect = value["connect_supported"].flag else { throw MacRemoteError.invalid }
        guard case .array(let rows) = value["slots"], rows.count <= 16 else { throw MacRemoteError.invalid }
        var slots: [Slot] = []
        for row in rows {
            guard let network = row["network"].text, !network.isEmpty, network.count <= 64,
                  let address = row["address"].text, let mac = row["mac"].text,
                  let cidr = row["cidr"].text else { continue }
            slots.append(Slot(network: network, address: address, mac: mac, cidr: cidr))
        }
        let binding = value["binding"]
        let valid = value["binding_valid"].flag == true
        if valid {
            let name = binding["registration"]["name"].text ?? ""
            let network = binding["network_id"].text ?? ""
            self.bindingText = "已登记：\(name) → \(network)（代次 \(binding["generation"].integer.map(String.init) ?? "?")）"
        } else if binding != .null {
            self.bindingText = "登记已过期：计划或代次已变化，请重新预览并保存。"
        } else {
            self.bindingText = "尚未登记外部攻击机。"
        }
        self.instanceUUID = instance
        self.generation = generation
        self.slots = slots
        self.bindingStale = binding != .null && !valid
        self.connectSupported = connect
        self.note = value["note"].text ?? ""
    }
}

/// A03 契约共享规则：与 tools/ctflab_contract.py 同判定（严格小写UUID、ASCII标识、安全整数）。
public enum MacContractRules {
    public static func uuid(_ value: String) -> Bool {
        let parts = value.split(separator: "-", omittingEmptySubsequences: false).map(String.init)
        guard parts.count == 5, [8, 4, 4, 4, 12] == parts.map(\.count) else { return false }
        return parts.joined().allSatisfy { "0123456789abcdef".contains($0) }
    }
    public static func identifier(_ value: String) -> Bool {
        guard (1...96).contains(value.count), let first = value.first,
              "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789".contains(first) else { return false }
        return value.dropFirst().allSatisfy { "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-".contains($0) }
    }
    public static func safe(_ value: MacRemoteJSON, minimum: Int = 0) -> Int? {
        guard let number = value.integer, number >= minimum else { return nil }
        return number
    }
    public static let states: Set<String> = ["preparing", "prepared", "starting", "process-running", "guest-ready",
        "service-ready", "course-verified", "stopping", "stopped", "resetting", "recovering", "failed", "unknown", "recovery-required"]
    public static let errorMessages: [String: String] = [
        "invalid-request": "请求结构或参数不符合契约。", "version-mismatch": "协议版本不兼容。",
        "permission-denied": "当前调用主体无权访问该实例。", "state-conflict": "实例、代次或状态版本已变化，请重新读取状态。",
        "idempotency-conflict": "同一幂等键不能用于不同请求。", "resource-busy": "操作仍在执行，请读取状态后重试。",
        "identity-unknown": "资源身份无法核验，已保留现场。", "capability-unverified": "所需能力尚未验证。",
        "unsupported-platform": "当前平台不支持此操作。", "storage-insufficient": "存储空间不足，已保留已有状态。",
        "persistence-failed": "操作记录未能可靠提交，需要恢复核验。", "control-unreachable": "控制通道不可达，需要恢复核验。",
        "stop-timeout": "正常停止超时，尚未释放资源。", "reset-commit-failed": "重置提交失败，需要恢复核验。",
        "route-conflict": "实验网络与现有路由冲突。", "cursor-expired": "事件游标已失效，请重新读取状态。",
        "event-gap": "事件序号不连续，请重新读取状态。", "operation-finished": "目标操作已结束，取消请求未执行。",
        "backend-failed": "后端操作失败，需要恢复核验。"]
    /// 与 contract.public_error 同构的公开错误核验；错误文案与代码一一对应，不透出后端细节。
    public static func publicError(_ error: MacRemoteJSON) -> Bool {
        guard case .object(let fields) = error,
              Set(fields.keys) == ["code", "stage", "message", "retryable", "preserved", "recovery_actions", "evidence_refs"],
              let code = error["code"].text, let message = errorMessages[code], error["message"].text == message,
              let stage = error["stage"].text, ["dispatch", "observe", "execute", "commit", "events"].contains(stage),
              error["retryable"].flag == (code == "resource-busy"), error["preserved"].flag == true else { return false }
        let actions = error["recovery_actions"].items.compactMap(\.text)
        guard actions == (code == "cursor-expired" ? ["status", "events"] : ["status"]) else { return false }
        let refs = error["evidence_refs"].items
        guard refs.count <= 32, refs.allSatisfy({ $0.text.map(identifier) ?? false }) else { return false }
        return true
    }
}

/// 原操作账本摘要（历史）：不返回请求参数或幂等键；历史记录不是当前运行事实。
public struct MacSavedOperation: Equatable, Sendable {
    public let operationID: String, requestID: String, operation: String
    public let expectedGeneration: Int?
    public let status: String
    public let responseRecorded: Bool, cancelRequested: Bool
    public init(_ value: MacRemoteJSON) throws {
        guard case .object(let fields) = value,
              Set(fields.keys) == ["operation_id", "request_id", "operation", "expected_generation", "status", "response_recorded", "cancel_requested"],
              let operationID = value["operation_id"].text, MacContractRules.uuid(operationID),
              let requestID = value["request_id"].text, MacContractRules.uuid(requestID),
              let operation = value["operation"].text,
              ["prepare", "start", "stop", "reset", "recover", "cancel", "guest"].contains(operation),
              let status = value["status"].text,
              ["pending", "executing", "unknown", "failed", "completed"].contains(status),
              let recorded = value["response_recorded"].flag, let cancelled = value["cancel_requested"].flag else { throw MacRemoteError.invalid }
        if value["expected_generation"] == .null { expectedGeneration = nil }
        else { guard let generation = MacContractRules.safe(value["expected_generation"], minimum: 1) else { throw MacRemoteError.invalid }; expectedGeneration = generation }
        // 有已保存响应的不能是pending/executing；这两类必须等待真实结果。
        if recorded && ["pending", "executing"].contains(status) { throw MacRemoteError.invalid }
        self.operationID = operationID; self.requestID = requestID; self.operation = operation
        self.status = status; self.responseRecorded = recorded; self.cancelRequested = cancelled
    }
}

/// 已保存操作历史页：游标分页（更早一页用 next_before），全部只读。
public struct MacHistoryPage: Equatable, Sendable {
    public let operations: [MacSavedOperation]
    public let truncated: Bool
    public let nextBefore: String?
    public init(_ reply: MacRemoteJSON, instance: String) throws {
        guard case .object(let fields) = reply,
              Set(fields.keys) == ["state", "instance_uuid", "operations", "truncated", "next_before", "historical", "current_runtime_verified", "automatic_replay"],
              reply["state"].text == "operation-history", reply["instance_uuid"].text == instance,
              reply["historical"].flag == true, reply["current_runtime_verified"].flag == false,
              reply["automatic_replay"].flag == false else { throw MacRemoteError.invalid }
        let rows = reply["operations"].items
        guard rows.count <= 50 else { throw MacRemoteError.invalid }
        operations = try rows.map(MacSavedOperation.init)
        truncated = reply["truncated"].flag == true
        if truncated {
            guard let last = operations.last, let before = reply["next_before"].text, before == last.operationID else { throw MacRemoteError.invalid }
            nextBefore = before
        } else {
            guard reply["next_before"] == .null else { throw MacRemoteError.invalid }
            nextBefore = nil
        }
    }
}

/// 按原操作UUID重开的历史响应：未落结果仍为null，不合成当前状态。
public struct MacSavedRecord: Equatable, Sendable {
    public let record: MacSavedOperation
    public let response: MacRemoteJSON
    public init(_ reply: MacRemoteJSON, instance: String) throws {
        guard case .object(let fields) = reply,
              Set(fields.keys) == ["state", "instance_uuid", "record", "response", "historical", "current_runtime_verified", "automatic_replay"],
              reply["state"].text == "operation-recorded", reply["instance_uuid"].text == instance,
              reply["historical"].flag == true, reply["current_runtime_verified"].flag == false,
              reply["automatic_replay"].flag == false else { throw MacRemoteError.invalid }
        let record = try MacSavedOperation(reply["record"])
        let saved = reply["response"]
        if saved == .null {
            guard !record.responseRecorded, !["completed", "failed"].contains(record.status) else { throw MacRemoteError.invalid }
            response = .null
        } else {
            guard case .object(let responseFields) = saved,
                  Set(responseFields.keys) == ["protocol", "version", "request_id", "instance_uuid", "operation_id", "generation", "state_revision", "state", "cursor", "result", "cancelled", "error", "evidence_refs"],
                  saved["protocol"].text == "ctflab-local", saved["version"].integer == 1,
                  saved["request_id"].text == record.requestID, saved["operation_id"].text == record.operationID,
                  saved["instance_uuid"].text == instance,
                  let state = saved["state"].text, MacContractRules.states.contains(state),
                  saved["result"].text == record.status, saved["cancelled"].flag != nil,
                  MacContractRules.safe(saved["generation"], minimum: 1) != nil,
                  MacContractRules.safe(saved["state_revision"]) != nil, MacContractRules.safe(saved["cursor"]) != nil,
                  record.responseRecorded, !["pending", "executing"].contains(record.status),
                  case .array(let refs) = saved["evidence_refs"], refs.count <= 32,
                  refs.allSatisfy({ $0.text.map(MacContractRules.identifier) ?? false }) else { throw MacRemoteError.invalid }
            if saved["error"] != .null, !MacContractRules.publicError(saved["error"]) { throw MacRemoteError.invalid }
            response = saved
        }
        self.record = record
    }
}

/// 严格事件游标消费：与 contract.merge_events 同判定（同序号内容冲突/缺口/跨实例均拒绝）。
/// 拒绝时 reload=true，游标只按绑定状态快照重定位，不自动重发操作。
public struct MacEventPage: Equatable, Sendable {
    public let cursor: Int
    public let events: [MacRemoteJSON]
    public let reload: Bool
    static let fields: Set<String> = ["protocol", "version", "event_id", "sequence", "timestamp", "instance_uuid",
        "generation", "operation_id", "state_revision", "stage", "state"]
    static let stages: Set<String> = ["intent", "executing", "cancel-requested", "failed", "cancelled", "completed"]
    public static func consume(_ cursorValue: MacRemoteJSON, _ response: MacRemoteJSON, instance: String?) -> MacEventPage {
        func refused() -> MacEventPage { MacEventPage(cursor: 0, events: [], reload: true) }
        guard let cursor = MacContractRules.safe(cursorValue), case .array(let rows) = response, rows.count <= 1000 else { return refused() }
        var fresh: [MacRemoteJSON] = [], seen: [Int: MacRemoteJSON] = [:], identities: [String: Int] = [:]
        var expectedInstance = instance
        for event in rows {
            guard case .object(let fields) = event, Set(fields.keys) == Self.fields,
                  event["protocol"].text == "ctflab-local", event["version"].integer == 1,
                  let sequence = MacContractRules.safe(event["sequence"], minimum: 1),
                  let eventID = event["event_id"].text, MacContractRules.uuid(eventID),
                  let operationID = event["operation_id"].text, MacContractRules.uuid(operationID),
                  let instanceText = event["instance_uuid"].text, MacContractRules.uuid(instanceText),
                  MacContractRules.safe(event["generation"], minimum: 1) != nil,
                  MacContractRules.safe(event["state_revision"]) != nil,
                  let state = event["state"].text, MacContractRules.states.contains(state),
                  let stage = event["stage"].text, Self.stages.contains(stage),
                  let timestamp = event["timestamp"].text, timestamp.unicodeScalars.count <= 64 else { return refused() }
            if expectedInstance == nil { expectedInstance = instanceText }
            guard instanceText == expectedInstance else { return refused() }
            if let prior = identities[eventID], prior != sequence { return refused() }
            identities[eventID] = sequence
            if sequence <= cursor { continue }
            if let prior = seen[sequence] { guard prior == event else { return refused() }; continue }
            guard sequence == cursor + fresh.count + 1 else { return refused() }
            seen[sequence] = event; fresh.append(event)
        }
        return MacEventPage(cursor: cursor + fresh.count, events: fresh, reload: false)
    }
    /// 断流/裁剪后只用本次绑定的状态快照定位下一页；未绑定回复不能决定游标。
    public static func refresh(_ cursor: MacRemoteJSON, _ response: MacRemoteJSON, view: MacRemoteJSON?) -> MacEventPage {
        let result = consume(cursor, response, instance: view?["instance_uuid"].text)
        guard result.reload else { return result }
        let status = view?["status"], viewInstance = view?["instance_uuid"].text
        let bound = status?["protocol"].text == "ctflab-local" && status?["version"].integer == 1
            && viewInstance.map(MacContractRules.uuid) == true
            && status?["instance_uuid"].text == viewInstance
            && MacContractRules.safe(status?["cursor"] ?? .null) != nil
        return MacEventPage(cursor: bound ? status?["cursor"].integer ?? 0 : 0, events: [], reload: true)
    }
}

/// 仅把清单投影为设计图；不生成采样时间、进程状态或可达性证据。
enum MacDesignTopology {
    static func project(_ manifest: MacRemoteJSON) -> MacRemoteJSON? {
        guard (try? MacGraphDraft.checked(manifest)) != nil else { return nil }
        let nodes = MacGraphDraft.keys(manifest["nodes"]).map { id -> MacRemoteJSON in
            let interfaces = manifest["nodes"][id]["interfaces"].items.map { nic -> MacRemoteJSON in
                .object(["id": nic["id"], "network": nic["network"], "planned_address": nic["address"]])
            }
            return .object(["id": .string(id), "interfaces": .array(interfaces)])
        }
        return .object(["topology": .object(["nodes": .array(nodes), "networks": manifest["networks"]])])
    }
}
