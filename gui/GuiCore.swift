// CTFLab 图形入口核心逻辑（无 UI 依赖，可单独编译测试）。
//
// 职责：状态机、按钮门禁、CLI 命令拼接、CLI JSON 解析、错误文案。
// 约束：只调用现有 CLI 能力（dist verify / import --manifest / run / status / health /
// stop --all / reset），不自行实现导入逻辑，不暴露任意 QEMU 参数；启动动作只把用户
// 选中的节点交给 CLI。Kali 的联网和图形分辨率由 CLI 的默认运行策略统一管理。

import Foundation

/// 实验三节点（GUI 只管理这三个 profile）。
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
    public var importedNodes: Set<LabNode> = []
    public var runningNodes: Set<LabNode> = []
    /// 启动选择默认全选，用户可在启动前取消任意靶机；导入仍按清单导入全部节点。
    public var selectedNodes: Set<LabNode> = Set(LabNode.required)
    public var healthyNodes: Set<LabNode> = []
    public var pendingHealthNodes: Set<LabNode> = []
    public var lastError: String?
    public var progressText: String = ""

    public init() {}

    public var verificationPassed: Bool { report?.ok == true }
    public var allImported: Bool { Set(LabNode.required).isSubset(of: importedNodes) }
    public var anyRunning: Bool { !runningNodes.isEmpty }

    public var canVerify: Bool { !(distDir ?? "").isEmpty && !phase.isBusy }
    public var canImport: Bool { verificationPassed && !anyRunning && !phase.isBusy }
    public var canStartSelected: Bool {
        verificationPassed && !selectedNodes.isEmpty
            && selectedNodes.isSubset(of: importedNodes)
            && !anyRunning && !phase.isBusy
    }
    public var canStart: Bool { canStartSelected }
    public var canCheckStatus: Bool { !phase.isBusy }
    public var canStop: Bool { anyRunning && !phase.isBusy }
    public var canReset: Bool { allImported && !anyRunning && !phase.isBusy }

    /// 导入按钮的进度文案（导入中显示第几个节点）。
    public func importProgressText(index: Int, total: Int, node: LabNode) -> String {
        "正在导入 \(node.displayName)（\(index + 1)/\(total)）…"
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
    case status
    case health(node: LabNode)
    case stopAll
    case resetNode(node: LabNode)

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
            let ordered = LabNode.required.filter { nodes.contains($0) }
            args += ["run"] + ordered.map(\.rawValue)
        case .status:
            args += ["status", "--json"]
        case .health(let node):
            args += ["health", node.rawValue, "--json"]
        case .stopAll:
            args += ["stop", "--all"]
        case .resetNode(let node):
            args += ["reset", node.rawValue]
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
        let match = manifestEntries().first { entry in
            (entry["profile"] as? String) == node.rawValue
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
        return LabNode.required.map { .resetNode(node: $0) }
    }
}
