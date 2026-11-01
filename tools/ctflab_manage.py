"""独立版本管理CLI；部署在版本树外，复用签名/摘要/停机门，不自动停止实验。"""
import argparse
from pathlib import Path
import sqlite3
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,ContractError,public_error
from ctflab_version_bridge import VersionBridge


def main(argv=None,*,factory=VersionBridge):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True);parser.add_argument('--expected-target')
    sub=parser.add_subparsers(dest='action',required=True)
    for action in ('status','initialize','launch-preview'):sub.add_parser(action)
    command=sub.add_parser('register');command.add_argument('--workspace',required=True)
    command=sub.add_parser('stage');command.add_argument('--source',required=True);command.add_argument('--manifest',required=True)
    for action in ('online-preview','online-download'):
        command=sub.add_parser(action);command.add_argument('--source',required=True)
        command.add_argument('--maximum',type=int,default=4*1024**3)
        if action=='online-download':
            command.add_argument('--plan-sha256',required=True);command.add_argument('--operation-id',required=True)
            command.add_argument('--resume-sha256')
    command=sub.add_parser('online-cancel');command.add_argument('--operation-id',required=True);command.add_argument('--cancel-id',required=True)
    for action in ('online-restore','abandon'):
        command=sub.add_parser(action);command.add_argument('--operation-id',required=True)
    for action in ('update-preview','update-apply'):
        command=sub.add_parser(action);command.add_argument('--version',required=True)
        if action=='update-apply':
            command.add_argument('--plan-sha256',required=True);command.add_argument('--operation-id',required=True)
    command=sub.add_parser('launch');command.add_argument('--plan-sha256',required=True)
    args=parser.parse_args(argv)
    try:
        bridge=factory(args.config)
        value={k:v for k,v in vars(args).items() if k not in ('config','expected_target') and v is not None}
        if args.action!='status':
            require(args.expected_target==bridge.target,'identity-unknown')
            require(bridge.store.root/'versions' not in Path(__file__).resolve().parents,'permission-denied')
            value['target']=args.expected_target
        result=bridge.handle(value);print(canonical(result));return 0
    except ContractError as error:
        print(canonical({'state':'refused-or-unknown','error':public_error(error.code),
            'automatic_stop':False,'automatic_replay':False,'preserved':True}));return 2
    except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error):
        print(canonical({'state':'refused-or-unknown','automatic_stop':False,'automatic_replay':False,'preserved':True}));return 2


if __name__=='__main__':raise SystemExit(main())
