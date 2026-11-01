"""镜像实际回环TLS/续传与白名单；证书/缓存/监听均为本轮自有临时对象。"""
from datetime import datetime, timedelta, timezone
from http.client import HTTPSConnection
import ipaddress
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import threading
import unittest
from urllib.request import build_opener, HTTPSHandler

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError, canonical
from ctflab_content_cache import ContentCache, NoRedirect
from ctflab_generation_store import digest
from ctflab_mirror_service import MirrorView, MirrorServer, byte_range
import test_ctflab_mirror as materials


def certificates(root):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key=ec.generate_private_key(ec.SECP256R1());name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'CTFLab fixture only')])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
          .not_valid_after(now+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
          .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
          .sign(key,hashes.SHA256()))
    certificate=root/'fixture-cert.pem';private=root/'fixture-key.pem'
    for path,data in ((certificate,cert.public_bytes(serialization.Encoding.PEM)),
                      (private,key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))):
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(data)
    return certificate,private


class ServiceTests(materials.MirrorTests):
    # 只复用材料的真实签名/cache夹具；原材料测试仍由其原测试类运行。
    def setUp(self):
        super().setUp();self.payload['expires']='2099-01-01T00:00:00Z'
        self.prepare();self.build()
        self.cert,self.key_path=certificates(self.root)
        self.context=ssl.create_default_context(cafile=str(self.cert))
    def start(self,**kwargs):
        self.view=MirrorView(self.destination,self.keys,self.source)
        self.server=MirrorServer(self.view,self.cert,self.key_path,**kwargs)
        self.thread=threading.Thread(target=lambda:self.server.serve_forever(poll_interval=.01));self.thread.start()
        def stop():self.server.shutdown();self.server.server_close();self.thread.join(5);self.assertFalse(self.thread.is_alive())
        self.addCleanup(stop)
        self.url='https://127.0.0.1:'+str(self.server.server_port)+'/'
    def request(self,path,*,method='GET',headers=None,context=None):
        connection=HTTPSConnection('127.0.0.1',self.server.server_port,context=context or self.context,timeout=5)
        try:
            connection.request(method,path,headers=headers or {});reply=connection.getresponse()
            return reply.status,dict(reply.getheaders()),reply.read()
        finally:connection.close()
    # 不重复继承仅材料准备阶段的测试，这里调用其setUp等夹具后已有导出目录。
    test_signed_student_export_keeps_exact_content_and_signature=None
    test_teacher_or_recipe_entry_refused_before_creating_anything=None
    test_windows_alias_path_rejected=None
    test_missing_or_changed_cache_not_exported=None
    test_explicit_mirror_changes_transport_url_only=None
    test_non_https_mirror_rejected_before_network_call=None

    def test_tls_index_and_asset_get_and_head_are_exact(self):
        self.start()
        for path,expected in (('/INDEX.json',(self.destination/'INDEX.json').read_bytes()),('/assets/linux.qcow2',self.data)):
            status,headers,data=self.request(path);self.assertEqual(status,200);self.assertEqual(data,expected)
            self.assertEqual(int(headers['Content-Length']),len(expected));self.assertEqual(headers['Connection'],'close')
            status,headers,data=self.request(path,method='HEAD');self.assertEqual(status,200);self.assertEqual(data,b'')
            self.assertEqual(int(headers['Content-Length']),len(expected))
        self.assertEqual(self.server.server_address[0],'127.0.0.1')
    def test_actual_content_cache_resumes_through_trusted_mirror_without_origin_change(self):
        self.start();cache=ContentCache.create(self.root/'client-cache');cache.accept(self.envelope(),self.keys,self.source)
        fd=os.open(cache.root/'partial'/self.sha,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(self.data[:37])
        opener=build_opener(NoRedirect(),HTTPSHandler(context=self.context)).open
        final=cache.download(self.source,self.sha,mirror=self.url,opener=opener)
        self.assertEqual(final.read_bytes(),self.data);self.assertEqual(digest(final),self.sha)
        with cache.locked() as db:self.assertEqual(db.execute('SELECT source FROM indexes').fetchone()[0],self.source)
    def test_partial_full_suffix_and_unsatisfied_range(self):
        self.start()
        for header,expected in (('bytes=5-9',self.data[5:10]),('bytes=5-',self.data[5:]),('bytes=-7',self.data[-7:]),('bytes=0-999999',self.data)):
            status,headers,data=self.request('/assets/linux.qcow2',headers={'Range':header})
            self.assertEqual(status,206);self.assertEqual(data,expected);self.assertIn('Content-Range',headers)
        for header in ('bytes=9000-','bytes=-0','bytes=5-4','bytes=0-1,4-5','items=0-1','bytes='+('1'*100)+'-'):
            status,headers,data=self.request('/assets/linux.qcow2',headers={'Range':header})
            self.assertEqual(status,416);self.assertEqual(data,b'');self.assertEqual(headers['Content-Range'],'bytes */'+str(len(self.data)))
    def test_if_range_changed_tag_returns_full_content(self):
        self.start();status,headers,data=self.request('/assets/linux.qcow2',headers={'Range':'bytes=5-','If-Range':'"old"'})
        self.assertEqual(status,200);self.assertEqual(data,self.data)
    def test_only_exact_allowlist_no_directory_receipt_query_or_traversal(self):
        self.start()
        for path in ('/','/MIRROR.json','/fixture-key.pem','/../INDEX.json','/%49NDEX.json','/INDEX.json?x=1','//INDEX.json','/assets/','/assets/../INDEX.json'):
            with self.subTest(path=path):
                status,headers,data=self.request(path);self.assertEqual(status,404);self.assertEqual(data,b'')
    def test_post_put_delete_never_modify_files(self):
        self.start();before=(self.destination/'INDEX.json').read_bytes()
        for method in ('POST','PUT','DELETE','OPTIONS'):
            status,_,_=self.request('/INDEX.json',method=method);self.assertEqual(status,501)
        self.assertEqual((self.destination/'INDEX.json').read_bytes(),before)
    def test_expired_or_changed_files_refuse_before_body(self):
        self.start();self.view.now=lambda:datetime(2100,1,1,tzinfo=timezone.utc)
        status,_,data=self.request('/assets/linux.qcow2');self.assertEqual((status,data),(503,b''))
        self.view.now=lambda:datetime.now(timezone.utc)
        (self.destination/'assets/linux.qcow2').write_bytes(b'changed')
        status,_,data=self.request('/assets/linux.qcow2');self.assertEqual((status,data),(503,b''))
    def test_same_bytes_replacement_or_changed_index_refuse(self):
        self.start();path=self.destination/'assets/linux.qcow2';copy=path.with_name('replacement');copy.write_bytes(self.data);copy.chmod(0o600);copy.replace(path)
        status,_,data=self.request('/assets/linux.qcow2');self.assertEqual((status,data),(503,b''))
        (self.destination/'INDEX.json').write_bytes(b'changed')
        status,_,data=self.request('/INDEX.json');self.assertEqual((status,data),(503,b''))
    def test_untrusted_tls_certificate_refused_and_plain_http_not_served(self):
        self.start()
        with self.assertRaises(ssl.SSLCertVerificationError):self.request('/INDEX.json',context=ssl.create_default_context())
        with socket.create_connection(self.server.server_address,timeout=2) as stream:
            stream.settimeout(2);stream.sendall(b'GET /INDEX.json HTTP/1.0\r\n\r\n')
            try:data=stream.recv(100)
            except (ConnectionResetError,ssl.SSLError):data=b''
            self.assertNotIn(b'HTTP/',data)
    def test_tls_handshake_wait_does_not_block_other_accepts(self):
        self.start(maximum=2)
        with socket.create_connection(self.server.server_address,timeout=2):
            status,_,data=self.request('/INDEX.json');self.assertEqual(status,200);self.assertTrue(data)
    def test_maximum_slots_refuse_and_release_after_disconnect(self):
        self.start(maximum=1);self.assertTrue(self.server.slots.acquire(blocking=False))
        try:
            with self.assertRaises((OSError,ssl.SSLError)):self.request('/INDEX.json')
        finally:self.server.slots.release()
        status,_,_=self.request('/INDEX.json');self.assertEqual(status,200)
    def test_lan_binding_limits_invalid_certificate_or_missing_signature_refuse(self):
        view=MirrorView(self.destination,self.keys,self.source)
        for kwargs in ({'host':'0.0.0.0'},{'host':'::1'},{'maximum':9},{'port':True}):
            with self.assertRaises(ContractError):MirrorServer(view,self.cert,self.key_path,**kwargs)
        with self.assertRaises(ContractError):MirrorView(self.destination,{},self.source)
        (self.destination/'assets/linux.qcow2').write_bytes(b'changed')
        with self.assertRaises(ContractError):MirrorView(self.destination,self.keys,self.source)
    def test_receipt_teacher_policy_and_unlisted_extra_files_never_become_public(self):
        extra=self.destination/'teacher-private.txt';extra.write_text('不在索引中的教师资料');extra.chmod(0o600)
        self.start();status,_,data=self.request('/teacher-private.txt');self.assertEqual((status,data),(404,b''))
        path=self.destination/'MIRROR.json';value=json.loads(path.read_text());value['teacher_materials_included']=True
        path.write_text(json.dumps(value))
        with self.assertRaises(ContractError):MirrorView(self.destination,self.keys,self.source)
    def test_symbolic_link_and_hard_link_refuse_even_when_bytes_match(self):
        self.start();asset=self.destination/'assets/linux.qcow2';original=self.destination/'copy.qcow2'
        asset.rename(original);asset.symlink_to(original)
        status,_,data=self.request('/assets/linux.qcow2');self.assertEqual((status,data),(503,b''))
        with self.assertRaises(ContractError):MirrorView(self.destination,self.keys,self.source)
        asset.unlink();os.link(original,asset)
        status,_,data=self.request('/assets/linux.qcow2');self.assertEqual((status,data),(503,b''))
        with self.assertRaises(ContractError):MirrorView(self.destination,self.keys,self.source)
    def test_empty_ranges_and_invalid_numbers_refuse(self):
        for raw in ('bytes=-','bytes=+1-','bytes=1.1-','bytes= 1-','bytes=1-2\r\nInjected: x'):
            with self.assertRaises(ContractError):byte_range(raw,len(self.data))
    def test_even_signed_student_entries_cannot_publish_active_tls_credentials(self):
        asset=self.destination/'assets/linux.qcow2'
        for source in (self.key_path,self.cert):
            data=source.read_bytes();sha=hashlib.sha256(data).hexdigest();asset.write_bytes(data)
            self.payload['assets']={sha:{'path':'assets/linux.qcow2','size':len(data),'audience':'student','redistribution':'allowed'}}
            (self.destination/'INDEX.json').write_text(canonical(self.envelope()))
            receipt_path=self.destination/'MIRROR.json';receipt=json.loads(receipt_path.read_text())
            receipt.update(files={'assets/linux.qcow2':sha},signed_index_sha256=hashlib.sha256(canonical(self.payload).encode()).hexdigest())
            receipt_path.write_text(canonical(receipt))
            view=MirrorView(self.destination,self.keys,self.source)
            certificate,key=(self.cert,asset) if source==self.key_path else (asset,self.key_path)
            with self.assertRaises(ContractError):MirrorServer(view,certificate,key)


if __name__=='__main__':unittest.main()
