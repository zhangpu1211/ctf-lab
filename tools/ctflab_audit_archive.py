"""审计库一致快照与可携带签名封存；不自动换库、不上传、不把签名当外部可信锚。"""
import argparse
import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,identifier,uuid_text
from ctflab_generation_store import digest,private_directory
from ctflab_tls_endpoint import guard
from ctflab_remote import private_json
from ctflab_remote_audit import AuditStore,ZERO


def seal(store,destination,signing):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    require(type(signing) is dict and set(signing)=={'key_id','private_key_hex'})
    identifier(signing['key_id']);require(type(signing['private_key_hex']) is str and len(signing['private_key_hex'])==64)
    key=Ed25519PrivateKey.from_private_bytes(bytes.fromhex(signing['private_key_hex']))
    destination=Path(destination).absolute();require(destination!=store.root and store.root not in destination.parents
        and destination not in store.root.parents,'permission-denied')
    with store.transaction() as db:
        events=store.verify(db);pending=db.execute('SELECT COUNT(*) FROM attempts WHERE completed=0').fetchone()[0]
        require(guard(store.root/'audit.sqlite3').stat().st_size<=64*1024**2,'storage-insufficient')
        private_directory(destination)
        target=destination/'audit.sqlite3';fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        with closing(sqlite3.connect(target)) as snapshot:db.backup(snapshot)
        copied=AuditStore({'root':str(destination),'max_attempts':store.config['max_attempts']},store.server)
        with copied.transaction() as snapshot:require(copied.verify(snapshot)==events,'identity-unknown')
        payload={'schema':1,'kind':'ctflab-audit-snapshot','server_uuid':store.server,'capacity':store.config['max_attempts'],
            'head_seq':len(events),'head_sha256':events[-1]['sha256'] if events else ZERO,'pending_count':pending,
            'database_sha256':digest(target),'database_bytes':target.stat().st_size,
            'original_worker_results_preserved':True,'vm_observed':False,'externally_anchored':False}
        envelope={'key_id':signing['key_id'],'payload':payload,
            'signature':base64.b64encode(key.sign(canonical(payload).encode())).decode()}
        fd=os.open(destination/'CHECKPOINT.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(canonical(envelope));stream.flush();os.fsync(stream.fileno())
    return {'state':'signed-snapshot-created','key_id':signing['key_id'],'head_seq':payload['head_seq'],
        'head_sha256':payload['head_sha256'],'database_sha256':payload['database_sha256'],
        'pending_count':pending,'original_audit_modified':False,'policy_changed':False,'uploaded':False,'externally_anchored':False}


def verify(directory,keys):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    directory=guard(Path(directory).absolute())
    require({p.name for p in directory.iterdir()}=={'audit.sqlite3','CHECKPOINT.json'},'identity-unknown')
    envelope=private_json(directory/'CHECKPOINT.json')
    require(type(envelope) is dict and set(envelope)=={'key_id','payload','signature'}
            and type(envelope['key_id']) is str and type(keys) is dict and envelope['key_id'] in keys
            and type(envelope['signature']) is str and len(envelope['signature'])<=128,'permission-denied')
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(keys[envelope['key_id']])).verify(
        base64.b64decode(envelope['signature'],validate=True),canonical(envelope['payload']).encode())
    payload=envelope['payload']
    expected={'schema','kind','server_uuid','capacity','head_seq','head_sha256','pending_count','database_sha256',
        'database_bytes','original_worker_results_preserved','vm_observed','externally_anchored'}
    require(type(payload) is dict and set(payload)==expected and type(payload['schema']) is int and payload['schema']==1
            and payload['kind']=='ctflab-audit-snapshot' and payload['original_worker_results_preserved'] is True
            and payload['vm_observed'] is False and payload['externally_anchored'] is False,'identity-unknown')
    uuid_text(payload['server_uuid']);target=guard(directory/'audit.sqlite3');info=target.stat()
    require(target.is_file() and info.st_nlink==1 and info.st_size<=64*1024**2
            and info.st_size==payload['database_bytes'] and digest(target)==payload['database_sha256'],'identity-unknown')
    store=AuditStore({'root':str(directory),'max_attempts':payload['capacity']},payload['server_uuid'])
    with store.transaction() as db:
        events=store.verify(db)
        require(type(payload['head_seq']) is int and len(events)==payload['head_seq']
            and payload['head_sha256']==(events[-1]['sha256'] if events else ZERO)
            and type(payload['pending_count']) is int
            and db.execute('SELECT COUNT(*) FROM attempts WHERE completed=0').fetchone()[0]==payload['pending_count'],'identity-unknown')
    return {'state':'signed-snapshot-verified','key_id':envelope['key_id'],'head_seq':len(events),
        'head_sha256':payload['head_sha256'],'database_sha256':payload['database_sha256'],
        'pending_count':payload['pending_count'],'externally_anchored':False,'vm_observed':False,'audit_modified':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('seal','verify'))
    parser.add_argument('--directory',required=True,type=Path);parser.add_argument('--policy',type=Path)
    parser.add_argument('--signing-key',type=Path);parser.add_argument('--keys',type=Path);args=parser.parse_args(argv)
    try:
        if args.action=='seal':
            require(args.policy is not None and args.signing_key is not None and args.keys is None)
            from ctflab_audit_review import AuditReview
            review=AuditReview(args.policy)
            from ctflab_server_storage import verify as verify_storage
            verify_storage(review.policy,extra={'audit-export':args.directory.absolute()})
            result=seal(review.audit,args.directory,private_json(args.signing_key))
        else:
            require(args.keys is not None and args.policy is None and args.signing_key is None)
            result=verify(args.directory,private_json(args.keys))
        print(canonical(result));return 0
    except Exception:
        print(canonical({'state':'refused-or-partial','preserved':True,'uploaded':False,'policy_changed':False}));return 2


if __name__=='__main__':raise SystemExit(main())
