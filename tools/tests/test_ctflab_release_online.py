"""签名在线准备、断线续传与原请求恢复；固定内存HTTPS替身，不下载真实版本。"""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import canonical,ContractError
from ctflab_release_online import OnlineRelease,metadata
from ctflab_generation_store import digest
from ctflab_release_store import release_manifest
import test_ctflab_release_store as fixtures


class Response(io.BytesIO):
    def __init__(self,data,url,offset=0):
        super().__init__(data[offset:]);self.url=url;self.status=206 if offset else 200
        self.headers={'Content-Length':str(len(data)-offset)}
        if offset:self.headers['Content-Range']=f'bytes {offset}-{len(data)-1}/{len(data)}'
    def geturl(self):return self.url


class OnlineTests(unittest.TestCase):
    setUp=fixtures.ReleaseTests.setUp
    def configure(self):
        self.location='https://updates.example.invalid/stable/';self.maximum=1024**2;self.target='a'*64
        self.data={'ctflab-desktop':b'not-executed-binary','LICENSE':b'fixture license','empty':b''}
        self.payload={'schema':2,'version':'0.2.0','data_schema':1,
            'files':{n:hashlib.sha256(v).hexdigest() for n,v in self.data.items()},'licenses':['LICENSE'],
            'launch':{'platform':'linux-x64','entry':'ctflab-desktop','executables':['ctflab-desktop']}}
        self.index={'schema':1,'sequence':1,'expires':'2099-01-01T00:00:00Z','source':self.location,
            'assets':{hashlib.sha256(v).hexdigest():{'path':'objects/'+hashlib.sha256(v).hexdigest(),'size':len(v),
                'audience':'student','redistribution':'allowed'} for v in self.data.values() if v}}
        self.calls=[];self.failure=False;self.corrupt=False
        self.online=OnlineRelease(self.store.root,self.keys,self.target,opener=self.open)
    def signed(self,payload):
        return {'payload':payload,'key_id':'main','signature':base64.b64encode(self.key.sign(canonical(payload).encode())).decode()}
    def open(self,request,timeout):
        url=request.full_url;self.calls.append((url,request.get_header('Range')))
        if url.endswith('INDEX.json'):return Response(canonical(self.signed(self.index)).encode(),url)
        if url.endswith('RELEASE.json'):return Response(canonical(self.signed(self.payload)).encode(),url)
        sha=url.rsplit('/',1)[1];data=next(v for v in self.data.values() if hashlib.sha256(v).hexdigest()==sha)
        offset=int(request.get_header('Range').split('=')[1].split('-')[0]) if request.has_header('Range') else 0
        if self.failure:
            self.failure=False
            class Broken(Response):
                def read(self,size=-1):
                    if self.tell():raise OSError('合成断网')
                    return super().read(3)
                def read1(self,size=-1):return self.read(size)
            return Broken(data,url,offset)
        if self.corrupt:data=b'x'*len(data)
        return Response(data,url,offset)
    def preview(self):return self.online.preview(self.location,self.maximum)
    def download(self,preview,operation=None):
        return self.online.prepare(self.location,self.maximum,preview['plan_sha256'],operation or str(uuid.uuid4()))

    def test_preview_only_fetches_metadata_and_does_not_create_cache_or_version(self):
        self.configure();value=self.preview()
        self.assertEqual(value['bytes'],sum(map(len,self.data.values())))
        self.assertFalse(value['downloaded']);self.assertEqual(len(self.calls),2)
        self.assertFalse((self.store.root/'online-cache').exists());self.assertEqual(self.store.status()['versions'],[])

    def test_download_empty_file_signatures_and_explicit_later_stage(self):
        self.configure();result=self.download(self.preview())
        self.assertFalse(result['activated']);self.assertEqual(self.store.status()['versions'],[])
        for name,data in self.data.items():self.assertEqual((Path(result['source'])/name).read_bytes(),data)
        signed=json.loads(Path(result['manifest']).read_text())
        self.store.stage(Path(result['source']),signed,self.keys)
        self.assertEqual(self.store.status()['versions'],['0.2.0']);self.assertIsNone(self.store.status()['active'])
        self.assertFalse(self.online.history()[0]['files_currently_reverified'])

    def test_disconnect_resume_keeps_same_operation_and_verified_cache(self):
        self.configure();preview=self.preview();operation=str(uuid.uuid4());self.failure=True
        with self.assertRaises(OSError):self.download(preview,operation)
        parts=list((self.store.root/'online-cache/partial').iterdir());self.assertEqual(parts[0].stat().st_size,3)
        restored=self.online.restore(operation);self.assertFalse(restored['network_sent'])
        count=len(self.calls);self.online.restore(operation);self.assertEqual(len(self.calls),count)
        value=self.download(preview,operation);self.assertEqual(value['operation_id'],operation)
        self.assertTrue(any(header=='bytes=3-' for _,header in self.calls))
        self.assertTrue((self.store.root/'online-cache/objects'/parts[0].name).is_file())

    def test_changed_plan_target_or_existing_partial_file_refuses_without_overwrite(self):
        self.configure();preview=self.preview();self.payload['version']='0.3.0'
        with self.assertRaises(ContractError):self.download(preview)
        self.assertFalse((self.store.root/'online-cache').exists())
        preview=self.preview();operation=str(uuid.uuid4());value=self.download(preview,operation)
        path=Path(value['source'])/'LICENSE';path.write_bytes(b'preserved-user-change')
        with self.assertRaises(ContractError):self.download(preview,operation)
        self.assertEqual(path.read_bytes(),b'preserved-user-change')
        with self.assertRaises(ContractError):OnlineRelease(self.store.root,self.keys,'b'*64,opener=self.open).restore(operation)

    def test_bad_metadata_signature_expiry_license_or_missing_asset_prevents_payload_download(self):
        for change in ('expiry','license','missing','key'):
            self.configure()
            if change=='expiry':self.index['expires']='2000-01-01T00:00:00Z'
            elif change=='license':next(iter(self.index['assets'].values()))['redistribution']='recipe-only'
            elif change=='missing':self.index['assets'].clear()
            else:self.online.keys={}
            with self.subTest(change=change),self.assertRaises(ContractError):self.preview()
            self.assertTrue(all(url.endswith('.json') for url,_ in self.calls))

    def test_budget_type_bound_and_size_check(self):
        self.configure()
        for maximum in (True,0,17*1024**3):
            with self.assertRaises(ContractError):self.online.preview(self.location,maximum)
        self.assertEqual(self.calls,[])
        next(iter(self.index['assets'].values()))['size']=2*1024**2
        with self.assertRaises(ContractError):self.preview()

    def test_corrupt_download_is_quarantined_and_not_staged(self):
        self.configure();preview=self.preview();self.corrupt=True
        with self.assertRaises(ContractError):self.download(preview)
        self.assertTrue(list((self.store.root/'online-cache/quarantine').iterdir()))
        self.assertEqual(self.store.status()['versions'],[])
        self.assertEqual(self.online.history()[0]['state'],'partial-preserved')

    def test_metadata_redirect_encoding_duplicate_keys_and_length_are_rejected(self):
        self.configure();url=self.location+'INDEX.json'
        for change in ('redirect','encoding','duplicate','length'):
            data=b'{"a":1,"a":2}' if change=='duplicate' else b'{}'
            response=Response(data,url)
            if change=='redirect':response.url='https://other.invalid/'
            elif change=='encoding':response.headers['Content-Encoding']='gzip'
            elif change=='length':response.headers['Content-Length']='999999999'
            with self.subTest(change=change),self.assertRaises(ContractError):metadata(url,lambda *a,**k:response,128)

    def test_completed_retry_reverifies_and_does_not_request_payload_again(self):
        self.configure();preview=self.preview();operation=str(uuid.uuid4());value=self.download(preview,operation)
        self.calls.clear();self.assertEqual(self.download(preview,operation),value)
        self.assertEqual(len(self.calls),2)

    def test_cancel_before_prepare_makes_no_network_request(self):
        self.configure();preview=self.preview();operation=str(uuid.uuid4())
        result=self.online.cancel(operation,str(uuid.uuid4()));before=len(self.calls)
        with self.assertRaises(ContractError):self.download(preview,operation)
        self.assertEqual(len(self.calls),before);self.assertFalse(result['network_sent'])
        self.assertFalse((self.store.root/'online-downloads').exists())

    def test_pause_during_cache_lock_preserves_prefix_and_explicit_resume(self):
        self.configure();preview=self.preview();operation=str(uuid.uuid4());original=self.open;paused=[False]
        outer=self
        def opened(request,timeout):
            response=original(request,timeout)
            if not request.full_url.endswith('.json') and not paused[0]:
                class Paused(Response):
                    def read1(self,size=-1):
                        if self.tell()==3:
                            paused[0]=True;outer.online.cancel(operation,str(uuid.uuid4()))
                        return super().read1(min(size,3))
                return Paused(response.getvalue(),request.full_url)
            return response
        self.online.opener=opened
        with self.assertRaises(ContractError):self.download(preview,operation)
        part=list((self.store.root/'online-cache/partial').iterdir())[0]
        self.assertEqual(part.stat().st_size,3);self.assertTrue(self.online.history()[0]['pause_recorded'])
        before=len(self.calls);restored=self.online.restore(operation)
        self.assertFalse(restored['network_sent']);self.assertEqual(len(self.calls),before)
        with self.assertRaises(ContractError):self.download(preview,operation)
        result=self.online.prepare(self.location,self.maximum,preview['plan_sha256'],operation,
            resume_sha256=restored['request']['resume_sha256'])
        self.assertEqual(result['state'],'online-files-verified');self.assertFalse(self.online.cancelled(operation))
        self.assertTrue(any(header=='bytes=3-' for _,header in self.calls))
        self.assertTrue(list((self.store.root/'online-cancellations').glob('*.resumed.json')))

    def test_old_resume_receipt_cannot_clear_new_pause(self):
        self.configure();preview=self.preview();operation=str(uuid.uuid4())
        first=self.online.cancel(operation,str(uuid.uuid4()))
        self.online.prepare(self.location,self.maximum,preview['plan_sha256'],operation,resume_sha256=first['cancel_sha256'])
        second=self.online.cancel(operation,str(uuid.uuid4()));self.assertNotEqual(first['cancel_sha256'],second['cancel_sha256'])
        before=len(self.calls)
        with self.assertRaises(ContractError):self.online.prepare(self.location,self.maximum,preview['plan_sha256'],operation,resume_sha256=first['cancel_sha256'])
        self.assertTrue(self.online.cancelled(operation));self.assertEqual(len(self.calls),before)

    def test_stale_plan_resume_does_not_clear_pause_before_plan_is_verified(self):
        self.configure();preview=self.preview();operation=str(uuid.uuid4())
        paused=self.online.cancel(operation,str(uuid.uuid4()));self.payload['version']='0.3.0'
        with self.assertRaises(ContractError):self.online.prepare(self.location,self.maximum,preview['plan_sha256'],operation,resume_sha256=paused['cancel_sha256'])
        self.assertTrue(self.online.cancelled(operation))

    def test_pause_arriving_during_resume_preview_supersedes_old_resume(self):
        self.configure();preview=self.preview();operation=str(uuid.uuid4())
        first=self.online.cancel(operation,str(uuid.uuid4()));original=self.online.plan;new=[]
        def plan(*args,**kwargs):
            result=original(*args,**kwargs);new.append(self.online.cancel(operation,str(uuid.uuid4())));return result
        with patch.object(self.online,'plan',side_effect=plan):
            with self.assertRaises(ContractError):self.online.prepare(self.location,self.maximum,preview['plan_sha256'],operation,resume_sha256=first['cancel_sha256'])
        self.assertNotEqual(new[0]['cancel_sha256'],first['cancel_sha256'])
        self.assertEqual(digest(self.online._cancel_path(operation)),new[0]['cancel_sha256'])

    def test_replayed_cancel_identifier_does_not_pause_again_or_replace_new_pause(self):
        self.configure();preview=self.preview();operation=str(uuid.uuid4());cancel_id=str(uuid.uuid4())
        first=self.online.cancel(operation,cancel_id)
        self.online.prepare(self.location,self.maximum,preview['plan_sha256'],operation,resume_sha256=first['cancel_sha256'])
        self.assertFalse(self.online.cancel(operation,cancel_id)['pause_recorded'])
        self.assertFalse(self.online.cancelled(operation))
        latest=self.online.cancel(operation,str(uuid.uuid4()))
        self.assertEqual(self.online.cancel(operation,cancel_id)['cancel_sha256'],latest['cancel_sha256'])


if __name__=='__main__':unittest.main()
