// CTFLab 图形入口核心逻辑（无 UI 依赖，可单独编译测试）。
//
// 职责：状态机、按钮门禁、CLI 命令拼接、CLI JSON 解析、错误文案。
// 约束：只调用现有 CLI 能力（dist verify / import --manifest / run / status / health /
// stop --all / reset / inspect / onboard / probe），不自行实现导入逻辑，不暴露任意 QEMU 参数；启动动作只把用户
// 选中的节点交给 CLI。Kali 的联网和图形分辨率由 CLI 的默认运行策略统一管理。

import Foundation

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
    public let status: String
    public let problem: String?
    public var id: String { file }

    enum CodingKeys: String, CodingKey {
        case file, profile, role, size, status, problem
        case expectedSize = "expected_size"
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

public struct DistReport: Codable, Hashable {
    public let ok: Bool
    public let entries: [DistEntry]
    public let problems: [String]
    public let summary: DistSummary?
    public let dir: String?
    public let manifest: String?
}

// MARK: - 状态与健康检查

public struct StatusProfile: Codable, Hashable, Identifiable {
    public let id: String
    public let name: String?
    public let imported: Bool
    public let running: Bool
    public let pid: Int?
    public let logPath: String?
    public let baseSHA256: String?
    public let stalePid: Int?

    enum CodingKeys: String, CodingKey {
        case id, name, imported, running, pid
        case logPath = "log_path"
        case baseSHA256 = "base_sha256"
        case stalePid = "stale_pid"
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
    public var configuredProfileIDs: Set<String> = Set(LabNode.required.map(\.rawValue))
    public var importedProfileIDs: Set<String> = []
    public var runningProfileIDs: Set<String> = []
    /// 启动选择默认全选；已运行的节点保留在选择中，但启动时会自动略过它们。
    public var selectedProfileIDs: Set<String> = Set(LabNode.required.map(\.rawValue))
    public var healthyProfileIDs: Set<String> = []
    public var pendingHealthProfileIDs: Set<String> = []
    public var lastError: String?
    public var progressText: String = ""

    public init() {}

    public var verificationPassed: Bool { report?.ok == true }
    public var allImported: Bool { configuredProfileIDs.isSubset(of: importedProfileIDs) }
    public var anyRunning: Bool { !runningProfileIDs.isEmpty }
    public var startableSelectedProfileIDs: Set<String> {
        selectedProfileIDs.subtracting(runningProfileIDs)
    }

    public var canVerify: Bool { !(distDir ?? "").isEmpty && !phase.isBusy }
    public var canImport: Bool { verificationPassed && !anyRunning && !phase.isBusy }
    public var canStartSelected: Bool {
        verificationPassed && !startableSelectedProfileIDs.isEmpty
            && selectedProfileIDs.isSubset(of: importedProfileIDs)
            && !phase.isBusy
    }
    public var canStart: Bool { canStartSelected }
    public var canCheckStatus: Bool { !phase.isBusy }
    public var canStop: Bool { anyRunning && !phase.isBusy }
    public var canReset: Bool { allImported && !anyRunning && !phase.isBusy }

    /// 导入按钮的进度文案（导入中显示第几个节点）。
    public func importProgressText(index: Int, total: Int, profileID: String) -> String {
        "正在导入 \(LabNode.displayName(for: profileID))（\(index + 1)/\(total)）…"
    }

    public var statusLine: String {
        if let lastError { return "失败：\(lastError)" }
        if phase.isBusy { return progressText.isEmpty ? "执行中…" : progressText }
        if verificationPassed && allImported {
            return anyRunning ? "实验环境运行中" : "实验环境已就绪（未运行）"
        }
        if verificationPassed { return "分发目录已通过校验" }
        return "请选择并校验分发目录"
    }
}

// MARK: - CLI 命令拼接

public enum CliAction: Equatable {
    case distVerify(dir: String)
    case importNode(node: LabNode, sourcePath: String, manifestPath: String)
    case run(nodes: [LabNode])
    case importProfile(profileID: String, sourcePath: String, manifestPath: String)
    case runProfiles(profileIDs: [String])
    case status
    case health(node: LabNode)
    case healthProfile(profileID: String)
    case stopAll
    case stopProfiles(profileIDs: [String])
    case resetNode(node: LabNode)
    case resetProfile(profileID: String)
    case inspectImage(sourcePath: String)
    case onboardX86(sourcePath: String, profileID: String)
    case probeProfile(profileID: String, matrix: Bool)

    /// 参数数组：不做 shell 拼接，路径（含空格）保持为单个参数。
    public func arguments(stateDir: String? = nil) -> [String] {
        var args: [String] = []
        if let stateDir, !stateDir.isEmpty {
            args += ["--state-dir", stateDir]
        }
        switch self {
        case .distVerify(let dir):
            args += ["dist", "verify", "--dir", dir, "--json"]
        case .importNode(let node, let sourcePath, let manifestPath):
            // 与 CLI 一致：基盘是位置参数，--manifest 负责哈希校验并配对同目录的 NVRAM 模板。
            args += ["import", node.rawValue, sourcePath, "--manifest", manifestPath]
        case .run(let nodes):
            args += ["run"] + LabNode.orderedProfileIDs(nodes.map(\.rawValue))
        case .importProfile(let profileID, let sourcePath, let manifestPath):
            args += ["import", profileID, sourcePath, "--manifest", manifestPath]
        case .runProfiles(let profileIDs):
            args += ["run"] + LabNode.orderedProfileIDs(profileIDs)
        case .status:
            args += ["status", "--json"]
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
        case .inspectImage(let sourcePath):
            args += ["inspect", sourcePath, "--json"]
        case .onboardX86(let sourcePath, let profileID):
            // x86 向导只明确架构；固件、磁盘控制器、网卡仍由 inspect 证据生成候选，
            // 不在 GUI 中拼接任意 QEMU 原始参数。
            args += ["onboard", sourcePath, "--id", profileID, "--architecture", "x86_64"]
        case .probeProfile(let profileID, let matrix):
            args += ["probe", profileID]
            if matrix { args += ["--matrix"] }
        }
        return args
    }

    public var displayCommand: String {
        (["ctflab"] + arguments()).joined(separator: " ")
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
        guard confirmed, state.allImported else { return nil }
        return LabNode.orderedProfileIDs(state.configuredProfileIDs).map {
            .resetProfile(profileID: $0)
        }
    }
}
