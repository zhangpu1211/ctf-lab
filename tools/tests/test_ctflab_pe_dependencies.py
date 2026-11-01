"""纯字节PE夹具与临时目录；不执行PE、加载DLL或访问系统运行时。"""
import copy
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_runtime_inventory import InventoryError
import ctflab_pe_dependencies as pe


def fixture(imports=(),delay=(),forwarders=()):
    data=bytearray(8192);data[:2]=b'MZ';struct.pack_into('<I',data,60,128);data[128:132]=b'PE\0\0'
    struct.pack_into('<HH',data,132,0x8664,1);struct.pack_into('<H',data,148,240)
    optional=152;struct.pack_into('<H',data,optional,0x20b);struct.pack_into('<I',data,optional+60,512)
    struct.pack_into('<I',data,optional+108,16);section=optional+240
    struct.pack_into('<IIII',data,section+8,7680,0x1000,7680,512)
    def offset(rva):return rva-0x1000+512
    cursor=0x2000
    def string(value):
        nonlocal cursor
        raw=value.encode()+b'\0';start=cursor;data[offset(start):offset(start)+len(raw)]=raw;cursor+=len(raw);return start
    for index,names,width,rva in ((1,imports,20,0x1100),(13,delay,32,0x1400)):
        if not names:continue
        struct.pack_into('<II',data,optional+112+index*8,rva,width*(len(names)+1))
        for i,name in enumerate(names):
            start=offset(rva+i*width)
            if index==1:struct.pack_into('<I',data,start+12,string(name))
            else:struct.pack_into('<II',data,start,1,string(name))
    if forwarders:
        export=0x1800;size=512;struct.pack_into('<II',data,optional+112,export,size)
        struct.pack_into('<I',data,offset(export)+20,len(forwarders));struct.pack_into('<I',data,offset(export)+28,export+40)
        cursor=export+128
        for i,value in enumerate(forwarders):struct.pack_into('<I',data,offset(export+40)+4*i,string(value))
    return bytes(data)


class PETests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
    def put(self,name,data):
        path=self.root/name;path.parent.mkdir(exist_ok=True,parents=True);path.write_bytes(data);return path
    def test_regular_delay_and_export_forwarders_are_all_edges(self):
        value=pe.PE(fixture(['KERNEL32.dll','liba.dll'],['libb.dll'],['libc.Run','NTDLL.#123'])).dependencies()
        self.assertEqual(value,[{'name':'kernel32.dll','kind':'import'},{'name':'liba.dll','kind':'import'},
            {'name':'libb.dll','kind':'delay-import'},{'name':'libc.dll','kind':'forwarder'},{'name':'ntdll.dll','kind':'forwarder'}])
    def test_transitive_cycle_does_not_execute_and_records_precise_file_hashes(self):
        a=fixture(['liba.dll','KERNEL32.dll']);self.put('app.exe',a);self.put('liba.dll',fixture(['libb.dll']));self.put('libb.dll',fixture(['liba.dll']))
        with patch('subprocess.run',side_effect=AssertionError('静态检查不得启动程序')):
            value=pe.analyze(self.root,['app.exe'])
        self.assertTrue(value['bundled_static_dependencies_present']);self.assertEqual(len(value['files']),3)
        self.assertEqual(value['files'][0]['sha256'],hashlib.sha256(a).hexdigest())
        self.assertFalse(value['native_dependency_closure_verified']);self.assertFalse(value['binary_executed'])
        self.assertEqual(value['report_sha256'],hashlib.sha256(canonical({k:v for k,v in value.items() if k!='report_sha256'}).encode()).hexdigest())
    def test_delay_load_missing_is_not_omitted_or_looked_up_in_host_path(self):
        self.put('app.exe',fixture(delay=['optional.dll']))
        with patch.dict('os.environ',{'PATH':'/private/unrelated'},clear=False):value=pe.analyze(self.root,['app.exe'])
        self.assertFalse(value['bundled_static_dependencies_present']);self.assertEqual(value['missing'][0]['kind'],'delay-import')
    def test_explicit_search_scope_and_case_ambiguity(self):
        self.put('app.exe',fixture(['liba.dll']));self.put('deps/liba.dll',fixture())
        self.assertFalse(pe.analyze(self.root,['app.exe'])['bundled_static_dependencies_present'])
        self.assertTrue(pe.analyze(self.root,['app.exe'],['deps'])['bundled_static_dependencies_present'])
        self.put('other/LIBA.DLL',fixture())
        value=pe.analyze(self.root,['app.exe'],['deps','other']);self.assertFalse(value['bundled_static_dependencies_present'])
        self.assertEqual(len(value['ambiguous']),1)
    def test_os_contracts_unverified_and_local_shadow_is_rejected(self):
        self.put('app.exe',fixture(['kernel32.dll','api-ms-win-core-synch-l1-2-0.dll']))
        value=pe.analyze(self.root,['app.exe']);self.assertTrue(value['bundled_static_dependencies_present'])
        self.assertFalse(value['os_contracts_verified']);self.assertEqual({e['state'] for e in value['edges']},{'os-contract-unverified'})
        self.put('kernel32.dll',fixture());self.assertFalse(pe.analyze(self.root,['app.exe'])['bundled_static_dependencies_present'])
    def test_installer_property_system_contracts_remain_unverified_and_cannot_be_shadowed(self):
        self.put('app.exe',fixture([n+'.dll' for n in ('msi','propsys','cfgmgr32','d3d9','dxgi','dwrite','gdiplus','msimg32','mswsock','opengl32','usp10')]))
        value=pe.analyze(self.root,['app.exe'])
        self.assertTrue(value['bundled_static_dependencies_present'])
        self.assertFalse(value['os_contracts_verified'])
        self.assertEqual({e['state'] for e in value['edges']},{'os-contract-unverified'})
        for name in ('msi.dll','propsys.dll'):
            self.put(name,fixture())
            self.assertFalse(pe.analyze(self.root,['app.exe'])['bundled_static_dependencies_present'])
    def test_large_import_directory_with_small_descriptor_table_is_supported(self):
        data=bytearray(fixture(['kernel32.dll']));data.extend(bytes(128*1024))
        raw_size=len(data)-512
        struct.pack_into('<IIII',data,392+8,raw_size,0x1000,raw_size,512)
        struct.pack_into('<I',data,152+116+8,108160)
        self.assertEqual(pe.PE(bytes(data)).dependencies(),[{'name':'kernel32.dll','kind':'import'}])
        # 大目录不能绕过4097条扫描上限；有效重复描述符但无终止符仍拒绝。
        descriptor=bytes(data[768:788])
        data[768:768+20*4097]=descriptor*4097
        with self.assertRaises(ContractError):pe.PE(bytes(data)).dependencies()

    def test_path_imports_foreign_arch_truncation_and_legacy_delay_va_are_refused(self):
        bad=[]
        for name in ('../outside.dll','C:\\bad.dll','folder/file.dll','not-a-dll'):
            bad.append(fixture([name]))
        arm=bytearray(fixture());struct.pack_into('<H',arm,132,0xaa64);bad.append(bytes(arm))
        legacy=bytearray(fixture(delay=['lib.dll']));struct.pack_into('<I',legacy,512+0x400,0);bad.append(bytes(legacy))
        bad.extend([b'MZ',fixture()[:600]])
        for data in bad:
            with self.subTest(size=len(data)),self.assertRaises((ContractError,ValueError)):pe.PE(data).dependencies()
    def test_rva_unbacked_overlapping_and_unterminated_import_directory_refused(self):
        original=fixture(['lib.dll']);bad=[]
        value=bytearray(original);struct.pack_into('<I',value,152+112+8,0x9000);bad.append(bytes(value))
        value=bytearray(original);struct.pack_into('<I',value,152+116+8,20);bad.append(bytes(value))
        value=bytearray(original);struct.pack_into('<H',value,134,2);struct.pack_into('<IIII',value,432,7680,0x1000,7680,512);bad.append(bytes(value))
        for data in bad:
            with self.assertRaises(ContractError):pe.PE(data).dependencies()
    def test_links_external_roots_and_file_drift_are_refused(self):
        self.put('app.exe',fixture());self.put('unrelated.txt',b'input')
        with self.assertRaises(ContractError):pe.analyze(self.root,['../app.exe'])
        with self.assertRaises(ContractError):pe.analyze(self.root,['app.exe'],['../outside'])
        with patch.object(pe,'listing',side_effect=[pe.listing(self.root),{}]):
            with self.assertRaises(ContractError):pe.analyze(self.root,['app.exe'])
        (self.root/'link.dll').symlink_to(self.root/'app.exe')
        with self.assertRaises(InventoryError):pe.analyze(self.root,['app.exe'])
    def test_binary_and_dependency_count_limits_refuse_before_allocation(self):
        self.put('app.exe',fixture());data=bytearray(fixture(forwarders=['lib.Run']))
        struct.pack_into('<I',data,512+0x800+20,65537)
        with self.assertRaises(ContractError):pe.PE(bytes(data)).dependencies()
        with self.assertRaises(ContractError):pe.analyze(self.root,['app.exe']*2049)
