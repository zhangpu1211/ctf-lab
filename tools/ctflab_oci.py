"""受限OCI布局tar校验与无标签Docker载荷转换；不解包文件系统、不执行镜像。

只支持单Linux镜像、SHA-256、未压缩/gzip层及普通USTAR外包装。
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import posixpath
import shutil
import sys
import tarfile

if __package__ in (None, ''): sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctflab_contract import require, canonical
from ctflab_generation_store import private_directory, digest

MAX_ARCHIVE = 8*1024**3
MAX_EXPANDED = 16*1024**3
JSON_LIMIT = 4*1024**2
MANIFEST = 'application/vnd.oci.image.manifest.v1+json'
CONFIG = 'application/vnd.oci.image.config.v1+json'
LAYERS = ('application/vnd.oci.image.layer.v1.tar', 'application/vnd.oci.image.layer.v1.tar+gzip')


def checksum(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value))
    return value


def regular(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        info = part.lstat()
        require(not part.is_symlink() and not getattr(info, 'st_file_attributes', 0)&0x400, 'permission-denied')
    info = path.stat()
    require(path.is_file() and info.st_nlink == 1, 'permission-denied')
    return info


def signature(info): return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def json_value(raw):
    require(len(raw) <= JSON_LIMIT)
    def unique(pairs):
        result = {}
        for key, value in pairs: require(key not in result); result[key] = value
        return result
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=lambda _: require(False))


class Slice:
    def __init__(self, stream, start, size): self.stream, self.start, self.size, self.offset = stream, start, size, 0
    def read(self, size=-1):
        size = min(self.size-self.offset, size if size >= 0 else self.size)
        self.stream.seek(self.start+self.offset); raw = self.stream.read(size)
        require(len(raw) == size, 'state-conflict'); self.offset += len(raw); return raw


class Hashed:
    def __init__(self, stream): self.stream, self.sha, self.size = stream, hashlib.sha256(), 0
    def read(self, size=-1):
        raw = self.stream.read(size); self.sha.update(raw); self.size += len(raw); return raw


def validate_layer(source,limit):
    """有界流式核验层tar；不调用extract，也不让PAX/GNU扩展自动分配内存。"""
    source=Hashed(source);names=set()
    def read(size):
        raw=source.read(size);require(source.size<=limit,'storage-insufficient');return raw
    while True:
        header=read(512);require(len(header)==512)
        if header==b'\0'*512:
            require(read(512)==b'\0'*512)
            trailing=0
            while block:=read(65536):
                trailing+=len(block);require(trailing<=1024**2 and not any(block))
            return source.sha.hexdigest(),source.size
        require(header[257:265]==b'ustar\x0000','capability-unverified')
        def number(raw):
            raw=raw.strip(b'\0 ');require(bool(raw) and all(48<=c<=55 for c in raw));return int(raw,8)
        require(sum(header[:148])+8*32+sum(header[156:])==number(header[148:156]))
        def text(raw):
            parts=raw.split(b'\0',1);require(len(parts)==1 or not any(parts[1]));return parts[0].decode('utf-8')
        name=text(header[:100]);prefix=text(header[345:500])
        if prefix:name=prefix+'/'+name
        require(not name.startswith('/') and '..' not in name.split('/') and '\\' not in name,'permission-denied')
        normalized=posixpath.normpath(name);kind=header[156:157];size=number(header[124:136])
        require(normalized not in names and len(names)<100000);names.add(normalized)
        require(kind in (b'0',b'\0',b'1',b'2',b'5'),'capability-unverified')
        require(normalized!='.' or kind==b'5')
        if kind in (b'1',b'2'):
            target=text(header[157:257]);require(bool(target) and '\\' not in target and size==0)
            if kind==b'1':require(not target.startswith('/') and '..' not in target.split('/'),'permission-denied')
            elif not target.startswith('/'):
                resolved=posixpath.normpath(posixpath.join(posixpath.dirname(normalized),target))
                require(resolved!='..' and not resolved.startswith('../'),'permission-denied')
        elif kind==b'5':require(size==0)
        else:require(not any(header[157:257]))
        remaining=((size+511)//512)*512
        require(source.size+remaining<=limit,'storage-insufficient')
        while remaining:
            block=read(min(65536,remaining));require(bool(block));remaining-=len(block)


def entries(stream, size):
    result = {}; directories = set(); position = 0
    while True:
        require(position+512 <= size)
        stream.seek(position); header = stream.read(512)
        if header == b'\0'*512:
            require(size-position >= 1024 and size-position <= 1024**2)
            require(stream.read(512) == b'\0'*512)
            require(not any(stream.read(size-position-1024)))
            return result
        require(header[257:263] == b'ustar\0' and header[263:265] == b'00', 'capability-unverified')
        def number(raw):
            raw = raw.strip(b'\0 '); require(bool(raw) and all(48 <= c <= 55 for c in raw)); return int(raw, 8)
        require(sum(header[:148])+8*32+sum(header[156:]) == number(header[148:156]))
        def text(raw):
            parts = raw.split(b'\0', 1)
            require(len(parts) == 1 or not any(parts[1])); return parts[0].decode('ascii')
        name, prefix = text(header[:100]), text(header[345:500])
        if prefix: name = prefix+'/'+name
        length = number(header[124:136]); kind = header[156:157]
        require(not any(header[157:257]), 'permission-denied')
        if kind == b'5':
            normalized = name.rstrip('/')
            require(normalized in ('blobs', 'blobs/sha256') and length == 0 and normalized not in directories)
            directories.add(normalized)
        else:
            require(kind in (b'0', b'\0'), 'capability-unverified')
            require(name in ('oci-layout', 'index.json') or re.fullmatch('blobs/sha256/[0-9a-f]{64}', name))
            require(name not in result and len(result) < 260)
            result[name] = (position+512, length)
        position += 512+((length+511)//512)*512
        require(position <= size)


def descriptor(value, media):
    require(type(value) is dict and {'mediaType','digest','size'} <= set(value)
            and set(value) <= {'mediaType','digest','size','platform','annotations'})
    require(value['mediaType'] in media)
    require(isinstance(value['digest'], str) and value['digest'].startswith('sha256:'))
    sha = checksum(value['digest'][7:])
    require(type(value['size']) is int and 0 < value['size'] <= MAX_ARCHIVE)
    return sha


def inspect_archive(path, archive_sha256, manifest_sha256, architecture):
    path = Path(path).absolute(); checksum(archive_sha256); checksum(manifest_sha256)
    require(architecture in ('amd64','arm64'))
    info = regular(path); require(1024 <= info.st_size <= MAX_ARCHIVE)
    with path.open('rb') as stream:
        require(signature(os.fstat(stream.fileno())) == signature(info), 'identity-unknown')
        outer = hashlib.sha256(); counted = 0
        while block := stream.read(1024**2):
            counted += len(block); require(counted <= info.st_size, 'state-conflict'); outer.update(block)
        require(counted == info.st_size, 'state-conflict')
        require(outer.hexdigest() == archive_sha256, 'state-conflict')
        listing = entries(stream, info.st_size)
        def small(name):
            start, size = listing[name]; require(size <= JSON_LIMIT)
            stream.seek(start); raw = stream.read(size); require(len(raw) == size)
            return json_value(raw)
        require(small('oci-layout') == {'imageLayoutVersion':'1.0.0'})
        index = small('index.json')
        require(type(index) is dict and set(index) <= {'schemaVersion','mediaType','manifests','annotations'}
                and type(index.get('schemaVersion')) is int and index['schemaVersion'] == 2)
        require(index.get('mediaType', 'application/vnd.oci.image.index.v1+json') == 'application/vnd.oci.image.index.v1+json')
        require(type(index.get('manifests')) is list and len(index['manifests']) == 1, 'capability-unverified')
        top = index['manifests'][0]
        require(descriptor(top, (MANIFEST,)) == manifest_sha256, 'state-conflict')
        if 'platform' in top:
            require(type(top['platform']) is dict and top['platform'].get('os') == 'linux'
                    and top['platform'].get('architecture') == architecture, 'capability-unverified')
        referenced = set()
        def blob(spec, media):
            sha = descriptor(spec, media); name = 'blobs/sha256/'+sha
            require(name in listing and listing[name][1] == spec['size'], 'state-conflict')
            source = Slice(stream, *listing[name]); value = hashlib.sha256()
            while block := source.read(1024**2): value.update(block)
            require(value.hexdigest() == sha, 'state-conflict'); referenced.add(name)
            return name
        manifest_name = blob(top, (MANIFEST,)); manifest = small(manifest_name)
        require(type(manifest) is dict and {'schemaVersion','mediaType','config','layers'} <= set(manifest)
                and set(manifest) <= {'schemaVersion','mediaType','config','layers','annotations'})
        require(type(manifest['schemaVersion']) is int and manifest['schemaVersion'] == 2 and manifest['mediaType'] == MANIFEST)
        config_name = blob(manifest['config'], (CONFIG,)); config = small(config_name)
        require(type(config) is dict and config.get('os') == 'linux' and config.get('architecture') == architecture, 'capability-unverified')
        rootfs = config.get('rootfs')
        require(type(rootfs) is dict and set(rootfs) == {'type','diff_ids'} and rootfs['type'] == 'layers')
        require(type(rootfs['diff_ids']) is list and type(manifest['layers']) is list
                and len(rootfs['diff_ids']) == len(manifest['layers']) <= 128)
        layers = []; expanded = 0
        for spec, diff_id in zip(manifest['layers'], rootfs['diff_ids']):
            require(isinstance(diff_id, str) and diff_id.startswith('sha256:')); checksum(diff_id[7:])
            name = blob(spec, LAYERS); source = Slice(stream, *listing[name])
            source = gzip.GzipFile(fileobj=source, mode='rb') if spec['mediaType'] == LAYERS[1] else source
            actual,size=validate_layer(source,MAX_EXPANDED-expanded);expanded+=size
            require(actual == diff_id[7:], 'state-conflict')
            layers.append({'blob':name, 'gzip':spec['mediaType'] == LAYERS[1], 'size':size, 'diff_id':diff_id})
        require(set(listing) == referenced|{'oci-layout','index.json'}, 'capability-unverified')
        require(signature(os.fstat(stream.fileno())) == signature(info) and signature(regular(path)) == signature(info), 'state-conflict')
        return {'schema':1, 'archive_sha256':archive_sha256, 'manifest_sha256':manifest_sha256,
                'config_sha256':manifest['config']['digest'][7:], 'architecture':architecture,
                'diff_ids':rootfs['diff_ids'], 'config_blob':config_name, 'entries':listing,
                'layers':layers, 'expanded_bytes':expanded, 'runtime_verified':False}


def convert(path, destination, archive_sha256, manifest_sha256, architecture):
    """只写新目录，生成无标签Docker manifest，原OCI摘要与ImageID分别保留。"""
    original = regular(Path(path).absolute())
    report = inspect_archive(path, archive_sha256, manifest_sha256, architecture)
    path = Path(path).absolute(); destination = Path(destination).absolute()
    require(destination != path and destination not in path.parents)
    require(shutil.disk_usage(destination.parent).free >= report['expanded_bytes']+16*1024**2, 'storage-insufficient')
    private_directory(destination)
    target = destination/'docker.tar'
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with path.open('rb') as source, os.fdopen(fd, 'wb') as output, tarfile.open(fileobj=output, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
        require(signature(os.fstat(source.fileno())) == signature(original), 'identity-unknown')
        def add(name, size, stream):
            entry = tarfile.TarInfo(name); entry.size = size; entry.mode = 0o400
            archive.addfile(entry, stream)
        config_name = report['config_sha256']+'.json'
        start, size = report['entries'][report['config_blob']]
        config_stream = Hashed(Slice(source, start, size)); add(config_name, size, config_stream)
        require(config_stream.sha.hexdigest() == report['config_sha256'], 'state-conflict')
        layer_names = []
        for index, layer in enumerate(report['layers']):
            name = f'layers/{index:03d}/layer.tar'; layer_names.append(name)
            raw = Slice(source, *report['entries'][layer['blob']])
            stream = Hashed(gzip.GzipFile(fileobj=raw, mode='rb') if layer['gzip'] else raw)
            add(name, layer['size'], stream)
            require(stream.read(1) == b'' and stream.sha.hexdigest() == layer['diff_id'][7:], 'state-conflict')
        manifest = canonical([{'Config':config_name,'RepoTags':[],'Layers':layer_names}]).encode()
        add('manifest.json', len(manifest), io.BytesIO(manifest))
        archive.close(); output.flush(); os.fsync(output.fileno())
    require(signature(regular(path)) == signature(original), 'state-conflict')
    return dict(report, docker_archive_sha256=digest(target))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect','convert')); parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--archive-sha256', required=True); parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--architecture', required=True, choices=('amd64','arm64')); parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'convert':
            require(args.destination is not None)
            result = convert(args.input,args.destination,args.archive_sha256,args.manifest_sha256,args.architecture)
        else: result = inspect_archive(args.input,args.archive_sha256,args.manifest_sha256,args.architecture)
        print(canonical(result))
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,EOFError):
        print(canonical({'state':'failed','preserved':True,'runtime_verified':False}));raise SystemExit(2)
