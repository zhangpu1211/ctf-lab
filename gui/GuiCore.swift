// CTFLab 图形入口核心逻辑（无 UI 依赖，可单独编译测试）。
//
// 职责：状态机、按钮门禁、CLI 命令拼接、CLI JSON 解析、错误文案。
// 约束：只调用现有 CLI 能力（dist verify / import --manifest / run / status / health /
// stop --all / reset / inspect / onboard / probe），不自行实现导入逻辑，不暴露任意 QEMU 参数；启动动作只把用户
// 选中的节点交给 CLI。Kali 的联网和图形分辨率由 CLI 的默认运行策略统一管理。

import Foundation

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

public enum CliAction: Equatable {
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

    /// 参数数组：不做 shell 拼接，路径（含空格）保持为单个参数。
    public func arguments(stateDir: String? = nil) -> [String] {
        var args: [String] = []
        if let stateDir, !stateDir.isEmpty {
            args += ["--state-dir", stateDir]
        }
        switch self {
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
        }
        return args
    }

    public var displayCommand: String {
        (["ctflab"] + arguments()).joined(separator: " ")
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
public struct ImportProgress: Decodable {
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
            total > 0 ? done.map { " \(min(100, max(0, Int(Double($0) / Double(total) * 100))))%" } : nil
        } ?? ""
        return "\(stage)\(percent) · \(Int(elapsed_seconds)) 秒"
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
