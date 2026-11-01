"""自制PCAP与FAT12教学证据；只生成/读取字节，不捕获流量、不挂载或运行镜像。"""
from datetime import datetime, timezone
import argparse
import hashlib
import inspect
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct
from ctflab_evidence_course import MAX_FILE, MAX_TOTAL, sha, verify
from ctflab_evidence_workspace import checked_path, read_stable


def checksum(raw):
    if len(raw) % 2:raw += b'\0'
    total = sum(struct.unpack('!'+str(len(raw)//2)+'H', raw))
    while total >> 16:total = (total & 65535)+(total >> 16)
    return (~total) & 65535


def frame(source, target, sport, dport, sequence, acknowledgement, payload):
    src = ipaddress.IPv4Address(source).packed; dst = ipaddress.IPv4Address(target).packed
    tcp = struct.pack('!HHIIBBHHH', sport, dport, sequence, acknowledgement, 0x50, 0x18, 8192, 0, 0)
    pseudo = src+dst+struct.pack('!BBH', 0, 6, len(tcp)+len(payload))
    tcp = tcp[:16]+struct.pack('!H', checksum(pseudo+tcp+payload))+tcp[18:]
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20+len(tcp)+len(payload), sport, 0x4000, 64, 6, 0, src, dst)
    ip = ip[:10]+struct.pack('!H', checksum(ip))+ip[12:]
    return bytes.fromhex('0200000000800200000000240800')+ip+tcp+payload


def pcap_sample():
    data = bytearray(struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
    cases = [('09:01:00', 'r05', '198.51.100.24', '/admin/settings', 'maintenance=true', '200 OK', 'saved'),
             ('09:02:00', 'r06', '192.0.2.10', '/', '', '503 Service Unavailable', 'maintenance'),
             ('09:03:00', 'r07', '203.0.113.9', '/health', '', '200 OK', 'healthy')]
    for index, (clock, request, source, path, body, status, response_body) in enumerate(cases):
        method = 'POST' if body else 'GET'; port = 50005+index
        query = (f'{method} {path} HTTP/1.1\r\nHost: training.invalid\r\nX-Lab-Request: {request}\r\nContent-Length: {len(body)}\r\n\r\n'+body).encode()
        response = (f'HTTP/1.1 {status}\r\nX-Lab-Request: {request}\r\nContent-Length: {len(response_body)}\r\n\r\n'+response_body).encode()
        packets = [frame(source, '192.0.2.80', port, 80, 1000, 5000, query),
                   frame('192.0.2.80', source, 80, port, 5000, 1000+len(query), response)]
        seconds = int(datetime.fromisoformat('2026-10-20T'+clock+'+00:00').timestamp())
        for number, packet in enumerate(packets):
            data.extend(struct.pack('<IIII', seconds, number*1000, len(packet), len(packet))); data.extend(packet)
    return bytes(data)


def fat_entry(table, cluster, value):
    offset = cluster+cluster//2; prior = int.from_bytes(table[offset:offset+2], 'little')
    combined = (prior & 0x000f) | (value << 4) if cluster & 1 else (prior & 0xf000) | value
    table[offset:offset+2] = combined.to_bytes(2, 'little')


def fat_sample(web_log):
    # 360KiB软盘几何，非启动用途；两个FAT、固定根目录、无可执行文件或分区挂载。
    image = bytearray(720*512); image[:11] = b'\xeb\x3c\x90CTFLAB  '
    struct.pack_into('<HBHBHHBHHHII', image, 11, 512, 1, 1, 2, 112, 720, 0xfd, 3, 9, 2, 0, 0)
    struct.pack_into('<BBBI', image, 36, 0, 0, 0x29, 0xC052026)
    image[43:54] = b'CTFLAB C05 '; image[54:62] = b'FAT12   '; image[510:512] = b'\x55\xaa'
    table = bytearray(3*512); table[:3] = b'\xfd\xff\xff'; cluster = 2
    files = {'CONFIG.TXT': b'maintenance=true\ncache_ttl=120\n', 'ACCESS.LOG': web_log,
             'COLLECT.TXT': b'Synthetic data volume; not a real host disk.\nSnapshot label: 2026-10-20T09:04:00Z.\nFAT local timestamps are unspecified, not independent UTC evidence.\n'}
    date = ((2026-1980)<<9) | (10<<5) | 20; clock = (9<<11) | (4<<5)
    for index, (name, raw) in enumerate(files.items()):
        first = cluster; needed = (len(raw)+511)//512
        for position in range(needed):
            fat_entry(table, cluster, 0xfff if position == needed-1 else cluster+1)
            start = (14+cluster-2)*512; image[start:start+len(raw[position*512:(position+1)*512])] = raw[position*512:(position+1)*512]
            cluster += 1
        entry = 7*512+index*32; base, suffix = name.split('.')
        image[entry:entry+11] = (base.ljust(8)+suffix.ljust(3)).encode(); image[entry+11] = 0x20
        struct.pack_into('<HH', image, entry+22, clock, date)
        struct.pack_into('<HI', image, entry+26, first, len(raw))
    image[512:4*512] = table; image[4*512:7*512] = table
    return bytes(image)


def read_pcap(raw):
    if (type(raw) is not bytes or not 24 <= len(raw) <= 65536
            or raw[:24] != struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)):
        raise ValueError('仅支持本课小端微秒Ethernet PCAP')
    records = []; offset = 24
    while offset < len(raw):
        if len(records) >= 32 or offset+16 > len(raw):raise ValueError('PCAP记录边界无效')
        seconds, micros, captured, original = struct.unpack_from('<IIII', raw, offset); offset += 16
        if captured != original or not 54 <= captured <= 8192 or offset+captured > len(raw) or micros >= 1000000:
            raise ValueError('PCAP长度/时间不符')
        packet = raw[offset:offset+captured]; offset += captured
        ip = packet[14:]
        if packet[12:14] != b'\x08\x00' or ip[0] != 0x45 or ip[9] != 6 or checksum(ip[:20]) != 0:
            raise ValueError('仅支持本课IPv4/TCP固定头')
        if int.from_bytes(ip[2:4], 'big') != len(ip) or int.from_bytes(ip[6:8], 'big') & 0x3fff:
            raise ValueError('不支持分片或长度变化')
        tcp = ip[20:]; pseudo = ip[12:20]+struct.pack('!BBH', 0, 6, len(tcp))
        if tcp[12] != 0x50 or checksum(pseudo+tcp) != 0:raise ValueError('TCP头或校验和不符')
        text = tcp[20:].decode('ascii'); header, body = text.split('\r\n\r\n', 1); lines = header.split('\r\n')
        labels = [line.split(': ', 1)[1] for line in lines[1:] if line.startswith('X-Lab-Request: ')]
        if len(labels) != 1 or len(labels[0]) > 32:raise ValueError('教学关联标识不符')
        records.append({'record': len(records)+1, 'timestamp_utc': datetime.fromtimestamp(seconds, timezone.utc).isoformat(),
                        'microseconds': micros, 'source': str(ipaddress.IPv4Address(ip[12:16])),
                        'target': str(ipaddress.IPv4Address(ip[16:20])), 'request': labels[0],
                        'http': lines[0], 'body': body})
    return records


def read_fat(raw):
    if type(raw) is not bytes or len(raw) != 720*512 or raw[510:512] != b'\x55\xaa':raise ValueError('非本课FAT12数据卷')
    geometry = struct.unpack_from('<HBHBHHBHHHII', raw, 11)
    if geometry != (512, 1, 1, 2, 112, 720, 0xfd, 3, 9, 2, 0, 0):raise ValueError('不支持此磁盘几何')
    table = raw[512:4*512]
    if table != raw[4*512:7*512] or table[:3] != b'\xfd\xff\xff':raise ValueError('FAT副本不一致')
    result = {}; used = set()
    for index in range(112):
        entry = raw[7*512+index*32:7*512+(index+1)*32]
        if entry[0] == 0:break
        if entry[11] != 0x20 or any(c not in b'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ' for c in entry[:11]):
            raise ValueError('仅支持本课根目录普通8.3文件')
        name = entry[:8].decode().rstrip()+'.'+entry[8:11].decode().rstrip()
        first, length = struct.unpack_from('<HI', entry, 26)
        if name in result or not 0 < length <= 65536:raise ValueError('文件重复或长度无效')
        cluster = first; data = bytearray()
        while len(data) < length:
            if not 2 <= cluster <= 707 or cluster in used:raise ValueError('簇越界、循环或交叉链接')
            used.add(cluster); start = (14+cluster-2)*512; data.extend(raw[start:start+512])
            offset = cluster+cluster//2; value = int.from_bytes(table[offset:offset+2], 'little')
            cluster = (value >> 4) if cluster & 1 else (value & 0xfff)
            if len(data) < length and cluster >= 0xff8:raise ValueError('簇链提前结束')
        if not 0xff8 <= cluster <= 0xfff:raise ValueError('簇链未完整终止')
        data = bytes(data[:length])
        result[name] = {'bytes': length, 'sha256': hashlib.sha256(data).hexdigest(), 'text': data.decode('utf-8'),
                        'dos_modified_time': int.from_bytes(entry[22:24], 'little'),
                        'dos_modified_date': int.from_bytes(entry[24:26], 'little'), 'timestamp_timezone': 'unspecified-local'}
    if set(result) != {'CONFIG.TXT', 'ACCESS.LOG', 'COLLECT.TXT'}:raise ValueError('不是本课文件集')
    return result


def inspect_samples(root, manifest_sha256):
    root = checked_path(root)
    if sha(read_stable(root/'MANIFEST.json')) != manifest_sha256:raise ValueError('清单指纹不符')
    verify(root)
    packets = read_pcap(read_stable(root/'evidence/traffic.pcap'))
    volume = read_fat(read_stable(root/'evidence/disk.fat12'))
    return {'synthetic': True, 'classroom_verified': False, 'publisher_identity_verified': False,
            'capture_executed': False, 'volume_mounted': False, 'sample_executed': False,
            'pcap': packets, 'fat12_files': volume,
            'scope': '仅本课固定PCAP/360KiB FAT12；不支持任意抓包、文件系统或恶意镜像',
            'clock_note': 'PCAP为合成UTC；FAT目录时间是无指定时区本地字段，不能直接等同UTC'}


def inspector_main(argv=None):
    parser = argparse.ArgumentParser(description='校验后只读查看本课PCAP与FAT12，不挂载、不运行')
    parser.add_argument('--manifest-sha256', required=True); args = parser.parse_args(argv)
    try:
        result = inspect_samples(Path(__file__).absolute().parent, args.manifest_sha256)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (OSError, ValueError, TypeError, KeyError, struct.error, OverflowError):
        print('样本未能核验；原件保留，不解析未知格式或执行样本。'); return 2


def inspector_source():
    imports = ('import argparse,hashlib,ipaddress,json,os,stat,struct\n'
               'from datetime import datetime,timezone\nfrom pathlib import Path,PurePosixPath\n')
    functions = (sha, verify, checked_path, read_stable, checksum, read_pcap, read_fat, inspect_samples, inspector_main)
    return (imports+f'MAX_FILE={MAX_FILE}\nMAX_TOTAL={MAX_TOTAL}\n'
            +'\n\n'.join(inspect.getsource(function) for function in functions)
            +"\nif __name__ == '__main__':raise SystemExit(inspector_main())\n")
