"""生成并校验C05离线合成应急课程；学生证据与教师答案独立，不运行样本。"""
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile

MAX_FILE = 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def student_files():
    return {
        'evidence/web-access.log': '''# 合成数据；UTC；未对任何真实服务执行请求
2026-10-20T08:58:00Z src=192.0.2.10 method=GET path=/ status=200 request=r01
2026-10-20T09:00:00Z src=198.51.100.24 method=POST path=/login status=401 request=r02
2026-10-20T09:00:03Z src=198.51.100.24 method=POST path=/login status=401 request=r03
2026-10-20T09:00:06Z src=198.51.100.24 method=POST path=/login status=200 request=r04
2026-10-20T09:01:00Z src=198.51.100.24 method=POST path=/admin/settings status=200 request=r05
2026-10-20T09:02:00Z src=192.0.2.10 method=GET path=/ status=503 request=r06
2026-10-20T09:03:00Z src=203.0.113.9 method=GET path=/health status=200 request=r07
''',
        'evidence/auth-events.jsonl': '''{"timestamp":"2026-10-20T09:00:00Z","request":"r02","account":"training-admin","outcome":"failure","source":"198.51.100.24"}
{"timestamp":"2026-10-20T09:00:03Z","request":"r03","account":"training-admin","outcome":"failure","source":"198.51.100.24"}
{"timestamp":"2026-10-20T09:00:06Z","request":"r04","account":"training-admin","outcome":"success","source":"198.51.100.24","session_label":"synthetic-session-a"}
{"timestamp":"2026-10-20T09:01:00Z","request":"r05","account":"training-admin","outcome":"authorized","session_label":"synthetic-session-a"}
''',
        'evidence/change-audit.csv': '''timestamp,request,actor,object,old_value,new_value,result
2026-10-20T09:01:00Z,r05,training-admin,app.maintenance,false,true,applied
2026-10-20T08:50:00Z,maintenance-01,scheduled-job,cache.ttl,60,120,applied
''',
        'evidence/collection.json': json.dumps({
            'schema': 1, 'source': 'CTFLab手工编写的合成教学事件，非真实入侵或活体采集',
            'collector': 'ctflab-evidence-course-v2', 'created_at': '2026-10-30T00:00:00Z',
            'event_timezone': 'UTC', 'instance': 'synthetic-web-01', 'generation': 1,
            'clock': '合成时间轴一致；真实环境应另查时钟偏移',
            'coverage': '自制Web/认证/变更日志、6帧合成HTTP PCAP、360KiB FAT12数据卷；不是现场采集，无主机进程、完整握手/全量流量或更早认证记录',
            'pcap': '手工构造Ethernet/IPv4/TCP请求响应，非抓包；UTC；捕获窗口不含握手，地址均为文档示例',
            'disk': '手工构造FAT12数据卷，非真实主机盘，无可执行文件；快照标签09:04 UTC；目录DOS时间无指定时区，不可当独立UTC证据',
            'addresses': '全部为文档示例地址；不得对地址执行扫描',
            'credentials': '无真实凭据；session_label是非访问令牌的教学关联标签'}, ensure_ascii=False, indent=2),
        '学生任务.md': '''# C05：Web异常访问与配置变更溯源

建议用时60—90分钟。所有记录、PCAP和FAT12数据卷均为自制教学材料，无需虚拟机、联网、管理员权限、挂载磁盘或运行样本。

## 开始前

解压后在学生包目录执行`python -B verify.py`核验文件。保存原始ZIP及摘要。原件用于核验，另复制到自己的调查目录后阅读；不要在原件中改时间、加注释或删除记录。文本编辑器、表格软件和所附Python标准库查看器即可完成本课。verify.py仅含校验逻辑，没有教师答案；课程生成器供教师使用，不随学生材料分发。

向教师取得独立核对的student-manifest.sha256（对应MANIFEST.json），再执行`python -I -B workspace.py prepare /绝对路径/新的调查工作区 --manifest-sha256 清单的64位指纹`。只创建新目录：original是撤销写权限的证据快照，work是可写调查副本，reports用于自己的报告。原解压目录不改，已有工作区不覆盖，失败目录保留；文件权限不是不可篡改封存。Windows仅使用文件只读属性，不改变ACL，本课程尚无Windows原生验收。

结课时执行`python -I -B workspace.py inspect /绝对路径/新的调查工作区 --manifest-sha256 原指纹`，复核original的摘要和只读权限。该结果不检查你的报告、不认证发布者，也不证明证据是真实现场。仅在work里批注，把报告保存到reports；不要把报告加到original。工具全部只用Python标准库，不联网、不执行日志/样本，不依赖教师模块。

在work中执行`python -I -B inspect_samples.py --manifest-sha256 原指纹`，先核验整包再只读显示PCAP记录和FAT12根目录文件。输出可另存reports；不要重定向到original。该工具仅支持本课固定格式，不是通用恶意样本解析器。可选使用自己的离线抓包/取证工具交叉核对，不扫描地址、不挂载或启动disk.fat12。

## 场景

用户报告09:02左右网页无法使用，但健康检查仍能返回成功。你取得限定时间窗口的Web访问、认证和配置变更记录。时间均为UTC；需要北京时间时统一加8小时并保留原时间。

## 调查任务

1. 列出证据名称、摘要、来源、时间范围和缺失范围，说明校验通过能证明什么。
2. 整理至少六条事件的时间线，每条标明文件、行号或记录标识。
3. 区分HTTP返回成功、认证成功和授权后的配置变更，找出能跨日志关联的字段。
4. 解释网页503与健康检查200是否矛盾，给出最小证据链。
5. 列出可以确认的事实与不能确认的推断。仅凭失败后成功是否足以证明密码被暴力破解？
6. 提出证据保全、限制风险、恢复服务和复验方案。只写方案，不操作任何真实系统。
7. 引用PCAP的记录号和request字段，核对请求/响应与日志是否相符；说明缺失握手和合成流量的证据限制。
8. 引用FAT12的CONFIG.TXT、ACCESS.LOG与COLLECT.TXT，核对配置/日志副本/快照标签；区分内容里的UTC标签与无时区DOS目录时间，不把同源副本误当独立现场佐证。

## 提交

提交事件时间线、带证据引用的结论、至少三项不确定性、恢复与复验清单。引用原记录，避免把同一IP直接等同某个人。教师答案不在学生包中。

## 验收

校验失败先停下保留差异；调查副本的编辑不得改变原件摘要。以证据支持结论，不以猜中答案为唯一标准。
''',
        '调查报告模板.md': '''# 调查报告

调查人：____；调查时间/时区：____；证据包摘要：____。

## 证据登记

| 文件 | SHA-256 | 来源与范围 | 校验结果 |
|---|---|---|---|
| 待填写 | | | |

## 时间线

| 原时间/时区 | 事件 | 证据文件/记录 | 事实或推断 |
|---|---|---|---|
| 待填写 | | | |

## 结论与不确定性

待填写。

## 保全、处置与复验方案

待填写；不要修改证据原件。
''',
    }


TEACHER = '''# C05教师说明与答案

这些是人工编写的合成事件与无害PCAP/FAT12材料。课程验证覆盖包结构、摘要、只读快照与内部时间线/多证据关联，不是恶意样本运行或真实课堂效果验收。建议先让学生完成证据表，再讨论因果与归因限制。

## 预设事实

09:00:00与09:00:03同一示例源地址对training-admin认证失败；09:00:06的r04认证成功，产生教学关联标签synthetic-session-a。09:01的r05使用该标签获得授权，审计记录显示app.maintenance从false变为true。09:02普通首页返回503，09:03健康检查200。08:50的cache.ttl变更是背景噪声，现有材料未把它与异常相连。

## 可支持的结论

Web请求ID连接认证和变更审计，r05给出维护开关被应用的证据；这与首页503在时间与功能上相符。健康端点可独立于普通页面，200不证明整个业务可用。教学预设原因为维护模式，但真实调查仍应验证配置语义、应用日志和恢复效果。

## 不可推出的结论

两次失败后成功不能单独证明暴力破解成功；无口令来源、人员身份或客户端取证。地址不能直接等同具体人员。没有进程和文件证据，不能断言主机植入、横向移动或数据泄露。时间窗口之外的事件未知。摘要一致证明副本与清单匹配，不证明日志内容真实或采集完整。

## 评分建议（100分）

证据登记与原件保护20；准确时间线与跨文件引用25；认证/授权/配置影响区分20；不确定性15；可回退的处置与业务复验20。处置方案应先保全，再在授权范围核验会话、账户和配置，恢复后同时检查首页与健康接口；不要直接清空日志或把所有异常归为攻击。

## 分级提示

提示1：比较r04和r05在不同文件中的记录。提示2：找old_value/new_value。提示3：健康检查与普通页面不是同一个业务检查。
'''


def teacher_replay(files):
    """完整示例仅在教师包；引用原文件行号，不把预设原因当现场因果实测。"""
    register = '\n'.join('| '+name+' | '+sha(files[name])+' |'
                         for name in sorted(files) if name.startswith('evidence/'))
    return '''# C05逐条证据复盘示例

这是项目作者依据自制文本整理的示例报告，非独立学生/课堂试点结果。先让学生完成报告，再单独分发本文件。无真实攻击、活体采集或第三方镜像。源为本项目新编事件；时间均UTC，需本地时间时统一加8小时并保留原值。collection.json限定覆盖范围；摘要匹配不证明真实性、完整采集或发布者身份。

## 证据登记

| 原文件 | SHA256 |
|---|---|
''' + register + '''

## 按时间重排的原事件

| UTC | 事件与引用 | 可确认的范围 |
|---|---|---|
| 08:50:00 | change-audit.csv第3行，maintenance-01 | scheduled-job改变cache.ttl，未见与异常直接关联 |
| 08:58:00 | web-access.log第2行，r01 | 示例普通来源首页GET返回200 |
| 09:00:00 | web-access.log第3行、auth-events.jsonl第1行，r02 | 198.51.100.24的training-admin认证失败，HTTP401 |
| 09:00:03 | web-access.log第4行、auth-events.jsonl第2行，r03 | 同一示例地址再次失败，不证明暴力破解 |
| 09:00:06 | web-access.log第5行、auth-events.jsonl第3行，r04 | 认证成功，关联标签synthetic-session-a；不是访问令牌 |
| 09:01:00 | web-access.log第6行、auth-events.jsonl第4行、change-audit.csv第2行，r05 | 同标签请求授权，app.maintenance从false变为true，结果applied |
| 09:02:00 | web-access.log第7行，r06 | 普通首页返回503；与09:02用户报告一致，但单条记录不证明所有用户受影响 |
| 09:03:00 | web-access.log第8行，r07 | /health返回200，仅证明该请求的健康端点响应 |

## PCAP与磁盘交叉核对

traffic.pcap记录1/2对应r05的POST /admin/settings与200响应，正文maintenance=true；记录3/4对应r06首页请求与503，记录5/6对应r07健康检查与200。每组以X-Lab-Request与日志request关联，IP与HTTP含义仍须分别核对。这六帧是手工编写的以太网/IPv4/TCP字节，不是现场抓包；没有握手、登录凭据或完整会话，不能据此证明认证身份或真实传输发生。

disk.fat12为360KiB无可执行文件的自制FAT12数据卷。CONFIG.TXT第1行maintenance=true、第2行cache_ttl=120；ACCESS.LOG与所给web-access.log逐字相同，COLLECT.TXT给出合成快照标签09:04 UTC及时间限制。目录时间编码09:04但没有时区，不能直接称UTC。日志副本、网络材料和磁盘均来自同一教学作者，不是三个独立现场来源；磁盘内容只能表明给定合成快照中的状态，不能独自证明09:01变更的真实因果或时钟准确性。全程用所附只读查看器，不挂载或启动磁盘。

## 结论、反证与限制

认证r04通过session_label与授权r05相连，r05再通过request与配置审计相连。HTTP200、认证success、授权authorized和审计applied是不同证据层，不能只看返回码。维护模式与首页503在时间/功能上相符，健康接口200不与此矛盾；教学预设原因为维护模式，但材料没有应用实现/配置语义与恢复后业务记录，现场因果仍应独立验证。

不能确认：密码如何取得、操作者身份、窗口外认证尝试、主机植入、横向移动或数据泄露。至少上述六项未知，不以相同IP等同同一个人。无会话原令牌/全量流量/主机进程和更早记录；不能因未给出就断言不存在。后台TTL变化是背景线索，应查但不能先当根因。UTC与北京时间换算不改变事件顺序；真实环境需查时钟偏差，不能把合成一致时钟当现场证明。

## 仅作方案的保全、处置、恢复与复验

1. 保存原ZIP、外部摘要与清单指纹；核验只读original，调查和报告只写work/reports。记录校验结果、来源范围和原时区；不删日志/改原时间。失败保留差异，不用重新生成包替代原件。
2. 在实际授权内另取应用配置语义、登录/会话/变更审批和应用日志；先保全再决定撤销会话或限制账户，使用可回退方案。不要对示例地址扫描，也不在本课执行账户或配置变更。
3. 经授权确认维护模式是否导致症状，保留原配置备份后选择恢复方案；记录变更人/时间/范围、回退条件。现有证据不允许直接宣布已恢复。
4. 复验普通首页、登录后核心业务、配置值及健康接口，分别保留结果；只有健康200不足以关闭事故。观察新时间窗口是否复发，必要时回退并继续调查。

## 教师复盘顺序与评分

先核对摘要/只读与来源20分；按上述8条事件核对排序和跨文件引用25分；区分认证/授权/配置/业务影响20分；至少3项不确定性15分；保全、授权/回退与首页/健康分别复验20分。能用证据说明不同合理假设也可得分，不以猜中“攻击者”或固定关键词为唯一标准。本示例不实现自动打分、自动处置或声称真实课堂通过。
'''


def archive(path, files):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED) as output:
        for name, raw in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (2026, 10, 23, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100444 << 16
            output.writestr(entry, raw)


def build(destination):
    destination = Path(destination)
    destination.mkdir(mode=0o700, exist_ok=False)
    files = {name: value.encode('utf-8') for name, value in student_files().items()}
    from ctflab_evidence_samples import pcap_sample, fat_sample, inspector_source
    files['evidence/traffic.pcap'] = pcap_sample()
    files['evidence/disk.fat12'] = fat_sample(files['evidence/web-access.log'])
    files['inspect_samples.py'] = inspector_source().encode('utf-8')
    # 学生只收到独立校验器；不能复制含TEACHER常量的整个课程生成器。
    verifier = ('import hashlib,json,os,stat\nfrom pathlib import Path,PurePosixPath\n'
                f'MAX_FILE={MAX_FILE}\nMAX_TOTAL={MAX_TOTAL}\n' + inspect.getsource(sha) + '\n'
                + inspect.getsource(verify) + '\n'
                + "if __name__ == '__main__':\n    try:\n        print(json.dumps(verify(Path(__file__).resolve().parent),ensure_ascii=False))\n"
                  "    except (OSError,ValueError,TypeError,KeyError):\n        print('校验失败；保留原件并核对清单。')\n        raise SystemExit(2)\n")
    files['verify.py'] = verifier.encode('utf-8')
    from ctflab_evidence_workspace import standalone_source
    files['workspace.py'] = standalone_source().encode('utf-8')
    manifest = {'schema': 1, 'course': 'c05-synthetic-web-01', 'kind': 'synthetic-offline-evidence-v2', 'content_version': 2,
                'classroom_verified': False, 'source': '项目内新编教学样例；未公开发布',
                'files': {name: {'sha256': sha(raw), 'bytes': len(raw)} for name, raw in files.items()}}
    files['MANIFEST.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    archive(destination / 'C05-student.zip', files)
    teacher = {'教师说明与答案.md': TEACHER.encode('utf-8'),
               '逐条证据复盘.md': teacher_replay(files).encode('utf-8'),
               'student-manifest.sha256': (sha(files['MANIFEST.json']) + '\n').encode()}
    archive(destination / 'C05-teacher.zip', teacher)
    (destination/'student-manifest.sha256').write_text(sha(files['MANIFEST.json'])+'\n', encoding='utf-8')
    sums = {name: sha((destination / name).read_bytes()) for name in ('C05-student.zip', 'C05-teacher.zip')}
    (destination / 'SHA256SUMS.json').write_text(json.dumps(sums, indent=2), encoding='utf-8')
    return sums


def verify(root):
    root = Path(root).absolute()
    def linked(path):
        try:info = path.lstat()
        except FileNotFoundError:return False
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)
    if any(linked(p) for p in (root, *root.parents)):
        raise ValueError('拒绝链接路径')
    manifest_path = root / 'MANIFEST.json'
    def read(path):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
            raise ValueError('文件类型或大小无效')
        with path.open('rb') as stream:
            raw = stream.read(MAX_FILE+1)
        if len(raw) > MAX_FILE:
            raise ValueError('文件超限')
        return raw
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('重复字段')
            result[key] = value
        return result
    manifest = json.loads(read(manifest_path), object_pairs_hook=unique)
    if (type(manifest) is not dict or type(manifest.get('schema')) is not int or manifest['schema'] != 1
            or manifest.get('kind') not in ('synthetic-text-only', 'synthetic-offline-evidence-v2')
            or manifest.get('classroom_verified') is not False
            or (manifest.get('kind') == 'synthetic-offline-evidence-v2' and
                (type(manifest.get('content_version')) is not int or manifest['content_version'] != 2))):
        raise ValueError('清单无效')
    files = manifest.get('files')
    if type(files) is not dict or not 1 <= len(files) <= 64:
        raise ValueError('文件清单无效')
    total = 0
    for name, expected in files.items():
        path = PurePosixPath(name)
        if (not isinstance(name, str) or path.is_absolute() or path.as_posix() != name
                or '..' in path.parts or '\\' in name or ':' in name or name == 'MANIFEST.json'):
            raise ValueError('路径无效')
        target = root.joinpath(*path.parts)
        if any(linked(p) for p in (target, *target.parents)):
            raise ValueError('拒绝链接')
        raw = read(target)
        total += len(raw)
        if (total > MAX_TOTAL or type(expected) is not dict or set(expected) != {'sha256', 'bytes'}
                or type(expected['bytes']) is not int or expected['bytes'] != len(raw) or expected['sha256'] != sha(raw)):
            raise ValueError('摘要或长度不符')
    actual = set()
    for directory, dirs, names in os.walk(root, followlinks=False):
        if len(actual) + len(dirs) + len(names) > 128:
            raise ValueError('额外文件过多')
        if any(linked(Path(directory) / name) for name in dirs):
            raise ValueError('拒绝链接目录')
        actual.update((Path(directory) / name).relative_to(root).as_posix() for name in names)
    if actual != set(files) | {'MANIFEST.json'}:
        raise ValueError('存在未登记文件')
    return {'integrity_verified': True, 'files': len(files), 'synthetic': True, 'classroom_verified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'verify', 'prepare', 'inspect'))
    parser.add_argument('directory', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--manifest-sha256')
    args = parser.parse_args(argv)
    try:
        if args.action in ('build', 'verify'):
            if args.destination is not None or args.manifest_sha256 is not None:raise ValueError('未知操作参数')
            result = build(args.directory) if args.action == 'build' else verify(args.directory)
        else:
            from ctflab_evidence_workspace import prepare, inspect_workspace
            if args.manifest_sha256 is None:raise ValueError('须提供清单指纹')
            if args.action == 'prepare':
                if args.destination is None:raise ValueError('须提供新目录')
                result = prepare(args.directory, args.destination, args.manifest_sha256)
            else:
                if args.destination is not None:raise ValueError('未知操作参数')
                result = inspect_workspace(args.directory, args.manifest_sha256)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        print('证据包操作失败，保留已有文件；请核对路径与清单。')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
