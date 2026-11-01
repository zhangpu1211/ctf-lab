"""封存已完成PCAP及白名单生命周期时间线；只写新的本地证据目录。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctflab_contract import require, canonical, uuid_text
from ctflab_generation_store import private_directory, digest
from ctflab_runtime_inventory import check_path, hash_file
from ctflab_tls_endpoint import guard

MAX_CAPTURE = 1024**3
EVENTS = ('start.intent.json', 'stop.intent.json', 'stop.result.json',
          'supervisor-fault.request.json', 'supervisor-fault.applied.json',
          'supervisor-fault.exit.json', 'observer-exit.json', 'exit.json')


def stable(path, maximum):
    path = Path(path).absolute(); info = check_path(path)
    require(path.is_file() and info.st_nlink == 1 and info.st_size <= maximum)
    return info, hash_file(path, info)


def read_capture(path, binding):
    """只接受已封口的项目Ethernet PCAP；不把丢帧计数当作完整采集证明。"""
    path = Path(path).absolute()
    metadata = path.with_suffix(path.suffix+'.capture.json')
    _, metadata_sha = stable(metadata, 16384)
    value = json.loads(metadata.read_bytes())
    require(type(value) is dict and value.get('binding') == binding, 'identity-unknown')
    for field in ('max_bytes', 'bytes_written', 'frames_written', 'frames_dropped_quota', 'frames_truncated_snaplen'):
        require(type(value.get(field)) is int and value[field] >= 0)
    info, sha = stable(path, MAX_CAPTURE)
    require(24 <= info.st_size == value['bytes_written'] <= value['max_bytes'] <= MAX_CAPTURE)
    count = truncated = 0; first = last = None
    with path.open('rb') as source:
        header = source.read(24)
        require(len(header) == 24)
        magic, major, minor, zone, sigfigs, snaplen, network = struct.unpack('<IHHIIII', header)
        require((magic, major, minor, network) == (0xA1B2C3D4, 2, 4, 1) and 1 <= snaplen <= 65535)
        consumed = 24
        while consumed < info.st_size:
            raw = source.read(16); require(len(raw) == 16)
            seconds, micros, captured, original = struct.unpack('<IIII', raw)
            require(micros < 1000000 and 0 <= captured <= min(snaplen, original)
                    and consumed+16+captured <= info.st_size)
            require(len(source.read(captured)) == captured)
            moment = seconds*1000000+micros
            first = moment if first is None else min(first, moment)
            last = moment if last is None else max(last, moment)
            count += 1; truncated += int(captured < original); consumed += 16+captured
        require(source.read(1) == b'')
    require(count == value['frames_written'] and truncated == value['frames_truncated_snaplen'])
    require(stable(path, MAX_CAPTURE)[1] == sha and stable(metadata, 16384)[1] == metadata_sha, 'state-conflict')
    return {'sha256': sha, 'size': info.st_size, 'metadata_sha256': metadata_sha,
            'capture': value, 'packet_time_range_us': [first, last], 'clock_verified': False}


def lifecycle(attempt, binding):
    attempt = guard(Path(attempt).absolute())
    launch = attempt/'launch.json'; process = attempt/'binding.json'
    _, launch_sha = stable(launch, 1024**2); _, process_sha = stable(process, 16384)
    raw = json.loads(launch.read_bytes()); bound = json.loads(process.read_bytes())
    require(raw['plan_sha256'] == binding['plan_sha256'] and raw['node'] == binding['node']
            and bound['launch_sha256'] == launch_sha, 'identity-unknown')
    # 事件只导出固定的状态字段；argv、磁盘路径、PID及证书材料不进入时间线。
    events = []
    for name in EVENTS:
        path = attempt/name
        if not path.exists(): continue
        info, sha = stable(path, 65536); value = json.loads(path.read_bytes())
        require(type(value) is dict)
        if name in ('exit.json', 'observer-exit.json'):
            require(value.get('identity') == bound['identity'], 'identity-unknown')
        event = {'source': name, 'sha256': sha, 'file_mtime_ns': info.st_mtime_ns,
                 'time_basis': 'filesystem-mtime-not-verified-event-time', 'node': binding['node']}
        for key in ('state', 'returncode', 'source', 'acknowledged', 'automatic_replay', 'graceful_stop_verified'):
            item = value.get(key)
            if item is None or type(item) in (bool, int) or isinstance(item, str) and len(item) <= 96:
                # 名称source保留证据文件名，退出观测来源用单独字段。
                if key in value: event['exit_source' if key == 'source' else key] = item
        events.append(event)
        require(stable(path, 65536)[1] == sha, 'state-conflict')
    require(stable(launch, 1024**2)[1] == launch_sha and stable(process, 16384)[1] == process_sha, 'state-conflict')
    return sorted(events, key=lambda v: (v['file_mtime_ns'], v['source']))


def export(destination, *, instance_uuid, generation, network_id, captures, attempts=()):
    uuid_text(instance_uuid)
    require(type(generation) is int and generation > 0)
    from ctflab_scenario_v2 import identifier
    identifier(network_id)
    require(0 < len(captures) <= 32 and len(attempts) <= 128)
    binding = {'instance_uuid': instance_uuid, 'generation': generation, 'network_id': network_id}
    checked = [(Path(path).absolute(), read_capture(path, binding)) for path in captures]
    require(len({str(path) for path, _ in checked}) == len(checked))
    destination = Path(destination).absolute()
    require(all(destination != p and destination not in p.parents for p, _ in checked))
    timeline = []
    for path, node, plan_sha in attempts:
        identifier(node)
        require(isinstance(plan_sha, str) and len(plan_sha) == 64 and all(c in '0123456789abcdef' for c in plan_sha))
        # launch中的name是实例/代次绑定的一部分；不能混入其他实例的事件。
        path = guard(Path(path).absolute())
        stable(path/'launch.json', 1024**2)
        launch = json.loads((path/'launch.json').read_bytes())
        require(launch['name'] == f'ctflab-{instance_uuid}-g{generation}-{node}', 'identity-unknown')
        timeline.extend(lifecycle(path, {'node': node, 'plan_sha256': plan_sha}))
    private_directory(destination)
    files = {}; reports = []
    for index, (path, report) in enumerate(checked):
        target = destination/f'capture-{index+1:03d}.pcap'
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with path.open('rb') as source, os.fdopen(fd, 'wb') as output:
            remaining = report['size']
            while remaining:
                block = source.read(min(1024**2, remaining)); require(bool(block), 'state-conflict')
                output.write(block); remaining -= len(block)
            require(source.read(1) == b'', 'state-conflict')
            output.flush(); os.fsync(output.fileno())
        require(digest(target) == report['sha256'] and read_capture(path, binding) == report, 'state-conflict')
        files[target.name] = report['sha256']; reports.append(dict(report, file=target.name))
    timeline.sort(key=lambda v: (v['file_mtime_ns'], v['node'], v['source']))
    from ctflab_windows_recovery import record
    record(destination/'timeline.json', {'schema': 1, 'events': timeline, 'clock_verified': False})
    files['timeline.json'] = digest(destination/'timeline.json')
    manifest = {'schema': 1, 'kind': 'local-evidence-export', 'binding': binding,
                'created_at': datetime.now(timezone.utc).isoformat(), 'files': files, 'captures': reports,
                'complete_capture_verified': False, 'course_verified': False,
                'keys_included': False, 'uploaded': False}
    record(destination/'MANIFEST.json', manifest)
    return {'state': 'exported', 'files': len(files), 'manifest_sha256': digest(destination/'MANIFEST.json'),
            'uploaded': False, 'complete_capture_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--instance-uuid', required=True)
    parser.add_argument('--generation', required=True, type=int)
    parser.add_argument('--network-id', required=True)
    parser.add_argument('--capture', required=True, action='append', type=Path)
    args = parser.parse_args()
    print(canonical(export(args.destination, instance_uuid=args.instance_uuid, generation=args.generation,
                           network_id=args.network_id, captures=args.capture)))
