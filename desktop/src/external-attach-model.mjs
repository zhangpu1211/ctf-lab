// 外部攻击机接入模型：纯函数校验与展示推导；不发起网络操作。
// 登记/绑定契约与 tools/ctflab_external_attach.py 对应。

export const KIND = 'kali-l2-v1';

export function defaultRegistrationForm() {
  return { name: '', host: '127.0.0.1', port: '22', user: 'ctflab-attach',
           identity: '', machine_uuid: '', vendor: 'VMware, Inc.',
           product: 'VMware Virtual Platform', assistant_sha256: '' };
}

const HOST_PATTERN = /^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$/;
const USER_PATTERN = /^[a-z_][a-z0-9_-]{0,63}$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA_PATTERN = /^[0-9a-f]{64}$/;
const MAC_PATTERN = /^02(?::[0-9a-f]{2}){5}$/;

export function registrationFromForm(form) {
  return { schema: 1, kind: KIND, name: form.name.trim(), node_uuid: UUID_PATTERN.test(form.node_uuid ?? '') ? form.node_uuid : crypto.randomUUID(),
           machine_uuid: form.machine_uuid.trim(), vendor: form.vendor.trim(), product: form.product.trim(),
           ssh: { host: form.host.trim(), port: Number(form.port), user: form.user.trim(),
                  identity: form.identity.trim() },
           assistant_sha256: form.assistant_sha256.trim().toLowerCase() };
}

// 跨平台绝对路径：POSIX /、Windows盘符与UNC均为绝对；拒绝歧义或越权输入。
export function isAbsoluteHostPath(text) {
  return typeof text === 'string' && text.length > 0 && text.length <= 4096 &&
    (/^\//.test(text) || /^[A-Za-z]:[\\/]/.test(text) || /^\\\\[^\\]/.test(text));
}

export function validateRegistration(registration) {
  if (typeof registration !== 'object' || registration === null) return '登记信息不完整。';
  if (!registration.name || registration.name.length > 64) return '名称必填且不超过64字。';
  if (!UUID_PATTERN.test(registration.machine_uuid || '')) return '来宾机器UUID必须为标准UUID格式。';
  if (!registration.vendor || !registration.product) return '需要填写虚拟化厂商与产品以核验身份。';
  const ssh = registration.ssh || {};
  if (!HOST_PATTERN.test(ssh.host || '')) return 'SSH地址格式无效。';
  if (!Number.isInteger(ssh.port) || ssh.port < 1 || ssh.port > 65535) return 'SSH端口无效。';
  if (!USER_PATTERN.test(ssh.user || '')) return 'SSH用户名格式无效。';
  if (!ssh.identity || !isAbsoluteHostPath(ssh.identity)) return '需要绝对路径的本地私钥。';
  if (!SHA_PATTERN.test(registration.assistant_sha256 || '')) return '助手摘要必须为64位十六进制。';
  return null;
}

export function validateForm(form) {
  return validateRegistration(registrationFromForm(form));
}

// 槽位预览：只读展示当前计划的外部槽位与隔离边界。
export function slotSummary(slots) {
  if (!Array.isArray(slots) || slots.length === 0) {
    return { available: false,
             note: '当前计划未声明外部接入口。新实验需在场景网段声明 external 槽位；运行中的旧实验不热改，提示下次创建实验代次生效。' };
  }
  return { available: true,
           note: '外部攻击机使用静态预约地址；普通终端与已启动的图形程序不会自动进入实验网络。',
           items: slots.map(slot => ({ ...slot,
             label: `${slot.network} · ${slot.address ?? '未预约'} · ${slot.mac ?? ''}` })) };
}

const SESSION_LABELS = {
  idle: '未连接',
  connecting: '连接中',
  connected: '已连接',
  disconnected: '已断开',
  unknown: '状态未知：中转进程已退出且未写明原因，请核对现场后重连或清除。',
};

export function sessionView(session) {
  const state = session?.state ?? 'idle';
  return { state, text: SESSION_LABELS[state] ?? '状态待核验。',
           canConnect: ['idle', 'disconnected', 'unknown'].includes(state),
           canDisconnect: ['connecting', 'connected'].includes(state) };
}

// 诊断展开区：只展示白名单字段（协议/槽位/限额/会话），不输出宿主路径或凭据。
export function diagnosticsView(report) {
  if (!report || report.state !== 'external-attach-status') return [];
  const attachment = report.binding?.attachment;
  const lines = [];
  const family = report.binding?.registration?.identity_family;
  if (family) lines.push(`来宾身份家族：${family}（厂商白名单内核验，不凭IP授权）`);
  lines.push('数据面协议：ctflab-external-l2-v1 记录帧（type/seq/length）· 以太类型白名单 0x0800/0x0806');
  for (const slot of report.slots ?? []) {
    if (typeof slot.reserved_port === 'number') {
      lines.push(`槽位 ${slot.network}：${slot.address} · ${slot.mac} · 预留口 127.0.0.1:${slot.reserved_port}（hub 后端）`);
    } else {
      lines.push(`槽位 ${slot.network}：${slot.address} · ${slot.mac} · 本代次未预留接入口`);
    }
  }
  if (attachment?.limits) {
    lines.push(`限额：${attachment.limits.max_frames_per_second ?? 1000} 帧/秒 · 突发 ${attachment.limits.burst_frames ?? 250} · 累计 ${attachment.limits.max_bytes ?? 1073741824} 字节 · 会话 ${Math.round((attachment.limits.max_seconds ?? 7200) / 60)} 分钟 · MTU 1400`);
  }
  if (report.binding?.policy_sha256) lines.push(`策略摘要：${report.binding.policy_sha256.slice(0, 16)}…`);
  return lines;
}

export function statusView(report) {
  if (!report || report.state !== 'external-attach-status') return { ready: false, text: '状态未取得。' };
  const slots = slotSummary(report.slots);
  const binding = report.binding_valid
    ? { text: `已登记：${report.binding?.registration?.name ?? ''} → ${report.binding?.network_id ?? ''}（代次 ${report.binding?.generation}）`, stale: false }
    : report.binding
      ? { text: '登记已过期：计划或代次已变化，请重新预览并保存。', stale: true }
      : { text: '尚未登记外部攻击机。', stale: false };
  const session = sessionView(report.session);
  return { ready: true, slots, binding, session, diagnostics: diagnosticsView(report),
           connect: report.connect_supported === true,
           canConnect: report.connect_supported === true && session.canConnect,
           canDisconnect: session.canDisconnect,
           note: report.note ?? '' };
}

export function cliConnectHint(binding) {
  if (!binding || !binding_valid(binding)) return null;
  return 'python3 tools/ctflab_external_attach.py connect --registration <登记文件> --attachment <槽位文件> --policy <节点MAC列表> --secret <代次秘密> --endpoint 127.0.0.1:<预留端口>';
}

function binding_valid(binding) {
  return typeof binding === 'object' && binding !== null && binding.plan_sha256;
}
