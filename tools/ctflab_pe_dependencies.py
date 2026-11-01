"""Windows x64 PE的有界静态依赖核对；不加载DLL、不运行二进制或扫描系统目录。"""
import argparse
import hashlib
import os
from pathlib import Path,PurePosixPath
import re
import struct
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import require,canonical
from ctflab_runtime_inventory import listing,signature,check_path

MAX_PE=256*1024**2
MAX_BINARIES=2048
# 仅是Win10+部署声明，不能证明当前/目标设备确实提供这些库或导出。
SYSTEM=frozenset((
    'advapi32 bcrypt bcryptprimitives cabinet comctl32 comdlg32 crypt32 cryptbase cryptsp '
    'dbghelp dnsapi dwmapi gdi32 gdi32full hid imm32 iphlpapi kernel32 kernelbase mpr msi msvcrt '
    'ncrypt netapi32 normaliz ntdll ole32 oleaut32 pdh powrprof profapi propsys psapi rpcrt4 secur32 '
    'setupapi shell32 shlwapi user32 userenv ucrtbase version winhttp wininet winmm winspool.drv '
    'wintrust wldap32 ws2_32 wsock32 wtsapi32 cfgmgr32 d3d9 dxgi dwrite gdiplus msimg32 mswsock opengl32 usp10 uxtheme').split())


def library(value):
    require(type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+\-]{0,127}\.(?:dll|drv)',value,re.I),'permission-denied')
    require('..' not in value,'permission-denied');return value.casefold()


def relative(value,*,directory=False):
    require(type(value) is str and value and '\\' not in value and ':' not in value and '\0' not in value,'permission-denied')
    if directory and value=='.':return value
    path=PurePosixPath(value)
    require(not path.is_absolute() and path.as_posix()==value and all(part not in ('','.','..') for part in value.split('/')),'permission-denied')
    return value


class PE:
    def __init__(self,data):
        require(type(data) is bytes and 64<=len(data)<=MAX_PE,'capability-unverified');self.data=data
        require(data[:2]==b'MZ','capability-unverified');offset=self.u32(60)
        require(64<=offset<=1024**2 and self.raw(offset,4)==b'PE\0\0','capability-unverified')
        require(self.u16(offset+4)==0x8664,'unsupported-platform')
        count=self.u16(offset+6);size=self.u16(offset+20);optional=offset+24
        require(1<=count<=96 and 112<=size<=4096 and self.u16(optional)==0x20b,'capability-unverified')
        self.raw(optional,size);directories=self.u32(optional+108)
        require(directories<=16 and 112+directories*8<=size,'capability-unverified')
        self.directories=[(self.u32(optional+112+i*8),self.u32(optional+116+i*8)) for i in range(directories)]
        self.headers=self.u32(optional+60);require(optional+size+count*40<=self.headers<=len(data),'capability-unverified')
        self.sections=[]
        for index in range(count):
            section=optional+size+index*40;self.raw(section,40)
            virtual_size=self.u32(section+8);address=self.u32(section+12);raw_size=self.u32(section+16);start=self.u32(section+20)
            require(address>=self.headers and address+max(raw_size,virtual_size)<=2**32,'capability-unverified')
            if raw_size:require(start>=self.headers and start+raw_size<=len(data),'capability-unverified')
            for old_address,old_size,old_start,old_raw in self.sections:
                require(address+max(raw_size,virtual_size)<=old_address or old_address+old_size<=address,'capability-unverified')
                if raw_size and old_raw:require(start+raw_size<=old_start or old_start+old_raw<=start,'capability-unverified')
            self.sections.append((address,max(raw_size,virtual_size),start,raw_size))
    def raw(self,offset,size):
        require(type(offset) is int and type(size) is int and offset>=0 and size>=0 and offset+size<=len(self.data),'capability-unverified')
        return self.data[offset:offset+size]
    def u16(self,offset):return struct.unpack('<H',self.raw(offset,2))[0]
    def u32(self,offset):return struct.unpack('<I',self.raw(offset,4))[0]
    def mapped(self,rva,size):
        require(0<rva<2**32 and 0<size<=MAX_PE,'capability-unverified')
        if rva<self.headers:
            require(rva+size<=self.headers,'capability-unverified');return rva
        candidates=[start+rva-address for address,_,start,raw in self.sections if address<=rva and rva+size<=address+raw]
        require(len(candidates)==1,'capability-unverified');return candidates[0]
    def text(self,rva,limit=256):
        value=bytearray()
        for index in range(limit):
            char=self.raw(self.mapped(rva+index,1),1)
            if char==b'\0':require(bool(value),'capability-unverified');return value.decode('ascii')
            value.extend(char)
        require(False,'capability-unverified')
    def directory(self,index):
        if index>=len(self.directories):return (0,0)
        rva,size=self.directories[index];require(bool(rva)==bool(size),'capability-unverified')
        if rva:self.mapped(rva,size)
        return rva,size
    def dependencies(self):
        values=set()
        for directory,width,kind in ((1,20,'import'),(13,32,'delay-import')):
            rva,size=self.directory(directory)
            if not rva:continue
            require(width<=size<=MAX_PE,'capability-unverified');terminated=False
            for index in range(min(size//width,4097)):
                offset=self.mapped(rva+index*width,width);raw=self.raw(offset,width)
                if not any(raw):terminated=True;break
                if kind=='delay-import':
                    # PE32+的现代RVA描述符；旧VA格式不做推断。
                    require(self.u32(offset)==1,'capability-unverified');name=self.u32(offset+4)
                else:name=self.u32(offset+12)
                values.add((library(self.text(name)),kind));require(len(values)<=1024,'storage-insufficient')
            require(terminated,'capability-unverified')
        rva,size=self.directory(0)
        if rva:
            require(size>=40,'capability-unverified');base=self.mapped(rva,40)
            count=self.u32(base+20);functions=self.u32(base+28);require(count<=65536,'storage-insufficient')
            if count:
                table=self.mapped(functions,count*4)
                for index in range(count):
                    target=self.u32(table+index*4)
                    if rva<=target<rva+size:
                        forward=self.text(target);require('.' in forward and target+len(forward.encode())+1<=rva+size,'capability-unverified')
                        name,symbol=forward.rsplit('.',1)
                        require(bool(symbol) and re.fullmatch(r'[A-Za-z0-9_?@$]+|#[0-9]+',symbol),'capability-unverified')
                        values.add((library(name if name.lower().endswith(('.dll','.drv')) else name+'.dll'),'forwarder'))
            require(len(values)<=1024,'storage-insufficient')
        return [{'name':name,'kind':kind} for name,kind in sorted(values)]


def analyze(root,entries,search_dirs=()):
    root=Path(root).absolute();before=listing(root)
    require(type(entries) in (list,tuple) and 1<=len(entries)<=MAX_BINARIES and len(set(entries))==len(entries))
    for name in entries:relative(name);require(name in before and Path(name).suffix.casefold() in ('.exe','.dll','.pyd','.drv'))
    require(type(search_dirs) in (list,tuple) and len(search_dirs)<=32 and len(set(search_dirs))==len(search_dirs))
    for directory in search_dirs:
        relative(directory,directory=True);path=root/directory;require(path.is_dir(),'permission-denied');check_path(path)
    parsed={};scopes=[];edges=[];missing=[];ambiguous=[]
    def parse(name):
        if name in parsed:return parsed[name]
        require(len(parsed)<MAX_BINARIES,'storage-insufficient');expected=before[name]
        require(expected.st_size<=MAX_PE,'storage-insufficient');path=root/name;check_path(path)
        with path.open('rb') as stream:
            require(signature(os.fstat(stream.fileno()))==signature(expected),'identity-unknown')
            data=stream.read(MAX_PE+1)
            require(len(data)==expected.st_size and signature(os.fstat(stream.fileno()))==signature(expected),'identity-unknown')
        require(signature(check_path(path))==signature(expected),'identity-unknown')
        result={'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'dependencies':PE(data).dependencies()};parsed[name]=result;return result
    for entry in entries:
        directories=sorted(set([PurePosixPath(entry).parent.as_posix(),*search_dirs]));index={}
        for name in before:
            if PurePosixPath(name).parent.as_posix() in directories and Path(name).suffix.casefold() in ('.dll','.drv'):
                index.setdefault(library(PurePosixPath(name).name),[]).append(name)
        scopes.append({'entry':entry,'declared_search_directories':directories});pending=[entry];seen=set()
        while pending:
            name=pending.pop()
            if name in seen:continue
            seen.add(name);info=parse(name)
            for dependency in info['dependencies']:
                dll=dependency['name'];candidates=sorted(index.get(dll,[]))
                system=dll.removesuffix('.dll') in SYSTEM or dll in SYSTEM or dll.startswith(('api-ms-win-','ext-ms-win-'))
                state='os-contract-unverified' if system and not candidates else 'bundled' if len(candidates)==1 and not system else 'missing' if not candidates else 'ambiguous-or-os-shadow'
                edge={'entry':entry,'importer':name,**dependency,'state':state,'candidates':candidates};edges.append(edge)
                require(len(edges)<=65536,'storage-insufficient')
                if state=='bundled':pending.extend(candidates)
                elif state=='missing':missing.append(edge)
                elif state=='ambiguous-or-os-shadow':ambiguous.append(edge)
    after=listing(root)
    require(set(before)==set(after) and all(signature(value)==signature(after[name]) for name,value in before.items()),'identity-unknown')
    files=[{'name':name,**value} for name,value in sorted(parsed.items())]
    result={'schema':1,'scope':'windows-x64-static-imports-only','files':files,'entries':list(entries),'search_scopes':scopes,
        'edges':edges,'missing':missing,'ambiguous':ambiguous,'bundled_static_dependencies_present':not missing and not ambiguous,
        'os_contracts_verified':False,'dynamic_loads_verified':False,'native_dependency_closure_verified':False,
        'signature_verified':False,'source_verified':False,'binary_executed':False,'host_modified':False}
    result['report_sha256']=hashlib.sha256(canonical(result).encode()).hexdigest();return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--entry',action='append',required=True);parser.add_argument('--search-dir',action='append',default=[])
    args=parser.parse_args(argv)
    try:
        value=analyze(args.root,args.entry,args.search_dir);print(canonical(value));return 0 if value['bundled_static_dependencies_present'] else 2
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,struct.error):
        print(canonical({'state':'static-import-inspection-refused','preserved':True,'binary_executed':False,'host_modified':False}));return 2


if __name__=='__main__':raise SystemExit(main())
