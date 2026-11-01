"""本机进程适配入口；标准输入不是跨用户认证通道，不开放网络监听。"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sqlite3
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctflab_contract import (ContractError, MAX_MESSAGE_BYTES, PROTOCOL, VERSION,
                             canonical, parse_request, public_error, require)
from ctflab_local_service import LocalService


def process_actor():
    """取得普通本机进程身份；不接受请求体或线程模拟主体。"""
    if os.name == 'nt':
        from ctflab_windows_security import WindowsSecurity
        from ctflab_windows_native import NativeError
        try:
            sid = WindowsSecurity().current_user()
        except NativeError:
            raise ContractError('permission-denied') from None
        return 'win-sid-' + hashlib.sha256(sid.encode('ascii')).hexdigest()
    require(os.name == 'posix', 'unsupported-platform')
    require(os.getuid() == os.geteuid() and os.getgid() == os.getegid(), 'permission-denied')
    require(os.geteuid() != 0, 'permission-denied')
    return 'local-uid-' + str(os.geteuid())


def failure(code, *, result='failed'):
    require(result in ('failed', 'unknown'))
    return {'protocol': PROTOCOL, 'version': VERSION, 'request_id': None,
            'instance_uuid': None, 'operation_id': None, 'generation': None,
            'state_revision': None, 'state': 'unknown', 'cursor': 0,
            'result': result, 'cancelled': False, 'error': public_error(code),
            'evidence_refs': []}


class LocalAdapter:
    """CLI/界面共用边界；后端只能由受信宿主代码注入，消息不能选择后端。"""
    def __init__(self, root, *, backend=None):
        self.actor = process_actor()
        self.service = LocalService(root)
        self.backend = backend

    def dispatch(self, text):
        try:
            # 每次检查身份，防止宿主改变有效身份后继续沿用旧主体。
            require(process_actor() == self.actor, 'permission-denied')
            req = parse_request(text)
            require(req['operation'] == 'status' or self.backend is not None,
                    'capability-unverified')
            response = self.service.submit(req, self.actor)
            if (self.backend is not None and req['operation'] not in {'status', 'cancel'}
                    and response['result'] == 'accepted'):
                return self.service.execute(response['operation_id'], self.actor, self.backend)
            return response
        except ContractError as exc:
            return failure(exc.code)
        except (OSError, sqlite3.Error):
            return failure('persistence-failed', result='unknown')

    def events(self, instance_uuid, *, after=0, limit=100):
        try:
            require(process_actor() == self.actor, 'permission-denied')
            return self.service.events(instance_uuid, self.actor, after=after, limit=limit)
        except ContractError as exc:
            return failure(exc.code)
        except (OSError, sqlite3.Error):
            return failure('persistence-failed', result='unknown')

    def history(self, instance_uuid, *, operation_id=None, limit=20, before=None):
        """窗口/CLI重开后只读查询原账本；不领取、提交或重发任何操作。"""
        try:
            require(process_actor() == self.actor, 'permission-denied')
            return (self.service.operation_result(instance_uuid, operation_id, self.actor) if operation_id is not None
                    else self.service.operation_history(instance_uuid, self.actor, limit=limit, before=before))
        except ContractError as exc:
            return failure(exc.code)
        except (OSError, sqlite3.Error):
            return failure('persistence-failed', result='unknown')


def serve(adapter, source, destination):
    """UTF-8 JSON 行；超长/未终止帧关闭会话，避免将尾部误当下一条命令。"""
    while True:
        frame = source.readline(MAX_MESSAGE_BYTES + 2)
        if not frame:
            return 0
        if not frame.endswith(b'\n') or len(frame) > MAX_MESSAGE_BYTES + 1:
            destination.write((canonical(failure('invalid-request')) + '\n').encode())
            destination.flush()
            return 2
        try:
            text = frame[:-1].decode('utf-8', errors='strict')
            response = adapter.dispatch(text)
        except UnicodeError:
            response = failure('invalid-request')
        destination.write((canonical(response) + '\n').encode())
        destination.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description='CTFLab 本地契约只读入口（不启动 VM）')
    parser.add_argument('--root', required=True, help='已创建的私有契约目录；不自动初始化或迁移')
    parser.add_argument('--history', help='只读列出该实例的持久操作；不读取标准输入或派发')
    parser.add_argument('--operation', help='与--history一起按原操作UUID读取已保存结果')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--before', help='只读历史分页：前页next_before操作UUID')
    args = parser.parse_args(argv)
    try:
        adapter = LocalAdapter(args.root)
        require(args.history is not None or (args.operation is None and args.before is None and args.limit == 20))
        require(args.operation is None or (args.before is None and args.limit == 20))
        if args.history is not None:
            reply = adapter.history(args.history, operation_id=args.operation, limit=args.limit, before=args.before)
            print(canonical(reply)); return 2 if reply.get('error') else 0
        return serve(adapter, sys.stdin.buffer, sys.stdout.buffer)
    except ContractError as exc:
        print(canonical(failure(exc.code)))
        return 2
    except (OSError, sqlite3.Error):
        print(canonical(failure('persistence-failed', result='unknown')))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
