// CTFLab 图形入口核心逻辑的单元测试（swiftc 直接编译运行，无需 XCTest）。
//
// 覆盖：状态机门禁、命令拼接（含空格路径）、清单/状态 JSON 解析、哈希失败阻断、
// 导入失败文案、重置确认门禁、分发目录文件识别。

import Foundation

final class CLIProof: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [CliOutcome] = []
    private var exited = false
    func record(_ value: CliOutcome) { lock.lock(); values.append(value); lock.unlock() }
    func markExited() { lock.lock(); exited = true; lock.unlock() }
    var outcomes: [CliOutcome] { lock.lock(); defer { lock.unlock() }; return values }
    var exitSeen: Bool { lock.lock(); defer { lock.unlock() }; return exited }
}

// 仅测试二进制的显式夹具入口，最多等待2秒；不运行QEMU/Python或用户程序。
func cliOutputFixture(_ mode: String, root: URL) {
    if mode == "descendant" {
        let child = Process(); child.executableURL = URL(fileURLWithPath: CommandLine.arguments[0])
        child.arguments = ["--cli-output-fixture", "gate", root.path]
        child.standardInput = FileHandle.nullDevice
        child.standardOutput = FileHandle.standardOutput; child.standardError = FileHandle.standardError
        try! child.run(); exit(0)
    }
    if mode == "gate" {
        let until = Date().addingTimeInterval(2)
        while !FileManager.default.fileExists(atPath: root.appendingPathComponent("release").path), Date() < until {
            Thread.sleep(forTimeInterval: 0.005)
        }
    }
    if mode == "flood" {
        try! FileHandle.standardOutput.write(contentsOf: Data(repeating: 120, count: 1024 * 1024))
        let marker = Data("候选配置已生成：".utf8)
        try! FileHandle.standardOutput.write(contentsOf: marker.prefix(5))
        try! FileHandle.standardOutput.write(contentsOf: marker.dropFirst(5))
        try! Data("finished".utf8).write(to: root.appendingPathComponent("finished"))
        exit(3)
    }
    if mode == "invalid" {
        try! FileHandle.standardOutput.write(contentsOf: Data([255, 254]))
    } else {
        let bytes = Data("{\"text\":\"中文\"}".utf8)
        try! FileHandle.standardOutput.write(contentsOf: bytes.prefix(11))
        Thread.sleep(forTimeInterval: 0.01)
        try! FileHandle.standardOutput.write(contentsOf: bytes.dropFirst(11))
    }
    try! Data("finished".utf8).write(to: root.appendingPathComponent("finished"))
    exit(0)
}

func runCLIOutputChecks() {
    let buffer = OutputBuffer(limit: 8)
    buffer.append(Data("12345678".utf8))
    check(buffer.snapshot().complete && buffer.snapshot().capturedBytes == 8, "输出恰好达到上限仍完整")
    buffer.append(Data("9".utf8)); buffer.append(Data(repeating: 120, count: 10000))
    check(!buffer.snapshot().complete && buffer.snapshot().capturedBytes == 8, "越限后不追加原始回复或解析截断JSON")
    let marker = Data("候选配置已生成：".utf8)
    buffer.append(marker.prefix(4)); buffer.append(marker.dropFirst(4))
    check(buffer.snapshot().candidateCreated, "越限后跨UTF8块保留候选提示元数据")
    let utf = OutputBuffer(limit: 32); let text = Data("中文".utf8)
    utf.append(text.prefix(1)); check(!utf.snapshot().complete, "半个UTF8字符暂不当完整回复")
    utf.append(text.dropFirst(1)); check(utf.snapshot().complete && utf.snapshot().text == "中文", "后续字节补全后恢复精确UTF8")
    utf.markReadFailure(); check(!utf.snapshot().complete, "读取失败后不能仅凭合法前缀成功")

    let updates = CLIOutputUpdates(); var schedules = 0
    for _ in 0..<1000 { if updates.offer(Data(repeating: 120, count: 1024), progress: nil) { schedules += 1 } }
    let p = ImportProgress.latest(in: "CTFLAB_IMPORT_PROGRESS {\"stage\":\"提交\",\"elapsed_seconds\":1,\"cancellable\":false}\n")!
    _ = updates.offer(Data("tail".utf8), progress: p)
    let batch = updates.take()
    check(schedules == 1 && batch.text.utf8.count <= 65536 && batch.text.hasSuffix("tail"), "千次输出只排一个有界显示批次")
    check(batch.progress?.cancellable == false, "合并通知保留最新不可取消状态")
    check(updates.offer(Data("new".utf8), progress: nil), "消费批次后才安排下一通知")
    _ = updates.take()
    let largeProgress = ImportProgress.latest(in: "CTFLAB_IMPORT_PROGRESS {\"stage\":\"异常\",\"done\":9223372036854775807,\"total\":1,\"elapsed_seconds\":1e300,\"cancellable\":false}\n")!
    check(largeProgress.label == "异常 100% · 耗时未知", "进度大整数先截断再转换，超大耗时明确未知")
    let negativeProgress = ImportProgress(stage: "异常", done: Int64.min, total: 1, elapsed_seconds: -1, cancellable: false)
    check(negativeProgress.label == "异常 0% · 耗时未知", "负进度归零但负耗时不伪装正常")
    let infiniteProgress = ImportProgress(stage: "异常", done: nil, total: nil, elapsed_seconds: .infinity, cancellable: false)
    check(infiniteProgress.label == "异常 · 耗时未知", "非有限耗时不能转Int崩溃")
    let partialPipe = Pipe(); let partialBuffer = OutputBuffer(limit: 32)
    let partialReader = CLIPipeCollector(handle: partialPipe.fileHandleForReading, buffer: partialBuffer)
    let available = DispatchSemaphore(value: 0)
    try! partialPipe.fileHandleForWriting.write(contentsOf: Data("ready".utf8))
    DispatchQueue.global().async { _ = partialReader.receive({ _ in }); available.signal() }
    let beforeEOF = available.wait(timeout: .now() + 1) == .success
    check(beforeEOF, "有数据即返回有界读取，不等待满64KiB或EOF")
    try! partialPipe.fileHandleForWriting.close()
    if !beforeEOF { _ = available.wait(timeout: .now() + 1) }
    check(partialReader.drain({ _ in }) && partialBuffer.snapshot().text == "ready", "分块读取结束后尾部完整收口")
    let identityPipe = Pipe(); let identityBuffer = OutputBuffer(limit: 32)
    let identityReader = CLIPipeCollector(handle: identityPipe.fileHandleForReading, buffer: identityBuffer)
    try! identityPipe.fileHandleForReading.close()
    let unrelated = Pipe()
    try! unrelated.fileHandleForWriting.write(contentsOf: Data("other".utf8)); try! unrelated.fileHandleForWriting.close()
    try! identityPipe.fileHandleForWriting.write(contentsOf: Data("owned".utf8)); try! identityPipe.fileHandleForWriting.close()
    check(identityReader.drain({ _ in }) && identityBuffer.snapshot().text == "owned", "原句柄关闭后仍只读取独立绑定的旧管道")
    check(try! unrelated.fileHandleForReading.read(upToCount: 32) == Data("other".utf8), "不会借描述符复用读取另一条管道")
    let ioSlots = CLIRequestSlots(maximum: 1); let ioTicket = ioSlots.acquire()!
    let lifetime = CLIRequestLifetime(ticket: ioTicket, hasInput: true)
    lifetime.processFinished(outputClosed: true)
    check(ioSlots.active == 1, "进程和输出结束仍须等待输入写端收口")
    lifetime.inputFinished(); check(ioSlots.active == 0, "输入结束后统一释放进程与管道槽位")
    let slots = CLIRequestSlots(maximum: 1); let first = slots.acquire()!
    check(slots.acquire() == nil && slots.active == 1, "在途已满不发放新进程槽位")
    first.release(); first.release(); check(slots.active == 0, "资源收口重复释放仍只计一次")
    do { _ = slots.acquire() }
    check(slots.active == 1, "未核验的票据离开作用域不静默释放")
    let proof = CLIProof(); let response = CLIResponseOnce { proof.record($0) }
    check(response.finish(.success("one")) && !response.finish(.failure("late")), "同步收口也只交付一次")
    response.startTimeout(seconds: 0.001); Thread.sleep(forTimeInterval: 0.02)
    check(proof.outcomes == [.success("one")], "已结束请求不新增迟到计时回复")

    for mode in ["normal", "flood", "invalid", "gate", "descendant"] {
        let root = URL(fileURLWithPath: NSTemporaryDirectory()).resolvingSymlinksInPath()
            .appendingPathComponent("ctflab-cli-proof-\(UUID().uuidString)")
        try! FileManager.default.createDirectory(at: root, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let process = Process(); process.executableURL = URL(fileURLWithPath: CommandLine.arguments[0])
        process.arguments = ["--cli-output-fixture", mode, root.path]
        process.standardInput = FileHandle.nullDevice
        let pipe = Pipe(); process.standardOutput = pipe; process.standardError = pipe
        let captured = OutputBuffer(limit: mode == "flood" ? 64 : 4096)
        let collector = CLIPipeCollector(handle: pipe.fileHandleForReading, buffer: captured)
        let localSlots = CLIRequestSlots(maximum: 1); let ticket = localSlots.acquire()!
        let localProof = CLIProof(); let replied = DispatchSemaphore(value: 0); let ended = DispatchSemaphore(value: 0)
        let once = CLIResponseOnce { localProof.record($0); replied.signal() }
        pipe.fileHandleForReading.readabilityHandler = { handle in
            switch collector.receive({ _ in }) {
            case .received: break
            case .eof, .failed: handle.readabilityHandler = nil
            }
        }
        process.terminationHandler = { finished in
            localProof.markExited()
            pipe.fileHandleForReading.readabilityHandler = nil
            if collector.drain({ _ in }) { ticket.release() }
            let value = captured.snapshot()
            _ = once.finish(value.complete && finished.terminationStatus == 0 ? .success(value.text) : .failure(value.text))
            ended.signal()
        }
        if mode == "gate" || mode == "descendant" { once.startTimeout(seconds: 0.01) }
        do { try process.run() }
        catch { check(false, "自有Swift子进程启动失败"); ticket.release(); continue }
        if mode == "gate" || mode == "descendant" {
            check(replied.wait(timeout: .now() + 3) == .success, "\(mode)等待超时先交付未知结果")
            if mode == "descendant" {
                let until = Date().addingTimeInterval(1)
                while !localProof.exitSeen && Date() < until { Thread.sleep(forTimeInterval: 0.005) }
                check(localProof.exitSeen, "父进程退出已观察，不能当stdout已结束")
            }
            check(localSlots.active == 1 && localSlots.acquire() == nil, "\(mode)未收口仍持槽且不停止后台")
            try! Data("release".utf8).write(to: root.appendingPathComponent("release"))
        }
        let finished = ended.wait(timeout: .now() + 5) == .success
        check(finished && localSlots.active == 0, "\(mode)真实退出及EOF后释放槽位")
        guard finished else { continue } // 失败现场保留，不处理其他进程。
        process.waitUntilExit()
        check(FileManager.default.fileExists(atPath: root.appendingPathComponent("finished").path), "\(mode)后台完成标记仍写入")
        check(localProof.outcomes.count == 1, "\(mode)迟到终态不重复交付")
        if mode == "flood" {
            check(!captured.snapshot().complete && captured.snapshot().candidateCreated && captured.snapshot().capturedBytes <= 64,
                  "真实大输出排空且上限后候选标记仍可核对")
        } else if mode == "invalid" { check(!captured.snapshot().complete, "真实非法编码不能冒充成功") }
        else { check(captured.snapshot().text == "{\"text\":\"中文\"}" && captured.snapshot().complete, "\(mode)分块JSON原字节顺序完整") }
        try? FileManager.default.removeItem(at: root)
    }
}

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

// MARK: 外部攻击机卡片展示模型

func runExternalAttachChecks() {
    func json(_ text: String) -> MacRemoteJSON { (try? MacRemoteJSON.decode(text)) ?? .null }
    let valid = json("""
    {"state":"external-attach-status","instance_uuid":"0d1f7e57-7b1e-4c8e-9c8d-2f1a3b4c5d60","generation":3,
     "connect_supported":false,"note":"材料先于连接。",
     "binding":{"registration":{"name":"教室Kali"},"network_id":"lab0","generation":3},"binding_valid":true,
     "slots":[{"network":"lab0","address":"192.168.50.9","mac":"02:aa:bb:cc:dd:ee","cidr":"192.168.50.0/24"}]}
    """)
    if let summary = try? MacExternalAttachSummary(valid) {
        check(summary.bindingText.contains("已登记") && summary.bindingText.contains("教室Kali"), "有效登记显示名称与网段")
        check(!summary.bindingStale, "有效登记不过期")
        check(summary.slots.count == 1 && summary.slots[0].address == "192.168.50.9", "槽位静态地址展示")
        check(!summary.connectSupported, "验收前不提供连接")
    } else { check(false, "有效状态可解析") }
    let stale = json("""
    {"state":"external-attach-status","instance_uuid":"0d1f7e57-7b1e-4c8e-9c8d-2f1a3b4c5d60","generation":4,
     "connect_supported":false,"note":"","binding":{"registration":{"name":"旧"}},"binding_valid":false,"slots":[]}
    """)
    if let summary = try? MacExternalAttachSummary(stale) {
        check(summary.bindingStale && summary.bindingText.contains("过期"), "计划或代次变化标记过期")
        check(summary.slots.isEmpty, "无槽位如实显示")
    } else { check(false, "过期状态可解析") }
    check((try? MacExternalAttachSummary(.null)) == nil, "缺失状态不可解析")
    let badState = json("{\"state\":\"overview\",\"slots\":[]}")
    check((try? MacExternalAttachSummary(badState)) == nil, "非接入状态拒绝")
}

// MARK: A03 持久操作账本（历史/原响应）只读模型

func runSavedOperationChecks() {
    func json(_ text: String) -> MacRemoteJSON { (try? MacRemoteJSON.decode(text)) ?? .null }
    let instance = "0d1f7e57-7b1e-4c8e-9c8d-2f1a3b4c5d60"
    let other = "11111111-2222-4333-8444-555555555555"
    let summary = """
    {"operation_id":"aaaaaaaa-1111-4222-8333-444444444444","request_id":"bbbbbbbb-1111-4222-8333-444444444444",
     "operation":"prepare","expected_generation":null,"status":"completed","response_recorded":true,"cancel_requested":false}
    """
    let response = """
    {"protocol":"ctflab-local","version":1,"request_id":"bbbbbbbb-1111-4222-8333-444444444444",
     "instance_uuid":"\(instance)","operation_id":"aaaaaaaa-1111-4222-8333-444444444444","generation":1,
     "state_revision":3,"state":"prepared","cursor":4,"result":"completed","cancelled":false,"error":null,"evidence_refs":[]}
    """
    let recordReply = """
    {"state":"operation-recorded","instance_uuid":"\(instance)","record":\(summary),"response":\(response),
     "historical":true,"current_runtime_verified":false,"automatic_replay":false}
    """
    if let record = try? MacSavedRecord(json(recordReply), instance: instance) {
        check(record.record.operation == "prepare" && record.record.responseRecorded, "有效原响应记录可解析")
        check(record.response["state"].text == "prepared", "历史响应状态按账本原样读取")
    } else { check(false, "有效原响应记录可解析") }
    check((try? MacSavedRecord(json(recordReply), instance: other)) == nil, "原响应拒绝其他实例")
    check((try? MacSavedOperation(json(summary))) != nil, "有效账本摘要可解析")
    // pending/executing 不允许携带已保存响应；completed 不允许缺失响应。
    let pendingRecord = """
    {"state":"operation-recorded","instance_uuid":"\(instance)","record":\(json(summary)),
     "response":null,"historical":true,"current_runtime_verified":false,"automatic_replay":false}
    """
    check((try? MacSavedRecord(json(pendingRecord), instance: instance)) == nil, "completed缺响应拒绝")
    var mutated = json(recordReply); if case .object(var fields) = mutated { fields["automatic_replay"] = .bool(true); mutated = .object(fields) }
    check((try? MacSavedRecord(mutated, instance: instance)) == nil, "自动重放标记拒绝")
    let pageReply = """
    {"state":"operation-history","instance_uuid":"\(instance)","operations":[\(summary)],
     "truncated":true,"next_before":"aaaaaaaa-1111-4222-8333-444444444444",
     "historical":true,"current_runtime_verified":false,"automatic_replay":false}
    """
    if let page = try? MacHistoryPage(json(pageReply), instance: instance) {
        check(page.truncated && page.nextBefore == "aaaaaaaa-1111-4222-8333-444444444444", "截断页给出原操作UUID游标")
    } else { check(false, "有效历史页可解析") }
    var truncatedPage = json(pageReply); if case .object(var fields) = truncatedPage { fields["next_before"] = .null; truncatedPage = .object(fields) }
    check((try? MacHistoryPage(truncatedPage, instance: instance)) == nil, "截断页缺游标拒绝")
    var missing = json(summary); if case .object(var fields) = missing { fields["cancel_requested"] = nil; missing = .object(fields) }
    check((try? MacSavedOperation(missing)) == nil, "摘要缺字段拒绝")
    var extra = json(summary); if case .object(var fields) = extra { fields["idempotency_key"] = .string("private"); extra = .object(fields) }
    check((try? MacSavedOperation(extra)) == nil, "摘要不透出幂等键等私有字段")
    check(!MacContractRules.uuid("AAAAAAAA-1111-4222-8333-444444444444"), "大写UUID拒绝")
    check(MacContractRules.identifier("lab-0.node_1") && !MacContractRules.identifier("-leading") && !MacContractRules.identifier("空格 id"), "标识规则与Python一致")
}

// MARK: A03 严格事件游标（与 contract.merge_events 同判定）

func runEventCursorChecks() {
    func json(_ text: String) -> MacRemoteJSON { (try? MacRemoteJSON.decode(text)) ?? .null }
    let instance = "0d1f7e57-7b1e-4c8e-9c8d-2f1a3b4c5d60"
    func event(_ sequence: Int, state: String = "prepared", stage: String = "completed",
               eventID: String? = nil) -> String {
        let id = eventID ?? ("cccccccc-1111-4222-8333-44444444444" + String(sequence % 10))
        return """
        {"protocol":"ctflab-local","version":1,"event_id":"\(id)","sequence":\(sequence),
         "timestamp":"2026-10-31T10:00:00+00:00","instance_uuid":"\(instance)","generation":1,
         "operation_id":"aaaaaaaa-1111-4222-8333-444444444444","state_revision":\(sequence),"stage":"\(stage)","state":"\(state)"}
        """
    }
    let three = "[" + [event(1), event(2, state: "process-running", stage: "executing"), event(3)].joined(separator: ",") + "]"
    let kept = MacEventPage.consume(.number(0), json(three), instance: instance)
    check(!kept.reload && kept.cursor == 3 && kept.events.count == 3, "三条连续事件全部消费")
    let dedupe = MacEventPage.consume(.number(0), json("[\(event(1)),\(event(1))]"), instance: instance)
    check(!dedupe.reload && dedupe.events.count == 1, "同序号同内容去重")
    check(MacEventPage.consume(.number(0), json("[\(event(1)),\(event(1, state: "failed"))]"), instance: instance).reload, "同序号内容冲突拒绝")
    check(MacEventPage.consume(.number(0), json("[\(event(1)),\(event(2, eventID: "cccccccc-1111-4222-8333-444444444441"))]"), instance: instance).reload, "事件ID跨序号复用拒绝")
    check(MacEventPage.consume(.number(0), json("[\(event(2))]"), instance: instance).reload, "缺口拒绝")
    check(MacEventPage.consume(.number(2), json("[\(event(1)),\(event(2)),\(event(3))]"), instance: instance).cursor == 3, "旧前缀跳过后续读")
    check(MacEventPage.consume(.number(1), json("[\(event(1, state: "bogus"))]"), instance: instance).reload, "旧事件同样严格校验")
    check(MacEventPage.consume(.number(0), json(three), instance: "11111111-2222-4333-8444-555555555555").reload, "跨实例混用拒绝")
    check(MacEventPage.consume(.number(0), json(three), instance: nil).cursor == 3, "未绑定实例按首条绑定")
    check(MacEventPage.consume(.string("0"), json(three), instance: instance).reload, "游标类型错误拒绝")
    check(MacEventPage.consume(.number(-1), json("[]"), instance: instance).reload, "负游标拒绝")
    check(MacEventPage.consume(.number(0), json("{\"events\":[]}"), instance: instance).reload, "未知回复形状拒绝")
    let view = json("""
    {"instance_uuid":"\(instance)","status":{"protocol":"ctflab-local","version":1,"instance_uuid":"\(instance)","cursor":5}}
    """)
    let relocated = MacEventPage.refresh(.number(0), json("{\"error\":{\"code\":\"cursor-expired\"}}"), view: view)
    check(relocated.reload && relocated.cursor == 5, "游标过期按绑定状态重定位")
    let unbound = MacEventPage.refresh(.number(0), json("[\(event(2))]"), view: json("{\"instance_uuid\":\"\(instance)\"}"))
    check(unbound.reload && unbound.cursor == 0, "未绑定快照不决定游标")
}

// MARK: 跨语言向量模式：Python测试以相同输入驱动本模型并对照 merge_events 结果。
// 输入：{"events":[{cursor,response,view}],"history":[{reply,instance}],"records":[{reply,instance}]}；不启动任何服务。

func contractVectorMode() {
    let raw = FileHandle.standardInput.readDataToEndOfFile()
    guard let value = try? MacRemoteJSON.decode(String(data: raw, encoding: .utf8) ?? "") else { exit(2) }
    var events: [MacRemoteJSON] = []
    for row in value["events"].items {
        let result = MacEventPage.refresh(row["cursor"], row["response"], view: row["view"] == .null ? nil : row["view"])
        events.append(.object(["cursor": .number(Double(result.cursor)), "reload": .bool(result.reload),
                               "count": .number(Double(result.events.count))]))
    }
    var history: [MacRemoteJSON] = [], records: [MacRemoteJSON] = []
    for row in value["history"].items {
        let accepted = (try? MacHistoryPage(row["reply"], instance: row["instance"].text ?? "")) != nil
        history.append(.bool(accepted))
    }
    for row in value["records"].items {
        let accepted = (try? MacSavedRecord(row["reply"], instance: row["instance"].text ?? "")) != nil
        records.append(.bool(accepted))
    }
    let output = MacRemoteJSON.object(["events": .array(events), "history": .array(history), "records": .array(records)])
    let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
    guard let data = try? encoder.encode(output) else { exit(2) }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
    exit(0)
}


func runPublicDiagnosticsChecks() {
    func node(_ phase: String = "network", stale: Int? = nil) -> StatusProfile {
        StatusProfile(id: "private-user-secret", name: "10.22.33.44", builtin: false, imported: true,
            importState: "registered", sourcePath: "/Users/private-user/source.qcow2", running: true,
            pid: 123456789, logPath: "C:\\Users\\private-user\\password.log", baseSHA256: "secret-sha",
            stalePid: stale,
            boot: BootSummary(phase: phase, phaseLabel: "password=secret", overall: "secret-overall",
                elapsedSeconds: 123456789, readinessTimeoutSeconds: 123456789,
                stages: [BootStage(name: "secret-stage", ok: true, detail: "token=secret")],
                diagnosis: BootDiagnosis(message: "secret", failedChecks: ["secret"], logPath: "/Users/private-user",
                    clientLogPath: "secret", hint: "secret")), spiceClient: nil)
    }
    do {
        let value = try MacPublicDiagnostics.preview([node()], version: "0.1.3-preview.20261028", machine: "arm64")
        let decoded = try JSONSerialization.jsonObject(with: value.data) as! [String: Any]
        let profiles = decoded["profiles"] as! [[String: String]]
        check(profiles == [["node": "node-1", "state": "running", "boot_phase": "network"]], "分享摘要只保留匿名节点和白名单状态阶段")
        check(Set(decoded.keys) == Set(["schema", "kind", "scope", "ctflab_version", "host", "profiles", "observation", "may_be_stale", "omitted", "uploaded"]), "分享摘要只生成固定顶层字段")
        check(decoded["observation"] as? String == "displayed-snapshot" && decoded["may_be_stale"] as? Bool == true,
            "分享摘要明确是可能过期的显示快照")
        check(decoded["uploaded"] as? Bool == false, "分享摘要不上传")
        check(value.data == Data(value.text.utf8) && value.data.last == 10, "预览显示与导出保留同一UTF8字节及换行")
        for secret in ["private-user", "secret", "10.22.33.44", "123456789", "password", "token", "/Users/", "C:\\"] {
            check(!value.text.contains(secret), "分享摘要不泄露 \(secret)")
        }
        let untrusted = try MacPublicDiagnostics.preview([node("secret-phase", stale: 123)], version: "password=secret", machine: "/Users/private-user")
        check(!untrusted.text.contains("secret") && !untrusted.text.contains("private-user"), "分享摘要拒绝自由文本版本/架构/阶段")
        let untrustedJSON = try JSONSerialization.jsonObject(with: untrusted.data) as! [String: Any]
        check((untrustedJSON["profiles"] as! [[String: String]])[0]["state"] == "unknown", "陈旧进程登记不作为运行证明")
        check((untrustedJSON["host"] as! [String: String])["machine"] == "unknown", "未知架构不回显")
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        defer { try? FileManager.default.removeItem(at: directory) }
        let path = directory.appendingPathComponent("summary.json")
        try value.save(to: path)
        check(try Data(contentsOf: path) == value.data, "分享摘要排他保存预览原字节")
        let info = try FileManager.default.attributesOfItem(atPath: path.path)
        check((info[.posixPermissions] as? NSNumber)?.intValue == 0o600, "分享摘要文件创建即0600")
        do { try untrusted.save(to: path); check(false, "分享摘要不得覆盖") }
        catch { check(try Data(contentsOf: path) == value.data, "再次保存拒绝覆盖且原字节不变") }
        let link = directory.appendingPathComponent("link.json")
        try FileManager.default.createSymbolicLink(at: link, withDestinationURL: path)
        do { try value.save(to: link); check(false, "分享摘要不得覆盖符号链接") }
        catch { check(try Data(contentsOf: path) == value.data, "符号链接保存拒绝且原文件不变") }
        do { try value.save(to: URL(string: "https://example.invalid/private")!); check(false, "分享摘要不得写网络URL") }
        catch { check(true, "分享摘要拒绝网络URL且不执行网络请求") }
        do { _ = try MacPublicDiagnostics.preview(Array(repeating: node(), count: 257), version: "1.2.3", machine: "arm64"); check(false, "分享节点数有界") }
        catch { check(true, "分享摘要拒绝超过256个节点") }
        let maximum = try MacPublicDiagnostics.preview(Array(repeating: node(), count: 256), version: "1.2.3", machine: "arm64")
        check(maximum.data.count <= 65536 && maximum.text.contains("node-256"), "最大节点摘要有界且不截断")
        let again = try MacPublicDiagnostics.preview([node()], version: "0.1.3-preview.20261028", machine: "arm64")
        check(again.data == value.data && again.id != value.id, "同一快照字节稳定且窗口标识不写入分享内容")
        let empty = try MacPublicDiagnostics.preview([], version: "1.2.3", machine: "arm64")
        check((try JSONSerialization.jsonObject(with: empty.data) as! [String: Any])["profiles"] as? [String] == [], "空节点库可生成合法白名单摘要")
    } catch { check(false, "分享摘要检查异常") }
}

func runAll() {
    runCLIOutputChecks()
    runPublicDiagnosticsChecks()
    runExternalAttachChecks()
    runSavedOperationChecks()
    runEventCursorChecks()
    let progressLine = "CTFLAB_IMPORT_PROGRESS {\"stage\":\"来源校验\",\"done\":50,\"total\":100,\"elapsed_seconds\":2.0,\"cancellable\":true}"
    check(ImportProgress.latest(in: progressLine) == nil, "未完整的进度行等待下一批")
    check(ImportProgress.latest(in: progressLine + "\n")?.label == "来源校验 50% · 2 秒", "阶段字节百分比和耗时解析")
    check(ImportProgress.latest(in: progressLine + "\nCTFLAB_IMPORT_PROGRESS broken\n")?.cancellable == true, "坏进度行不覆盖有效状态")
    check(CliAction.retryOnboard(sourcePath: "/tmp/a b.ova", profileID: "box").arguments()
          == ["onboard", "/tmp/a b.ova", "--id", "box", "--resume"], "重试参数不覆盖候选、不经 shell")
    check(!CliAction.status.controlsImport && CliAction.onboardAuto(sourcePath: "a", profileID: "box").controlsImport,
          "取消通道只用于导入，不干扰状态查询")

    var state = GuiState()
    check(!state.canImport, "未选择目录时导入禁用")
    check(!state.canStart, "未选择目录时启动禁用")
    check(!state.canReset, "未导入时重置禁用")

    state.distDir = "/tmp/with space/dist"
    check(state.canVerify, "选择目录后可校验")

    let okEntry = DistEntry(file: "kali-arm64-base.qcow2", profile: "kali-arm64", role: "base",
                            size: 100, expectedSize: 100, expectedSha256: "abc", status: "ok", problem: nil)
    let badEntry = DistEntry(file: "smoke-base.qcow2", profile: "smoke", role: "base",
                             size: 90, expectedSize: 100, expectedSha256: "abc", status: "sha256-mismatch",
                             problem: "SHA-256 不一致")
    let okReport = DistReport(ok: true, entries: [okEntry], problems: [],
                              summary: DistSummary(total: 1, ok: 1, failed: 0),
                              dir: state.distDir, manifest: "\(state.distDir!)/DISTRIBUTION.json")
    let badReport = DistReport(ok: false, entries: [badEntry], problems: ["smoke-base.qcow2: SHA-256 不一致"],
                               summary: DistSummary(total: 2, ok: 1, failed: 1),
                               dir: state.distDir, manifest: "\(state.distDir!)/DISTRIBUTION.json")

    state.report = badReport
    check(!state.canImport, "校验失败时导入禁用")
    // 启动只看状态目录的导入结果：镜像文件夹未校验不阻塞已导入节点启动。
    state.importedProfileIDs = [LabNode.kali.rawValue]
    state.selectedProfileID = LabNode.kali.rawValue
    check(state.canStart, "校验失败但节点已导入时仍可启动")
    state.importedProfileIDs = []
    state.selectedProfileID = nil
    check(state.report?.entries.first?.isOK == false, "失败条目状态可读")
    check(state.report?.entries.first?.statusText == "哈希不符", "失败状态中文文案")

    state.report = okReport
    // 真实 GUI 会从已校验清单写入本次课程的节点集合；这里显式模拟该步骤。
    state.configuredProfileIDs = Set(LabNode.required.map(\.rawValue))
    check(state.canImport, "校验通过后导入可用")
    check(!state.canStart, "未导入时启动仍禁用")

    state.importedProfileIDs = Set(LabNode.required.map(\.rawValue))
    check(state.allImported, "三个节点全部导入")
    state.selectedProfileID = LabNode.kali.rawValue
    check(state.canStart, "全部导入且未运行时启动可用")
    state.selectedProfileID = LabNode.smoke.rawValue
    check(state.canStartSelected, "可选择一个已导入靶机启动")
    state.selectedProfileID = nil
    check(!state.canStartSelected, "未选择节点时启动禁用")
    state.selectedProfileID = LabNode.kali.rawValue
    check(state.canReset, "全部导入后重置可用")
    check(!state.canStop, "未运行时停止禁用")

    state.runningProfileIDs = Set(LabNode.required.map(\.rawValue))
    check(state.canStop, "运行中停止可用")
    check(!state.canStart, "所选节点均运行时启动禁用")
    state.runningProfileIDs = [LabNode.kali.rawValue]
    state.selectedProfileID = LabNode.smoke.rawValue
    check(state.canStart, "Kali 运行时仍可单独启动 Smoke")
    state.selectedProfileID = LabNode.kali.rawValue
    check(state.canStopSelected, "当前选择的运行节点可停止")

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
                         "dist", "verify", "--dir", "/Users/student/课程 分发/dist", "--json", "--conflicts"],
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
    let appendedArgs = CliAction.runProfiles(profileIDs: ["webserver", "smoke", "kali-arm64"],
                                               clipboard: false).arguments()
    check(appendedArgs == ["run", "kali-arm64", "smoke", "webserver"], "追加节点按稳定顺序启动")
    check(CliAction.stopProfiles(profileIDs: ["webserver"]).arguments() == ["stop", "webserver"],
          "可停止单个扩展节点")
    check(CliAction.stopAll.arguments() == ["stop", "--all"], "停止使用 stop --all")
    check(CliAction.status.arguments() == ["status", "--json"], "状态查询使用 JSON")
    check(CliAction.health(node: .smoke).arguments() == ["health", "smoke", "--json"], "健康检查按节点 JSON")
    check(CliAction.resetNode(node: .basic).arguments() == ["reset", "basic-pentesting-2"], "重置按节点")
    let inspectArgs = CliAction.inspectImage(sourcePath: "/tmp/legacy image.ova").arguments()
    check(inspectArgs == ["inspect", "/tmp/legacy image.ova", "--json", "--no-hash"],
          "x86 向导先调用只读 inspect JSON，含空格路径不拆分")
    let onboardArgs = CliAction.onboardX86(sourcePath: "/tmp/legacy image.ova", profileID: "legacy-image").arguments()
    check(onboardArgs == ["onboard", "/tmp/legacy image.ova", "--id", "legacy-image", "--architecture", "x86_64"],
          "x86 向导只固定架构，不传任意 QEMU 参数")
    check(CliAction.probeProfile(profileID: "legacy-image", matrix: false).arguments()
          == ["probe", "legacy-image"], "首次启动探测不隐式运行矩阵")
    check(CliAction.probeProfile(profileID: "legacy-image", matrix: true).arguments()
          == ["probe", "legacy-image", "--matrix"], "回退矩阵必须由用户显式请求")
    check(CliAction.applyMatrixCandidate(profileID: "legacy-image", reportPath: "/tmp/with space/report.json").arguments()
          == ["probe", "legacy-image", "--apply-matrix-report", "/tmp/with space/report.json", "--confirm-apply"],
          "矩阵候选只在显式确认时保存，报告路径不经 shell")
    check(!CliAction.applyMatrixCandidate(profileID: "legacy-image", reportPath: "/tmp/r.json").controlsImport,
          "固化矩阵候选不占用导入取消通道")
    let matrixSuccess = """
      bios / ide: login_ready（画面 login_ready）
    矩阵结论：bios / ide 可以启动（login_ready）；请人工查看截图后再修改 profile。
    矩阵报告：/tmp/state with space/logs/probes/legacy-matrix.json
    """
    check(MatrixProbeResult.parse(matrixSuccess)?.reportPath
          == "/tmp/state with space/logs/probes/legacy-matrix.json", "只解析明确成功的矩阵报告")
    let matrixFailure = """
    矩阵结论：所有白名单候选都没有识别到可用启动画面；请人工检查截图与日志。
    矩阵报告：/tmp/state/logs/probes/failed.json
    """
    check(MatrixProbeResult.parse(matrixFailure) == nil, "失败矩阵即使有报告也不能显示固化按钮")
    let manualReview = "矩阵待人工复核：1（没有自动成功结论）\n复核截图：/tmp/screenshot.png\n矩阵报告：/tmp/matrix.json\n"
    check(MatrixProbeResult.parse(manualReview)?.reviewAttempt == 1, "待人工复核与自动成功分开")
    check(MatrixProbeResult.parse("矩阵待人工复核：1（没有自动成功结论）\n矩阵报告：/tmp/matrix.json") == nil,
          "无截图不提供人工确认入口")
    check(CliAction.reviewMatrixCandidate(profileID: "sample", reportPath: "/tmp/r.json", attempt: 1).arguments()
          == ["probe", "sample", "--apply-matrix-report", "/tmp/r.json", "--review-attempt", "1", "--confirm-apply"],
          "截图人工确认只选择绑定报告的指定候选")
    check(MatrixProbeResult.parse("矩阵结论：bios / ide 可以启动（login_ready）\n矩阵报告：relative.json\n") == nil,
          "GUI 不接受相对报告路径")
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
    check(decoded?.pack == nil, "旧分发目录没有内容包摘要")
    check(GuiParsing.decodeDistReport("not json") == nil, "非法 JSON 返回 nil")

    // MARK: 内容包摘要与安装动作

    let packJSON = """
    {"ok": true, "entries": [], "problems": [], "summary": {"total": 3, "ok": 3, "failed": 0},
     "dir": "/tmp/pack", "manifest": "/tmp/pack/DISTRIBUTION.json",
     "pack": {"id": "mini-pack", "name": "Mini 测试包", "version": "1.0.0",
      "requires_runner": ">=0.1.1", "runner": "0.1.1", "runner_satisfied": true,
      "notes": [], "docs": ["使用说明.md"], "claims": ["mini-test"],
      "claims_note": "包内验收声明仅供参考",
      "nodes": [{"profile": "mini-test", "has_base": true, "has_nvram": false,
        "name": "Mini Test", "architecture": "x86_64", "firmware": "bios",
        "memory_mb": 1024, "cpus": 1,
        "local": {"kind": "absent", "sha256": null}}]}}
    """
    let packReport = GuiParsing.decodeDistReport(packJSON)
    check(packReport?.pack?.id == "mini-pack", "解析内容包摘要")
    check(packReport?.pack?.nodes.first?.memoryMb == 1024, "解析包节点资源需求")
    check(packReport?.pack?.nodes.first?.local?.kind == "absent", "解析包节点本机冲突预览")
    check(packReport?.pack?.docs == ["使用说明.md"], "解析包说明文件清单")
    check(packReport?.pack?.claims?.isEmpty == false, "解析包内验收声明")
    let builtinPackJSON = packJSON.replacingOccurrences(of: "\"kind\": \"absent\"", with: "\"kind\": \"builtin\"")
    check(GuiParsing.decodeDistReport(builtinPackJSON)?.pack?.nodes.first?.local?.kind == "builtin",
          "内置同名冲突以 builtin 标注")
    check(CliAction.distInstall(dir: "/tmp/内容 包").arguments()
          == ["dist", "install", "--dir", "/tmp/内容 包", "--json"], "内容包安装走 dist install --json")
    check(CliAction.distInstall(dir: "/tmp/pack").controlsImport, "内容包安装可取消（复用导入通道）")
    check(CliAction.distVerify(dir: "/tmp/pack").arguments()
          == ["dist", "verify", "--dir", "/tmp/pack", "--json", "--conflicts"],
          "校验带 --conflicts：包摘要能提前显示冲突预览")
    check(CliAction.distVerify(dir: "/tmp/pack").preservesRawOutputOnFailure,
          "dist verify 失败时保留原始输出供结构化解码")
    check(!CliAction.importNode(node: .smoke, sourcePath: "a", manifestPath: "b").preservesRawOutputOnFailure,
          "导入失败仍使用通用错误文案")

    // 决策门：校验失败/输出不可解码时必须中止，绝不回退普通镜像 onboard。
    let okPackReport = GuiParsing.decodeDistReport(packJSON)!
    let tamperedJSON = """
    {"ok": false, "entries": [{"file": "smoke-mini-base.qcow2", "profile": "smoke-mini",
    "role": "base", "expected_size": 267649024, "expected_sha256": "7620a", "size": 100,
    "sha256": "7efdf", "status": "sha256-mismatch", "problem": "SHA-256 不一致"}],
    "problems": ["smoke-mini-base.qcow2: SHA-256 不一致（清单 7620a…，实际 7efdf…）"],
    "summary": {"total": 3, "ok": 2, "failed": 1}, "dir": "/tmp/pack",
    "manifest": "/tmp/pack/DISTRIBUTION.json",
    "pack": {"id": "smoke-mini-pack", "name": "Smoke Mini 内容包", "version": "1.0.0",
      "requires_runner": ">=0.1.1", "runner": "0.1.1", "runner_satisfied": true,
      "nodes": [{"profile": "smoke-mini", "has_base": true, "has_nvram": false}]}}
    """
    let failedPackReport = GuiParsing.decodeDistReport(tamperedJSON)
    check(failedPackReport?.ok == false && failedPackReport?.pack != nil,
          "篡改失败 JSON 可结构化解码，含包摘要")
    check(failedPackReport?.problems.isEmpty == false
          && failedPackReport?.entries.first?.status == "sha256-mismatch",
          "失败报告携带问题明细与红色校验行")
    check(DistImportGate.decide(report: okPackReport, manifestExists: true) == .installPack,
          "校验通过且是内容包 → 单次安装")
    check(DistImportGate.decide(report: failedPackReport, manifestExists: true) == .abort,
          "校验失败 → 中止全部导入")
    check(DistImportGate.decide(report: nil, manifestExists: true) == .abort,
          "输出不可解码 → 中止全部导入（不得回退普通镜像路径）")
    check(DistImportGate.decide(report: okPackReport, manifestExists: false) == .abort,
          "无清单的普通目录不经此门导入")
    // 冲突预览文案：按哈希区分“一致跳过”与“不同拒绝”，内置同名红色拒绝。
    let sameSha = PackLocalStatus(kind: "user", sha256: "aa11")
    let diffSha = PackLocalStatus(kind: "user", sha256: "bb22")
    check(DistImportGate.conflictNote(local: sameSha, profilePackSha256: "aa11")
          == "同名候选内容一致，重复导入将跳过", "内容一致提示跳过而非冲突")
    check(DistImportGate.conflictNote(local: diffSha, profilePackSha256: "aa11")
          == "已有同名候选配置；内容不同将拒绝覆盖", "内容不同提示拒绝覆盖")
    check(DistImportGate.conflictNote(local: PackLocalStatus(kind: "builtin", sha256: nil),
                                      profilePackSha256: "aa11")?.contains("内置") == true,
          "内置同名提示拒绝")
    check(DistImportGate.conflictNote(local: PackLocalStatus(kind: "absent", sha256: nil),
                                      profilePackSha256: "aa11") == nil, "无占用不显示冲突")
    let installOutput = """
    CTFLAB_IMPORT_PROGRESS {"stage": "转换", "done": null, "total": null, "elapsed_seconds": 1.0, "cancellable": true}
    {
      "ok": true,
      "pack": {"id": "mini-pack", "name": "Mini 测试包", "version": "1.0.0",
        "requires_runner": ">=0.1.1", "runner": "0.1.1", "runner_satisfied": true,
        "nodes": [{"profile": "mini-test", "has_base": true, "has_nvram": false}]},
      "installed": ["mini-test"], "skipped_identical": [], "imported": ["mini-test"],
      "docs": ["使用说明.md"], "record": "/tmp/state/content-packs/mini-pack/pack.json"
    }
    """
    let installReport = PackInstallReport.parse(installOutput)
    check(installReport?.ok == true && installReport?.installed == ["mini-test"],
          "安装结果可从带进度行的输出中解析")
    check(installReport?.imported == ["mini-test"], "安装结果包含已导入节点")
    check(PackInstallReport.parse("错误：内容包校验失败") == nil, "失败输出不误解析为安装结果")

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
    check(status?.profiles.first?.boot == nil, "无 boot 字段的旧状态 JSON 仍可解析")

    let bootStatusJSON = """
    {"schema": 1, "state_dir": "/tmp/state", "profiles": [
     {"id": "kali-arm64", "name": "Kali", "imported": true, "running": true, "pid": 42,
      "boot": {"phase": "guest-boot", "phase_label": "系统引导", "overall": "booting",
               "elapsed_seconds": 12, "readiness_timeout_seconds": 240,
               "stages": [{"name": "process", "ok": true, "detail": "PID 42"},
                          {"name": "guest-boot", "ok": true, "detail": "已出现来宾活动信号"},
                          {"name": "display", "ok": false, "detail": "等待显示通道就绪"},
                          {"name": "network", "ok": false, "detail": "健康检查未全部通过"}]}},
     {"id": "smoke", "imported": false, "running": false}]}
    """
    let bootStatus = GuiParsing.decodeStatus(bootStatusJSON)
    let boot = bootStatus?.profiles.first?.boot
    check(boot?.phase == "guest-boot", "启动阶段 phase 解析")
    check(boot?.phaseLabel == "系统引导", "启动阶段中文标签解析")
    check(boot?.overall == "booting", "启动整体状态解析")
    check(boot?.stages?.count == 4, "四阶段列表解析")
    check(boot?.stages?.first { $0.name == "display" }?.ok == false, "显示阶段未就绪解析")
    check(boot?.displayText.contains("系统引导（12s/240s）") == true, "阶段展示文案带计时")
    check(boot?.isTimedOut == false, "booting 不标记超时")

    let timeoutBootJSON = """
    {"schema": 1, "state_dir": "/tmp/state", "profiles": [
     {"id": "kali-arm64", "imported": true, "running": true, "pid": 42,
      "boot": {"phase": "process", "phase_label": "进程启动", "overall": "timeout",
               "elapsed_seconds": 300, "readiness_timeout_seconds": 240,
               "stages": [], "diagnosis": {
                   "message": "启动后 300s（就绪超时 240s）仍未就绪",
                   "failed_checks": ["dhcp", "ssh:22"],
                   "log_path": "/tmp/log", "client_log_path": "/tmp/client-log",
                   "hint": "查看日志；stop 仅作用于该节点。"}}}]}
    """
    let timeoutBoot = GuiParsing.decodeStatus(timeoutBootJSON)?.profiles.first?.boot
    check(timeoutBoot?.isTimedOut == true, "超时整体状态解析")
    check(timeoutBoot?.displayText.contains("超时") == true, "超时展示带标记")
    check(timeoutBoot?.diagnosis?.failedChecks == ["dhcp", "ssh:22"], "超时诊断失败项解析")
    check(timeoutBoot?.diagnosis?.clientLogPath == "/tmp/client-log", "超时诊断客户端日志路径解析")

    // 第 8 项：统一节点状态推导、搜索匹配与显示客户端列。
    func statusProfile(id: String, imported: Bool = true, importState: String? = "registered",
                       running: Bool = false, pid: Int? = nil, stalePid: Int? = nil,
                       bootOverall: String? = nil, bootPhase: String? = nil) -> StatusProfile {
        let boot: BootSummary? = bootOverall.map {
            BootSummary(phase: bootPhase ?? "process", phaseLabel: bootPhase ?? "进程启动",
                        overall: $0, elapsedSeconds: 5, readinessTimeoutSeconds: 240,
                        stages: [], diagnosis: nil)
        }
        return StatusProfile(id: id, name: nil, builtin: false, imported: imported, importState: importState,
                             sourcePath: nil, running: running, pid: pid, logPath: nil, baseSHA256: nil,
                             stalePid: stalePid, boot: boot, spiceClient: nil)
    }
    check(NodeOperationalState.state(for: statusProfile(id: "a", imported: false,
                                                        importState: "not-imported")) == .notImported,
          "未导入节点状态")
    check(NodeOperationalState.state(for: statusProfile(id: "a", imported: false,
                                                        importState: "missing-base")) == .baseMissing,
          "基盘失效节点状态")
    check(NodeOperationalState.state(for: statusProfile(id: "a")) == .stopped, "已导入未运行状态")
    check(NodeOperationalState.state(for: statusProfile(id: "a", running: true, pid: 7,
                                                        bootOverall: "booting")) == .booting,
          "启动中节点状态")
    check(NodeOperationalState.state(for: statusProfile(id: "a", running: true, pid: 7,
                                                        bootOverall: "ready",
                                                        bootPhase: "network")) == .running,
          "运行中节点状态")
    check(NodeOperationalState.state(for: statusProfile(id: "a", running: true,
                                                        bootOverall: "timeout")) == .timedOut,
          "启动超时节点状态")
    check(NodeOperationalState.state(for: statusProfile(id: "a", stalePid: 9)) == .stale,
          "状态残留优先于其他判定")
    check(NodeOperationalState.state(for: statusProfile(id: "a", running: true, pid: 7,
                                                        bootOverall: "timeout")).isProblem,
          "超时状态标记为问题")
    check(NodeOperationalState.detailText(for: statusProfile(id: "a", running: true,
                                                             bootOverall: "booting",
                                                             bootPhase: "display")).contains("display"),
          "启动中详情附带阶段标签")

    check(NodeSearch.matches(statusProfile(id: "kali-arm64", imported: false,
                                           importState: "not-imported"), query: "  "),
          "空搜索匹配全部节点")
    check(NodeSearch.matches(statusProfile(id: "basic-pentesting-2"), query: "BASIC"),
          "搜索按 ID 大小写不敏感匹配")
    check(NodeSearch.matches(statusProfile(id: "x"), query: "x"), "按显示名匹配未知节点")
    check(!NodeSearch.matches(statusProfile(id: "smoke"), query: "kali"), "不匹配的搜索被过滤")
    check(NodeSearch.filter([statusProfile(id: "kali-arm64"), statusProfile(id: "smoke")],
                            query: "kali").count == 1, "过滤结果数量正确")

    let clientJSON = """
    {"schema": 1, "state_dir": "/tmp/state", "profiles": [
     {"id": "kali-arm64", "imported": true, "running": true, "pid": 42,
      "boot": {"phase": "display", "phase_label": "显示连接", "overall": "booting",
               "elapsed_seconds": 6, "readiness_timeout_seconds": 240, "stages": []},
      "spice_client": {"pid": 99, "alive": true, "display_ready": true}},
     {"id": "smoke", "imported": false, "running": false, "spice_client": null}]}
    """
    let clientStatus = GuiParsing.decodeStatus(clientJSON)
    check(clientStatus?.profiles.first?.spiceClient?.displayReady == true, "显示客户端 display_ready 解析")
    check(clientStatus?.profiles.last?.spiceClient == nil, "非 SPICE 节点客户端列为空")
    check(SpiceClientStatus.columnText(clientStatus?.profiles.first?.spiceClient) == "已连接",
          "客户端列文案：已连接")
    check(SpiceClientStatus.columnText(nil) == "—", "客户端列文案：非 SPICE 显示 —")
    let connecting = SpiceClientStatus(pid: 9, alive: true, displayReady: false)
    check(SpiceClientStatus.columnText(connecting) == "连接中", "客户端列文案：连接中")
    let dead = SpiceClientStatus(pid: 9, alive: false, displayReady: false)
    check(SpiceClientStatus.columnText(dead) == "未连接", "客户端列文案：未连接")
    check(SpiceClientStatus.columnText(SpiceClientStatus(pid: 9, alive: false,
                                                       displayReady: true)) == "未连接",
          "客户端已退出时历史就绪不能覆盖未连接")
    let closedDisplayJSON = """
    {"profiles":[{"id":"kali-arm64","imported":true,"running":true,"pid":42,
      "spice_client":{"pid":99,"alive":false,"display_ready":false}}]}
    """
    if let closedProfile = GuiParsing.decodeStatus(closedDisplayJSON)?.profiles.first {
        check(DisplaySessionGuidance.message(for: closedProfile)?.contains("虚拟机仍在运行") == true,
              "显示退出提示保留虚拟机运行事实")
        check(DisplaySessionGuidance.actionTitle(for: closedProfile) == "重新打开显示窗口",
              "显示退出按钮提供恢复而不是重启")
        check(DisplaySessionGuidance.canReconnect(closedProfile), "运行中的 SPICE 节点可显式重连")
        check(DisplaySessionGuidance.loginHelp(for: closedProfile)?.contains("Kali User") == true,
              "Kali 登录说明区分显示名称")
        check(DisplaySessionGuidance.sleepHelp(for: closedProfile)?.contains("不能保证唤醒来宾") == true,
              "重开显示不能被宣称为唤醒来宾")
        check(DisplaySessionGuidance.sleepHelp(for: statusProfile(id: "smoke")) == nil,
              "Kali 睡眠边界不套用其他靶机")
    } else { check(false, "恢复提示测试 JSON 必须成功解码") }
    if let connectedProfile = clientStatus?.profiles.first {
        check(DisplaySessionGuidance.message(for: connectedProfile)?.contains("不代表已登录") == true,
              "已连接不能误报来宾已登录")
        check(DisplaySessionGuidance.actionTitle(for: connectedProfile) == "打开显示窗口",
              "已有客户端保持打开窗口动作")
    }
    check(DisplaySessionGuidance.message(for: statusProfile(id: "a")) == nil,
          "已停止节点不显示仍运行提示")
    check(!DisplaySessionGuidance.canReconnect(statusProfile(id: "a")), "停止或无 SPICE 的节点不提供重连按钮")
    check(DisplaySessionGuidance.loginHelp(for: statusProfile(id: "smoke")) == nil,
          "靶机不展示 Kali 登录说明")

    var library = NodeLibraryPreferences()
    let resourceJSON = """
    {"memory_mb": 2048, "cpus": 2, "cpu_percent": 130.5, "rss_mb": 600.2, "acceleration": "hvf"}
    """
    let resourceStatus = try! JSONDecoder().decode(NodeResourceStatus.self, from: Data(resourceJSON.utf8))
    check(resourceStatus.memoryMB == 2048 && resourceStatus.cpus == 2 && resourceStatus.cpuPercent == 130.5,
          "资源状态解析保留实际配置和多核 CPU 口径")
    let unknownResource = try! JSONDecoder().decode(NodeResourceStatus.self, from: Data("{}".utf8))
    check(unknownResource.rssMB == nil && unknownResource.cpuPercent == nil,
          "资源采样未知不转换为零")
    library.favorites.insert("smoke")
    library.setGroup("  Web 课程  ", for: "smoke")
    check(library.groups["smoke"] == "Web 课程", "分组去首尾空格保留内部空格")
    library.lastUsed["kali-arm64"] = Date(timeIntervalSince1970: 100)
    let savedCourse = NodeCourse(name: "  教学  ", profileIDs: ["smoke", "smoke", "kali-arm64"])
    library.courses.append(savedCourse)
    check(savedCourse.name == "教学" && savedCourse.profileIDs.count == 2, "课程名称与节点去重")
    let libraryData = try! JSONEncoder().encode(library)
    check((try! JSONDecoder().decode(NodeLibraryPreferences.self, from: libraryData)) == library,
          "收藏分组最近记录与课程持久化往返")
    let libraryNodes = [statusProfile(id: "kali-arm64"), statusProfile(id: "smoke")]
    check(library.ordered(libraryNodes, recentFirst: true).first?.id == "smoke", "收藏优先于最近使用")
    library.favorites.removeAll()
    check(library.ordered(libraryNodes, recentFirst: true).first?.id == "kali-arm64", "最近使用优先")
    check((try! CourseLaunchRules.pending(savedCourse, profiles: libraryNodes)).count == 2,
          "课程组合生成已导入待启动节点")
    check((try! CourseLaunchRules.pending(savedCourse, profiles: [statusProfile(id: "kali-arm64", running: true),
                                                               statusProfile(id: "smoke")])) == ["smoke"],
          "课程组合跳过已运行节点")
    do {
        _ = try CourseLaunchRules.pending(savedCourse, profiles: [statusProfile(id: "smoke")])
        check(false, "缺失课程节点必须拒绝")
    } catch { check(true, "缺失课程节点不部分执行") }
    do {
        _ = try CourseLaunchRules.pending(NodeCourse(name: "", profileIDs: ["smoke"]), profiles: libraryNodes)
        check(false, "空名称组合必须拒绝")
    } catch { check(true, "拒绝空名称组合") }

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
    resetState.configuredProfileIDs = Set(LabNode.required.map(\.rawValue))
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

    // MARK: 登记标签去重（同名登记附 ID）与镜像文件夹扫描

    check(LabNode.displayLabel(for: "kali-arm64") == "Kali Linux ARM64（kali-arm64）",
          "已知课程节点显示名附 ID")
    check(LabNode.displayLabel(for: "unnamed-node") == "unnamed-node",
          "登记名与 ID 相同时不加后缀")
    check(LabNode.displayLabel(for: "kali-arm64", name: "Webserver") == "Webserver（kali-arm64）",
          "登记名与 ID 不同时附 ID")
    check(LabNode.displayLabel(for: "webserver-e2e", name: "Webserver") == "Webserver（webserver-e2e）",
          "历史同名登记通过 ID 后缀区分")

    let scanDir = URL(fileURLWithPath: NSTemporaryDirectory())
        .appendingPathComponent("ctflab gui scan test")
    try? FileManager.default.createDirectory(at: scanDir, withIntermediateDirectories: true)
    for name in ["b.vmdk", "a.QCOW2", "notes.txt", "c.ova"] {
        FileManager.default.createFile(atPath: scanDir.appendingPathComponent(name).path,
                                       contents: Data([0x01]))
    }
    let scanned = ImageFolderScanner.scan(scanDir.path)
    check(scanned.map(\.fileName) == ["a.QCOW2", "b.vmdk", "c.ova"],
          "只扫描支持的镜像扩展名并按名称排序")
    check(ImageFolderScanner.scan("/definitely/not/exist/ctflab") == [],
          "不存在的目录返回空（空文件夹为合法状态）")
    try? FileManager.default.removeItem(at: scanDir)

    check(CliAction.deregisterProfile(profileID: "webserver-e2e").arguments()
          == ["deregister", "webserver-e2e"], "移除登记命令拼接")

    check(CliAction.runProfiles(profileIDs: ["kali-arm64"], clipboard: true).arguments()
          == ["run", "kali-arm64", "--clipboard"], "剪贴板共享打开时附加 --clipboard")
    check(CliAction.runProfiles(profileIDs: ["kali-arm64"], clipboard: false,
                                displayQuality: "smooth").arguments()
          == ["run", "kali-arm64", "--display-quality", "smooth"], "清晰度参数透传")
    check(CliAction.onboardAuto(sourcePath: "/tmp/a/kali-base.qcow2", profileID: "kali-base")
          .arguments() == ["onboard", "/tmp/a/kali-base.qcow2", "--id", "kali-base"],
          "自动导入不带架构参数（由 inspect 推断）")
    check(ImageOnboardingRules.availableProfileID(sourcePath: "/tmp/smoke.qcow2",
          existingIDs: ["smoke"]) == "smoke-2", "仅登记同名节点不隐藏新来源")
    check(ImageOnboardingRules.availableProfileID(sourcePath: "/tmp/smoke.vmdk",
          existingIDs: ["smoke", "smoke-2"]) == "smoke-3", "同批导入 ID 不重复")
    check(ImageOnboardingRules.validProfileID(ImageOnboardingRules.availableProfileID(
          sourcePath: "/tmp/" + String(repeating: "a", count: 49) + ".qcow2",
          existingIDs: [String(repeating: "a", count: 49)])), "碰撞后 ID 仍在长度边界内")
    check(CliAction.runProfiles(profileIDs: ["kali-arm64"], clipboard: false,
          fileTransfer: true).arguments() == ["run", "kali-arm64", "--file-transfer"],
          "文件传输不隐式开启剪贴板")
    let pendingNodes = try! JSONDecoder().decode(StatusReport.self, from: Data("""
      {"profiles":[{"id":"smoke","imported":false,"running":false},
        {"id":"old","imported":true,"running":false,"source_path":"/tmp/old.qcow2"}],
        "state_dir":"/tmp/state"}
      """.utf8)).profiles
    let pendingFiles = [ImageLibraryEntry(fileName: "smoke.qcow2", path: "/tmp/smoke.qcow2", sizeBytes: 1),
                        ImageLibraryEntry(fileName: "old.qcow2", path: "/tmp/old.qcow2", sizeBytes: 1)]
    check(ImageOnboardingRules.pendingImages(pendingFiles, nodes: pendingNodes).map(\.fileName)
          == ["smoke.qcow2"], "仅过滤已导入来源，不过滤未导入的登记 ID")
    check(CliAction.removeImage(profileID: "smoke").arguments() == ["remove", "smoke"],
          "删除镜像命令拼接")

    let builtinStatusJSON = """
    {"profiles": [{"id": "webserver", "name": "Webserver", "builtin": true,
                   "imported": false, "running": false},
                  {"id": "webserver-e2e", "name": "Webserver", "builtin": false,
                   "imported": false, "running": false}], "state_dir": "/tmp/x"}
    """
    if let data = builtinStatusJSON.data(using: .utf8),
       let report = try? JSONDecoder().decode(StatusReport.self, from: data) {
        check(report.profiles.count == 2, "状态报告解析两个登记")
        check(report.profiles.first { $0.id == "webserver" }?.builtin == true,
              "内置课程包 builtin 标记可解析")
        check(report.profiles.first { $0.id == "webserver-e2e" }?.builtin == false,
              "用户登记 builtin=false 可解析")
    } else {
        check(false, "状态报告 builtin 字段解析失败")
    }

    check(RecoveryRules.validName("before-1") && !RecoveryRules.validName("../bad"), "恢复点名称拒绝路径")
    check(RecoveryRules.validName(RecoveryRules.checkpointName()), "自动保护点名称合法")
    check(CliAction.snapshot(profileID: "smoke", operation: "list").arguments()
          == ["snapshot", "list", "smoke", "--json"], "恢复点列表使用 JSON")
    let backupArgs = CliAction.backupReset(profileID: "smoke").arguments()
    check(backupArgs.count == 4 && RecoveryRules.validName(backupArgs[3]), "备份重置附安全名称")
    let stableBackup = CliAction.backupReset(profileID: "smoke")
    check(stableBackup.arguments() == stableBackup.arguments(), "备份命令与日志使用同一名称")
    check(CliAction.showDisplay(profileID: "smoke").arguments() == ["show", "smoke"], "打开显示不会拼接 run")
    check(CliAction.reconnectDisplay(profileID: "kali-arm64").arguments() == ["show", "kali-arm64", "--reconnect"], "卡住恢复仅重连显示")
    check(CliAction.runProfiles(profileIDs: ["kali-arm64"], clipboard: false, resourcePreset: "light")
          .arguments().suffix(2) == ["--resource-preset", "light"], "资源档位与显示权限独立")
    check(NodeStatusFilter.active.matches(statusProfile(id: "smoke", running: true)), "运行状态筛选")
    check(!NodeStatusFilter.active.matches(statusProfile(id: "smoke")), "不运行的节点不混入运行筛选")
    check(NodeStatusFilter.problems.matches(statusProfile(id: "smoke", imported: false, importState: "missing-base")), "基盘失效仍可被问题筛选找到")
    check(CliAction.preflight(profileID: "kali-arm64", resourcePreset: "light").arguments() == ["preflight", "kali-arm64", "--resource-preset", "light"], "预检保留选中节点资源档位")
    check(CliAction.displayDiagnose(profileID: "smoke").arguments() == ["display-diagnose", "smoke"], "诊断只针对选中节点")
    check(CliAction.updateRollback.arguments() == ["update", "rollback"], "回退不混入停止或重置命令")
    let failedPreflight = PreflightReport.decode("启动失败\n{\"ok\":false,\"checks\":[{\"name\":\"disk\",\"ok\":false,\"detail\":\"旧基盘\",\"hint\":\"先备份\"}]}")
    check(failedPreflight?.guidance.contains("先备份") == true, "错误包装后的预检提示可读")

    // --- Wintermute 场景入口：动作参数与状态解码 ---
    check(CliAction.scenarioStatus.arguments() == ["scenario", "status", "--json"], "场景状态走独立子命令并请求 JSON")
    check(CliAction.scenarioStop.arguments() == ["scenario", "stop"], "场景停止不携带强杀参数")
    check(CliAction.scenarioRecover(closeReset: true, releaseOrphan: false).arguments()
          == ["scenario", "recover", "--close-reset"], "收口重置事务参数逐项传递")
    check(CliAction.scenarioRecover(closeReset: false, releaseOrphan: true).arguments()
          == ["scenario", "recover", "--release-orphan"], "释放孤儿预约参数逐项传递")
    let scenarioStopped = """
    [{"instance_uuid":"12345678-1234-4234-8234-123456789abc","state_root":"/s",
      "active":{"generation":1,"descriptor":"prepared.json"},
      "reset":{"state":"active-observed","generation":1,"problem":null},
      "services":{"state":"stopped-observed","live":[],"absent":["inner","outer"],"unknown":[],"problem":null},
      "nodes":{"state":"stopped-observed","live":[],"absent":["kali","neuromancer","straylight"],"unknown":[],"problem":null},
      "reservations":[{"token":"t","generation":1,"ports":[50701,50702]}],
      "next":["scenario reset --new-generation 2"]}]
    """
    let stoppedReports = ScenarioReport.decode(scenarioStopped)
    check(stoppedReports?.count == 1, "场景状态 JSON 数组可解码")
    check(stoppedReports?.first?.summaryState == "已停止", "全部停止时如实显示已停止")
    check(stoppedReports?.first?.stateDetail.contains("prepared.json") == true, "细节包含活动指针描述")
    let scenarioUnknown = """
    [{"instance_uuid":"12345678-1234-4234-8234-123456789abc","state_root":"/s",
      "active":{"generation":1,"descriptor":"prepared.json"},"reset":null,
      "services":{"state":"recovery-required","live":["outer"],"absent":[],"unknown":["inner"],"problem":null},
      "nodes":{"state":"recovery-required","live":[],"absent":[],"unknown":["kali"],"problem":"身份失配"},
      "reservations":null,"next":["scenario stop"]}]
    """
    let unknownReports = ScenarioReport.decode(scenarioUnknown)
    check(unknownReports?.first?.summaryState == "待恢复", "不明归属显示待恢复而非运行")
    check(unknownReports?.first?.stateDetail.contains("inner") == true
          && unknownReports?.first?.stateDetail.contains("kali") == true, "待恢复细节列出不明成员")
    check(ScenarioReport.decode("not json") == nil, "坏输出不解码为报告")
    print("---")
    // Mac原生远程请求：原标识/当前状态/租约门，配置和载荷不进入命令行日志。
    do {
        let server = "00000000-0000-4000-8000-000000000001", instance = "00000000-0000-4000-8000-000000000002"
        let saved = try MacSavedTarget(.object(["id": .string("00000000-0000-4000-8000-000000000003"),
            "label": .string("课堂"), "target": .string(String(repeating: "a", count: 64)), "server_uuid": .string(server)]))
        let connection: MacRemoteJSON = .object(["target": .string(saved.target), "result": .object([
            "server_uuid": .string(server), "role": .string("student"), "instances": .array([.string(instance)]),
            "resource_leases": .bool(true), "display_available": .bool(true)])])
        let context = try MacRemoteContext(saved: saved, reply: connection)
        check(context.display && !context.assets && !context.evidence, "远程旧服务器未声明的能力保持禁用")
        check(!context.courses && !context.audit, "旧服务器管理能力默认关闭")
        check((try? MacRemoteRules.administration("course-list", context: context, values: [:])) == nil, "学生不能请求课程管理")
        let admin = try MacRemoteContext(saved: saved, reply: .object(["target": .string(saved.target), "result": .object([
            "server_uuid": .string(server), "role": .string("administrator"), "instances": .array([.string(instance)]),
            "resource_leases": .bool(false), "course_management": .bool(true), "audit_management": .bool(true)])]))
        check(admin.courses && admin.audit, "管理员显式能力启用课程与审计")
        let course = try MacRemoteRules.administration("course-preview", context: admin, values: ["offer_id": .string("web"), "instance_uuid": .string(instance)])
        check(course["target"].text == saved.target && course["instance_uuid"].text == instance, "课程预览绑定目标实例")
        check((try? MacRemoteRules.administration("course-preview", context: admin, values: ["offer_id": .string("web"), "instance_uuid": .string(instance), "path": .string("/outside")])) == nil, "课程管理拒绝客户端路径")
        check((try? MacRemoteRules.administration("audit-settle", context: admin, values: ["attempt_id": .string(instance), "review_sha256": .string("bad")])) == nil, "审计结清要求预览摘要")
        let auditPayload = try MacRemoteRules.administration("audit-settle", context: admin, values: ["attempt_id": .string(instance), "review_sha256": .string(String(repeating: "b", count: 64))])
        check((try? MacRemoteRules.administrationResult(.object(["target": .string(saved.target), "result": .object(["attempt_id": .string(instance), "original_worker_result": .string("unknown"), "vm_observed": .bool(true), "automatic_replay": .bool(false)])]), payload: auditPayload, context: admin)) == nil, "审计不能冒称已观察虚拟机")
        let status: MacRemoteJSON = .object(["instance_uuid": .string(instance), "state": .string("prepared"),
            "generation": .number(1), "state_revision": .number(5), "result": .string("completed")])
        let view: MacRemoteJSON = .object(["instance_uuid": .string(instance), "generation": .number(1), "status": status])
        check(!MacRemoteRules.allowed("start", view: view, context: context, instance: instance, lease: "", busy: false, pending: false), "未选择租约不能启动")
        let lease = "00000000-0000-4000-8000-000000000004"
        check(MacRemoteRules.allowed("start", view: view, context: context, instance: instance, lease: lease, busy: false, pending: false), "核验状态和租约后开放启动请求")
        check(!MacRemoteRules.allowed("reset", view: view, context: context, instance: instance, lease: lease, busy: false, pending: true), "未决请求阻止创建第二组变更标识")
        let operation = try MacRemoteRules.operation("start", view: view, context: context, instance: instance, lease: lease)
        check(operation["request"]["expected_state_revision"].integer == 5 && operation["request"]["expected_generation"].integer == 1, "远程变更绑定当前代次和版本")
        check(operation["request"]["parameters"]["allow_emulation"] == .bool(false) && operation["request"]["parameters"]["display"].text == "headless", "固定运行参数不开放宿主任意命令")
        check(MacRemoteRules.uuid(operation["request"]["request_id"].text ?? "") && MacRemoteRules.uuid(operation["request"]["idempotency_key"].text ?? ""), "新明确请求持独立UUID和幂等键")
        let reply: MacRemoteJSON = .object(["target": .string(saved.target), "result": view])
        check(try MacRemoteRules.overview(reply, context: context, instance: instance, previous: .null) == view, "当前目标的状态可接受")
        var wrong = reply
        wrong = .object(["target": .string(String(repeating: "b", count: 64)), "result": view])
        check((try? MacRemoteRules.overview(wrong, context: context, instance: instance, previous: view)) == nil, "错绑目标不能覆盖状态")
        let newer: MacRemoteJSON = .object(["instance_uuid": .string(instance), "generation": .number(1), "status": .object([
            "state_revision": .number(6), "state": .string("stopped")])])
        check(try MacRemoteRules.overview(reply, context: context, instance: instance, previous: newer) == newer, "旧修订回复不回退状态")
        let leaseStatus: MacRemoteJSON = .object(["owner_actions": .bool(true), "max_ttl_seconds": .number(3600),
            "expiry_action": .string("request-stop"), "leases": .array([])])
        check((try? MacRemoteRules.lease("lease-acquire", status: leaseStatus, context: context, instance: instance, selected: "", ttl: 60, consent: false)) == nil, "到期停止策略须明确勾选")
        let brokenLeases: MacRemoteJSON = .object(["owner_actions": .bool(true), "max_ttl_seconds": .number(3600), "expiry_action": .string("notify")])
        check((try? MacRemoteRules.lease("lease-acquire", status: brokenLeases, context: context, instance: instance, selected: "", ttl: 60, consent: true)) == nil, "缺少租约数组时不能猜测额度空闲")
        let acquire = try MacRemoteRules.lease("lease-acquire", status: leaseStatus, context: context, instance: instance, selected: "", ttl: 60, consent: true)
        check(acquire["ttl_seconds"].integer == 60 && acquire["expiry_action"].text == "request-stop", "租约沿服务器固定策略和期限")
        check((try? MacRemoteRules.lease("lease-acquire", status: leaseStatus, context: context, instance: instance, selected: "", ttl: 3601, consent: true)) == nil, "超服务器期限拒绝")
        let activeStatus: MacRemoteJSON = .object(["owner_actions": .bool(true), "max_ttl_seconds": .number(3600), "leases": .array([
            .object(["lease_id": .string(lease), "state": .string("active"), "time_state": .string("active")])])])
        let currentLeases: MacRemoteJSON = .object(["leases": .array([.object(["instance_uuid": .string(instance), "lease_id": .string(lease), "state": .string("active"), "time_state": .string("active")])])])
        check(MacRemoteRules.activeLease(currentLeases, selected: lease, instance: instance), "当前实例的活动租约可用于变更和显示")
        check(!MacRemoteRules.activeLease(.null, selected: lease, instance: instance), "租约读取失败时旧UUID不能维持开放")
        check(!MacRemoteRules.activeLease(currentLeases, selected: lease, instance: server), "其他实例租约不能开放当前操作")
        let renew = try MacRemoteRules.lease("lease-renew", status: activeStatus, context: context, instance: instance, selected: lease, ttl: 60, consent: false)
        check(renew["lease_id"].text == lease && MacRemoteRules.uuid(renew["renewal_id"].text ?? ""), "续期保留原租约并产生明确续期标识")
        let release = try MacRemoteRules.lease("lease-release", status: activeStatus, context: context, instance: instance, selected: lease, ttl: 0, consent: false)
        check(release["ttl_seconds"] == .null && release["lease_id"].text == lease, "释放不伪造TTL或停止请求")
        let raw = try MacRemoteJSON.object(["action": .string("save-target"), "config": .string("/private/ssh-identity.json")]).encoded()
        let action = CliAction.remoteClient(json: raw)
        check(action.arguments(stateDir: "/tmp/state a") == ["--state-dir", "/tmp/state a", "remote-client"], "远程载荷只经标准输入不拼接到命令行")
        check(action.privateRequest == raw.data(using: .utf8) && !action.displayCommand.contains("ssh-identity"), "远程命令日志不含配置或载荷")
        check(action.preservesRawOutputOnFailure, "远程错误保留结构化回复供核验")
        check(MacRemoteJSON.bool(true).integer == nil && MacRemoteJSON.number(1.5).integer == nil, "布尔和小数不能冒充修订整数")
        check((try? MacRemoteJSON.string(String(repeating: "a", count: 65537)).encoded()) == nil, "远程请求有64KiB边界")
    } catch { check(false, "Mac远程模型意外失败：\(error)") }

    let sceneAction = CliAction.scenarioClient(json: "{\"private-path\":\"hidden\"}")
    check(sceneAction.arguments() == ["scenario-client"], "本机场景固定命令")
    check(sceneAction.privateRequest != nil, "本机场景使用stdin")
    check(!sceneAction.displayCommand.contains("hidden"), "本机场景载荷不进入日志")
    check(sceneAction.preservesRawOutputOnFailure, "本机场景保留结构化失败")
    let genericAction = CliAction.genericClient(json: "{\"secret-path\":\"hidden\"}")
    check(genericAction.arguments() == ["generic-client"], "Mac通用入口固定命令")
    check(genericAction.privateRequest != nil, "Mac通用入口使用stdin")
    check(!genericAction.displayCommand.contains("hidden"), "Mac通用载荷不进入日志")
    check(genericAction.preservesRawOutputOnFailure, "Mac通用入口结构化失败")
    do {
        let source = try MacRemoteJSON.decode(#"{"schema":2,"scenario_id":"three-node-example","assets":{"linux":{"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","architecture":"x86_64","source":"local-test-fixture","license":"synthetic-only","verification":"unverified"}},"networks":{"outer":{"cidr":"10.80.0.0/24","uplink":"none"},"inner":{"cidr":"10.81.0.0/24","uplink":"none"}},"nodes":{"client":{"asset":"linux","cpus":1,"memory_mb":512,"firmware":"bios","disk_bus":"ide","interfaces":[{"id":"eth0","network":"outer","address":"10.80.0.10","mac":"derived","model":"e1000"}],"depends_on":["middle"]},"middle":{"asset":"linux","cpus":1,"memory_mb":512,"firmware":"bios","disk_bus":"ide","interfaces":[{"id":"eth0","network":"outer","address":"10.80.0.20","mac":"derived","model":"e1000"},{"id":"eth1","network":"inner","address":"10.81.0.20","mac":"derived","model":"e1000"}],"depends_on":["server"]},"server":{"asset":"linux","cpus":1,"memory_mb":512,"firmware":"bios","disk_bus":"ide","interfaces":[{"id":"eth0","network":"inner","address":"10.81.0.30","mac":"derived","model":"e1000"}],"depends_on":[]}},"policy":{"internet":false,"host_forwards":[],"failure":"preserve"}}"#)
        check(try MacGraphDraft.checked(source) == source, "原生图保留完整原清单")
        let design = MacDesignTopology.project(source) ?? .null
        check(design["topology"]["nodes"].items.count == 3, "设计总览保留真实三节点")
        check(design["topology"]["networks"] == source["networks"], "设计总览保留网段")
        check(design["topology"]["nodes"].items.first?["interfaces"].items.first?["planned_address"].text == "10.80.0.10", "设计地址映射不丢失")
        check(!MacObservationWindow.fresh(design), "设计总览不伪造当前运行采样")
        check(MacDesignTopology.project(.null) == nil, "无效设计不生成关系图")

        let recoveryTarget = "11111111-1111-4111-8111-111111111111"
        let recoveryView = try MacRemoteJSON.decode("{\"status\":{\"state\":\"process-running\",\"result\":\"completed\"},\"observations\":{\"middle\":{\"state\":\"process-running\"}},\"guest_agents\":{\"middle\":{\"containers\":true,\"last_action\":\"preparation-inspect\",\"last_result\":{\"state\":\"preparation-observed\",\"operation_id\":\"" + recoveryTarget + "\",\"can_resume\":true,\"automatic_replay\":false,\"resume_sha256\":\"" + String(repeating:"a",count:64) + "\"}}}}")
        let recoveryParams = try MacGuestRecovery.parameters(recoveryView,node:"middle",target:recoveryTarget,resume:true)
        check(recoveryParams["target_operation_id"].text == recoveryTarget && recoveryParams["expected_sha256"].text == String(repeating:"a",count:64), "来宾续建绑定当前核对摘要和原操作")
        check(try MacGuestRecovery.parameters(recoveryView,node:"middle",target:recoveryTarget,resume:false)["expected_sha256"] == .null, "只读核对不携带续建摘要")
        check((try? MacGuestRecovery.parameters(recoveryView,node:"middle",target:"bad",resume:true)) == nil, "拒绝错误原操作标识")
        check((try? MacGuestRecovery.parameters(recoveryView,node:"missing",target:recoveryTarget,resume:true)) == nil, "拒绝缺失来宾节点")
        check((try? MacGuestRecovery.parameters(recoveryView,node:"middle",target:"22222222-2222-4222-8222-222222222222",resume:true)) == nil, "不能借用其他准备记录的摘要")
        for pair in [("process-running","recovery-required"),("completed","accepted"),("preparation-inspect","status"),(String(repeating:"a",count:64),"bad")] {
            let changed = try MacRemoteJSON.decode(recoveryView.encoded().replacingOccurrences(of:pair.0,with:pair.1))
            check((try? MacGuestRecovery.parameters(changed,node:"middle",target:recoveryTarget,resume:true)) == nil, "拒绝过期状态或错误续建来源")
        }

        var editHistory = try MacGraphHistory(source);try editHistory.edit(.string("下一步"));editHistory.undo()
        check(editHistory.present == source && editHistory.canRedo,"撤销恢复精确配置原件")
        editHistory.redo();check(editHistory.present == .string("下一步"),"重做恢复已撤销配置")
        editHistory.undo();try editHistory.edit(.string("新分支"));check(!editHistory.canRedo,"新配置编辑清空重做")
        for number in 0..<40 { try editHistory.edit(.string(String(number))) }
        check(editHistory.past.count == 20,"配置历史最多20步")
        for _ in 0..<40 { editHistory.undo() };check(editHistory.future.count == 20,"撤销到历史边界不增加记录")
        let preservedHistory = editHistory
        do { try editHistory.edit(.string(String(repeating:"字",count:22000)));check(false,"超大草稿应拒绝") } catch { check(editHistory == preservedHistory,"超大草稿拒绝并保留原历史") }
        let windowStart = Date(timeIntervalSince1970:1793145600), formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime,.withFractionalSeconds]
        let timedView: MacRemoteJSON = .object(["freshness":.object(["schema":.number(1),"complete":.bool(true),"sampled_at":.string(formatter.string(from:windowStart)),"valid_until":.string(formatter.string(from:windowStart.addingTimeInterval(60)))])])
        check(MacObservationWindow.fresh(timedView,now:windowStart.addingTimeInterval(1)),"当前完整采样可显示现场状态")
        check(!MacObservationWindow.fresh(timedView,now:windowStart.addingTimeInterval(61)),"过期采样不冒充现场状态")
        check(!MacObservationWindow.fresh(timedView,now:windowStart.addingTimeInterval(-1)),"未来采样拒绝")
        check(!MacObservationWindow.fresh(MacObservationWindow.invalidated(timedView),now:windowStart.addingTimeInterval(1)),"查询失败使旧采样失效")
        check(!MacObservationWindow.fresh(.null),"缺失采样窗口拒绝")
        var mixedView = timedView
        if case .object(var value) = timedView, case .object(var window) = value["freshness"] { window["coherent"] = .bool(false); value["freshness"] = .object(window); mixedView = .object(value) }
        check(!MacObservationWindow.fresh(mixedView,now:windowStart.addingTimeInterval(1)),"采样期间发生变化即使complete为真也拒绝")
        let point = try MacGraphLayout.point(12,34), positions = Dictionary(uniqueKeysWithValues: MacGraphLayout.keys(source).map { ($0,point) })
        let layout = try MacGraphLayout.export(source,positions: positions)
        check(try MacGraphLayout.load(source,text: layout.encoded()) == positions, "布局旁车无损往返，不包含执行资产")
        check(layout["assets"] == .null && layout["scope"]["scenario_id"] == source["scenario_id"], "布局只绑定草稿标识及元素")
        check(try MacGraphLayout.point(-12,100000) == MacRemoteJSON.object(["x":.number(0),"y":.number(32000)]), "布局移动夹紧边界")
        check((try? MacGraphLayout.point(.nan,1)) == nil, "拒绝非有限布局坐标")
        var missing = positions; missing.removeValue(forKey: "node:client")
        check((try? MacGraphLayout.export(source,positions: missing)) == nil, "拒绝缺失布局元素")
        var outside = positions; outside["node:client"] = .object(["x":.number(4001),"y":.number(0)])
        check((try? MacGraphLayout.export(source,positions: outside)) == nil, "拒绝越界布局坐标")
        outside["node:client"] = .object(["x":.number(1.5),"y":.number(0)])
        check((try? MacGraphLayout.export(source,positions: outside)) == nil, "拒绝小数布局坐标")
        let foreign = try layout.encoded().replacingOccurrences(of: "three-node-example",with: "foreign")
        check((try? MacGraphLayout.load(source,text: foreign)) == nil, "拒绝其他草稿的布局")
        check((try? MacGraphLayout.load(source,text: String(repeating:" ",count:65537))) == nil, "布局载入64KiB边界")

        let added = try MacGraphDraft.addNode(source, name: "analysis", asset: "linux")
        check(source["nodes"]["analysis"] == .null && added["nodes"]["analysis"]["interfaces"].items.isEmpty, "新增节点只改草稿副本，待补全连接")
        let network = try MacGraphDraft.addNetwork(added, name: "analysis-net", cidr: "10.90.0.0/24")
        let linked = try MacGraphDraft.connect(network, node: "analysis", nic: nil, network: "analysis-net")
        check(linked["nodes"]["analysis"]["interfaces"].items.first?["address"].text == "10.90.0.1", "新网卡分配首个可用设计地址")
        check(linked["nodes"]["analysis"]["interfaces"].items.first?["mac"].text == "derived", "新增网卡保留派生MAC声明")
        check((try? MacGraphDraft.connect(linked, node: "analysis", nic: nil, network: "analysis-net")) == nil, "拒绝同节点重复网段连接")
        let moved = try MacGraphDraft.connect(linked, node: "analysis", nic: "eth0", network: "outer")
        check(moved["nodes"]["analysis"]["interfaces"].items.first?["address"].text == "10.80.0.1", "重新连线更新设计地址")
        let detached = try MacGraphDraft.disconnect(moved, node: "analysis", nic: "eth0")
        check(detached["nodes"]["analysis"]["interfaces"].items.isEmpty, "最后网卡可在草稿断开，完整后端再拒绝不完整清单")
        check((try? MacGraphDraft.addNetwork(source, name: "overlap", cidr: "10.80.0.0/25")) == nil, "拒绝重叠实验网段")
        check((try? MacGraphDraft.addNetwork(source, name: "public", cidr: "8.8.8.0/24")) == nil, "拒绝物理公网网段")
        check((try? MacGraphDraft.addNetwork(source, name: "host-bits", cidr: "10.90.0.1/24")) == nil, "拒绝非网段地址")
        check((try? MacGraphDraft.addNode(source, name: "Bad Name", asset: "linux")) == nil, "原生图拒绝错误标识")
        let removed = try MacGraphDraft.removeNode(source, name: "server")
        check(removed["nodes"]["middle"]["depends_on"].items.isEmpty && source["nodes"]["server"] != .null, "移除草稿节点清理依赖且保留原节点")
        check(linked["policy"] == source["policy"] && linked["assets"] == source["assets"], "拓扑编辑保留原资产与网络边界策略")
        var arm = source
        if case .object(var root) = arm, case .object(var assets) = root["assets"], case .object(var asset) = assets["linux"] {
            asset["architecture"] = .string("aarch64"); assets["linux"] = .object(asset); root["assets"] = .object(assets); arm = .object(root)
        }
        let armAdded = try MacGraphDraft.addNode(arm, name: "arm-node", asset: "linux")
        let armLinked = try MacGraphDraft.connect(armAdded, node: "arm-node", nic: nil, network: "outer")
        check(armLinked["nodes"]["arm-node"]["firmware"].text == "uefi" && armLinked["nodes"]["arm-node"]["interfaces"].items.first?["model"].text == "virtio-net-pci", "ARM新节点使用UEFI与VirtIO声明")
        var exhausted = try MacGraphDraft.addNetwork(source, name: "small", cidr: "10.90.0.0/30")
        exhausted = try MacGraphDraft.connect(exhausted, node: "client", nic: nil, network: "small")
        exhausted = try MacGraphDraft.connect(exhausted, node: "server", nic: nil, network: "small")
        check((try? MacGraphDraft.connect(exhausted, node: "middle", nic: nil, network: "small")) == nil, "网段地址耗尽时拒绝连接")
        let sized = try MacGraphDraft.resources(source, node: "client", cpus: 64, memory: 262144)
        check(sized["nodes"]["client"]["cpus"].integer == 64 && source["nodes"]["client"]["cpus"].integer == 1, "资源编辑只改副本且接受生产上界")
        check((try? MacGraphDraft.resources(source, node: "client", cpus: 0, memory: 512)) == nil && (try? MacGraphDraft.resources(source, node: "client", cpus: 65, memory: 512)) == nil, "CPU越界拒绝")
        check((try? MacGraphDraft.resources(source, node: "client", cpus: 1, memory: 255)) == nil && (try? MacGraphDraft.resources(source, node: "client", cpus: 1, memory: 262145)) == nil, "内存越界拒绝")
        check((try? MacGraphDraft.dependencies(source, node: "server", selected: ["client"])) == nil, "拒绝三节点间接依赖循环")
        check((try? MacGraphDraft.dependencies(source, node: "client", selected: ["client"])) == nil, "拒绝自依赖")
        check((try? MacGraphDraft.dependencies(source, node: "client", selected: ["server", "server"])) == nil, "拒绝重复依赖")
        check((try? MacGraphDraft.dependencies(source, node: "client", selected: ["missing"])) == nil, "拒绝不存在的依赖")
        let independent = try MacGraphDraft.dependencies(source, node: "client", selected: [])
        check(independent["nodes"]["client"]["depends_on"].items.isEmpty && source["nodes"]["client"]["depends_on"].items.count == 1, "移除启动依赖保留原件")
        check((try? MacGraphDraft.removeNetwork(source, name: "outer")) == nil, "已连接网段不能隐式断开或移除")
        let emptyNetwork = try MacGraphDraft.addNetwork(source, name: "empty", cidr: "10.91.0.0/24")
        check(try MacGraphDraft.removeNetwork(emptyNetwork, name: "empty") == source, "空闲网段移除语义完整往返")
        if let file = ProcessInfo.processInfo.environment["CTFLAB_GRAPH_TEST_EXPORT"], file.hasPrefix("/") {
            let configured = try MacGraphDraft.resources(linked, node: "analysis", cpus: 2, memory: 1024)
            let dependent = try MacGraphDraft.dependencies(configured, node: "analysis", selected: ["server"])
            try dependent.encoded().write(to: URL(fileURLWithPath: file), atomically: false, encoding: .utf8)
        }
    } catch { check(false, "原生拓扑草稿用例：\(error)") }
    do {
        let start = Date(timeIntervalSince1970: 1793200000)
        let formatter = ISO8601DateFormatter()
        let view = MacRemoteJSON.object(["generation":.number(1),"status":.object(["generation":.number(1),"result":.string("completed")]),
            "freshness":.object(["schema":.number(1),"complete":.bool(false),"coherent":.bool(true),"sampled_at":.string(formatter.string(from:start)),"valid_until":.string(formatter.string(from:start.addingTimeInterval(60)))]),
            "manifest":.object(["nodes":.object(["server":.object([:])])]),
            "supervision":.object(["server":.object(["logs":.object(["kind":.string("posix-fifo-v1"),"rearm_allowed":.bool(true),"source_identity":.string("running"),"receiver":.string("not-receiving")])])])])
        check(MacLogRecovery.allowed(view,node:"server",busy:false,now:start.addingTimeInterval(1)),"日志背压时仅重接日志可使用一致但不完整窗口")
        check(!MacObservationWindow.fresh(view,now:start.addingTimeInterval(1)),"日志恢复不开放其他依赖完整采样的操作")
        check(!MacLogRecovery.allowed(view,node:"server",busy:true,now:start.addingTimeInterval(1)),"并发时拒绝日志重接")
        check(!MacLogRecovery.allowed(view,node:"outside",busy:false,now:start.addingTimeInterval(1)),"拒绝其他节点日志重接")
        check(!MacLogRecovery.allowed(view,node:"server",busy:false,now:start.addingTimeInterval(61)),"过期日志恢复窗口拒绝")
    }
    print("共 \(checkCount) 项检查，失败 \(failureCount) 项")
    exit(failureCount == 0 ? 0 : 1)
    }

@main
struct GuiCoreTestRunner {
    static func main() {
        if CommandLine.arguments.count == 4, CommandLine.arguments[1] == "--cli-output-fixture" {
            cliOutputFixture(CommandLine.arguments[2], root: URL(fileURLWithPath: CommandLine.arguments[3])); return
        }
        if CommandLine.arguments.count == 2, CommandLine.arguments[1] == "--contract-vectors" {
            contractVectorMode(); return
        }
        runAll()
    }
}
