"""生成助手边界：实际私有文件、链接与摘要；socket凭据/降权exec用API桩，不操作Kali。"""
import io
import os
import socket
import stat
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_ctflab_kali_attach_functions import load_assistant
import ctflab_kali_attach as host_module
from ctflab_kali_attach import raw_command as host_raw_command


@unittest.skipUnless(os.name=='posix','来宾Linux助手的POSIX函数边界')
class KaliSecurityTests(unittest.TestCase):
    def setUp(self):
        self.ns=load_assistant()
        temp=tempfile.TemporaryDirectory(dir=str(Path.home()))
        self.addCleanup(temp.cleanup);self.root=Path(temp.name).resolve()
        self.file=self.root/'tool';self.file.write_bytes(b'fixture');self.file.chmod(0o755)
    def checked(self,path,**kwargs):
        return self.ns['trusted_path'](str(path),owner_uid=os.getuid(),**kwargs)
    def test_real_file_and_root_managed_style_symlink_resolve(self):
        alias=self.root/'alias';alias.symlink_to(self.file)
        self.assertEqual(self.checked(alias),str(self.file))
    def test_writable_component_before_dotdot_is_not_skipped(self):
        bad=self.root/'writable';bad.mkdir();bad.chmod(0o777)
        alias=self.root/'alias';alias.symlink_to('writable/../tool')
        with self.assertRaises(OSError):self.checked(alias)
    def test_writable_file_or_ancestor_and_hardlink_refused(self):
        self.file.chmod(0o777)
        with self.assertRaises(OSError):self.checked(self.file)
        self.file.chmod(0o755);other=self.root/'hard';os.link(self.file,other)
        with self.assertRaises(OSError):self.checked(self.file)
    def test_symlink_cycle_and_regular_file_ancestor_refused(self):
        a=self.root/'a';b=self.root/'b';a.symlink_to(b);b.symlink_to(a)
        with self.assertRaises(OSError):self.checked(a)
        with self.assertRaises(OSError):self.checked(str(self.file)+'/../tool')
    def test_private_directory_requires_private_bits(self):
        self.root.chmod(0o755)
        with self.assertRaises(OSError):self.checked(self.root,directory=True,private=True)
    def test_live_tool_digest_change_refuses_exec(self):
        check=self.ns['trusted_path']
        self.ns['trusted_path']=lambda path,**kw:check(path,owner_uid=os.getuid(),**kw)
        self.ns['TOOLS']['ip']={'logical':str(self.file),'path':str(self.file),'sha256':self.ns['file_digest'](str(self.file))}
        self.assertEqual(self.ns['command_path']('ip'),str(self.file))
        self.file.write_bytes(b'changed')
        with self.assertRaises(OSError):self.ns['command_path']('ip')
    def test_network_commands_use_fixed_path_and_sterile_env(self):
        self.ns['command_path']=lambda _: '/usr/sbin/ip'
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(self.ns['run'](['ip','link','show']),0)
            self.assertEqual(run.call_args.args[0],['/usr/sbin/ip','link','show'])
            self.assertEqual(run.call_args.kwargs['env'],self.ns['SYSTEM_ENV'])
            self.assertEqual(run.call_args.kwargs['timeout'],5)
            run.reset_mock();self.assertEqual(self.ns['run'](['/tmp/fake-ip']),1);run.assert_not_called()
    def test_shell_has_no_new_privileges_or_inherited_secrets(self):
        self.ns['command_path']=lambda name:{'ip':'/usr/sbin/ip','setpriv':'/usr/bin/setpriv','shell':'/usr/bin/dash'}[name]
        sid='11111111-2222-4333-8444-555555555555'
        grant={'session':sid,'netns':self.ns['netns_name'](sid)}
        account=SimpleNamespace(pw_uid=1001,pw_gid=1001,pw_dir='/home/ctflab-attach',pw_name='ctflab-attach')
        with patch.dict(os.environ,{'LD_PRELOAD':'untrusted','ENV':'untrusted','BASH_ENV':'untrusted','SSH_AUTH_SOCK':'secret'}):
            executable,args,env=self.ns['shell_launch'](grant,account)
        self.assertEqual(executable,args[0]);self.assertEqual(args[-2:],['/usr/bin/dash','-i'])
        for flag in ('--clear-groups','--inh-caps=-all','--ambient-caps=-all','--bounding-set=-all','--no-new-privs'):
            self.assertIn(flag,args)
        self.assertFalse(set(env)&{'LD_PRELOAD','ENV','BASH_ENV','SSH_AUTH_SOCK','PYTHONPATH','PYTHONHOME'})
        account.pw_uid=0
        with self.assertRaises(OSError):self.ns['shell_launch'](grant,account)
        account.pw_uid=1001;grant['netns']='foreign'
        with self.assertRaises(OSError):self.ns['shell_launch'](grant,account)
    def test_control_connection_rejects_nonroot_before_sending(self):
        class Connection:
            closed=False;sent=False
            def settimeout(self,value):pass
            def connect(self,path):pass
            def getsockopt(self,*args):return struct.pack('3i',99,1001,1001)
            def close(self):self.closed=True
            def sendall(self,data):self.sent=True
        connection=Connection()
        self.ns['socket']=SimpleNamespace(socket=lambda *_:connection,AF_UNIX=socket.AF_UNIX,SOCK_STREAM=socket.SOCK_STREAM,SOL_SOCKET=socket.SOL_SOCKET)
        self.ns['trusted_path']=lambda *args,**kw:'/run/ctflab-attach'
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):self.ns['control_connection']()
        self.assertTrue(connection.closed);self.assertFalse(connection.sent)
        connection.getsockopt=lambda *args:struct.pack('3i',99,0,0)
        self.assertIs(self.ns['control_connection'](),connection)
    def test_existing_control_regular_file_is_never_unlinked(self):
        self.ns['CONTROL']=str(self.file)
        with self.assertRaises(OSError):self.ns['prepare_control_socket']()
        self.assertEqual(self.file.read_bytes(),b'fixture')
    def test_cleanup_does_not_remove_replacement_socket(self):
        snapshot=SimpleNamespace(st_mode=stat.S_IFSOCK|0o660,st_uid=0,st_dev=1,st_ino=99)
        with patch('os.lstat',return_value=snapshot),patch('os.unlink') as unlink:
            self.ns['unlink_owned_socket']('/unused',(1,98));unlink.assert_not_called()
            self.ns['unlink_owned_socket']('/unused',(1,99));unlink.assert_called_once_with('/unused')


class RawToolBoundaryTests(unittest.TestCase):
    """受控raw工具（设计§4.2）：白名单/参数边界/仅net_raw/进程归属。"""

    def setUp(self):
        self.ns=load_assistant()
        self.sid='11111111-2222-4333-8444-555555555555'
        self.grant={'session':self.sid,'netns':self.ns['netns_name'](self.sid),
                    'address':'10.80.0.10','prefix':24}
        self.account=SimpleNamespace(pw_uid=1001,pw_gid=1001,pw_dir='/home/ctflab-attach',pw_name='ctflab-attach')

    def raw_arguments(self,tool,arguments):
        return self.ns['raw_tool_arguments'](self.grant,tool,arguments)

    def test_unknown_tool_or_shape_rejected(self):
        with self.assertRaises(ValueError):self.raw_arguments('nmap --script',[])
        with self.assertRaises(ValueError):self.raw_arguments('curl',['-s','http://x'])
        with self.assertRaises(ValueError):self.raw_arguments('ping','-c 4')
        with self.assertRaises(ValueError):self.raw_arguments('ping',[str(i) for i in range(17)])
        with self.assertRaises(ValueError):self.raw_arguments('ping',['ok\x00'])
        with self.assertRaises(ValueError):self.raw_arguments('ping',['x'*257])

    def test_flags_must_match_allowlist_and_bounds(self):
        validated=self.raw_arguments('ping',['-n','-c','4','10.80.0.20'])
        self.assertEqual(validated,['-n','-c','4','10.80.0.20'])
        for bad in (['-f'],['-p','80'],['-c','0'],['-c','101'],['-w','301'],['-T','4'],['--max-rate','5']):
            with self.assertRaises(ValueError):self.raw_arguments('ping',bad)
        with self.assertRaises(ValueError):self.raw_arguments('ping',['-c'])
        with self.assertRaises(ValueError):self.raw_arguments('ping',['-c','4','-x'])
        # nmap已移出首版白名单（Kali filecap与NNP冲突，真实内核EPERM）：
        # 白名单外工具在参数层即拒绝，任何旗标组合都不再解析。
        for arguments in (['-sS','-n','-p','80,443','10.80.0.30'], ['-sX'], ['-iL','/etc/passwd']):
            with self.assertRaises(ValueError):self.raw_arguments('nmap',arguments)

    def test_targets_must_be_in_session_subnet_ipv4(self):
        self.assertEqual(self.raw_arguments('ping',['10.80.0.254']),['10.80.0.254'])
        for bad in (['10.81.0.10'],['10.80.0.20.x'],['example.com'],['-10.80.0.1'],
                    ['/etc/passwd'],['10.80.0.1='],['10.80.0.1','10.99.0.1'],[]):
            with self.assertRaises(ValueError):self.raw_arguments('ping',bad)

    def test_launch_is_no_shell_net_raw_only_and_sterile_env(self):
        self.ns['command_path']=lambda name:{'ip':'/usr/sbin/ip','setpriv':'/usr/bin/setpriv','shell':'/usr/bin/dash'}[name]
        self.ns['trusted_path']=lambda path,**kw:path
        self.ns['RAW_TOOLS_RESOLVED']['ping']={'logical':'/usr/bin/ping','path':'/usr/bin/ping',
                                               'sha256':'0'*64}
        self.ns['file_digest']=lambda path:'0'*64
        executable,args,env=self.ns['raw_tool_launch'](self.grant,self.account,'ping',['-c','4','10.80.0.20'])
        self.assertEqual(args[0],'/usr/sbin/ip')
        self.assertEqual(args[1:4],['netns','exec',self.ns['netns_name'](self.sid)])
        self.assertEqual(args[4],'/usr/bin/setpriv')
        for flag in ('--clear-groups','--bounding-set=-all,+net_raw','--inh-caps=+net_raw',
                     '--ambient-caps=+net_raw','--no-new-privs'):
            self.assertIn(flag,args)
        self.assertNotIn('--bounding-set=-all',args)
        self.assertIn('--reuid=1001',args);self.assertIn('--regid=1001',args)
        self.assertEqual(args[-4:],['/usr/bin/ping','-c','4','10.80.0.20'])
        self.assertEqual(env,self.ns['SYSTEM_ENV'])
        self.account.pw_uid=0
        with self.assertRaises(OSError):self.ns['raw_tool_launch'](self.grant,self.account,'ping',['10.80.0.20'])
        self.account.pw_uid=1001;self.grant['netns']='foreign'
        with self.assertRaises(OSError):self.ns['raw_tool_launch'](self.grant,self.account,'ping',['10.80.0.20'])

    def test_resolved_tool_digest_change_refuses_exec(self):
        calls=[]
        def fake_trusted(path,**kw):
            calls.append(path);return path
        self.ns['trusted_path']=fake_trusted
        digests=[]
        self.ns['file_digest']=lambda path:(digests.append(1) or ('a'*64 if len(digests)==1 else 'b'*64))
        # 首次解析记录摘要；文件被替换（摘要变化）后拒绝再次执行。
        self.assertEqual(self.ns['raw_tool_path']('ping'),'/usr/bin/ping')
        self.assertEqual(self.ns['RAW_TOOLS_RESOLVED']['ping']['sha256'],'a'*64)
        with self.assertRaises(OSError):self.ns['raw_tool_path']('ping')

    def test_raw_children_reaped_and_deadline_terminated(self):
        ns=self.ns
        ns['RAW_CHILDREN'].clear()
        ns['RAW_CHILDREN'][101]={'session':self.sid,'deadline':ns['time'].monotonic()+999}
        ns['RAW_CHILDREN'][102]={'session':'99999999-2222-4333-8444-555555555555','deadline':ns['time'].monotonic()-1}
        with patch('os.waitpid',side_effect=[(101,0),(102,0)]) as waitpid:
            ns['reap_raw_children']()
            self.assertEqual(waitpid.call_count,2)
        self.assertEqual(ns['RAW_CHILDREN'],{})
        ns['RAW_CHILDREN'][103]={'session':self.sid,'deadline':ns['time'].monotonic()-1}
        killed=[]
        with patch('os.waitpid',return_value=(0,0)),patch('os.kill',side_effect=lambda pid,sig:killed.append((pid,sig))):
            ns['reap_raw_children']()
        self.assertEqual(killed,[(103,ns['signal'].SIGTERM)])
        self.assertEqual(list(ns['RAW_CHILDREN']),[103])
        ns['RAW_CHILDREN'].clear()

    def test_teardown_terminates_only_own_session_children(self):
        ns=self.ns
        ns['RAW_CHILDREN'].clear()
        ns['RAW_CHILDREN'][201]={'session':self.sid,'deadline':0}
        ns['RAW_CHILDREN'][202]={'session':'99999999-2222-4333-8444-555555555555','deadline':0}
        killed=[]
        with patch('os.kill',side_effect=lambda pid,sig:killed.append(pid)):
            self.assertEqual(ns['terminate_raw_children'](self.sid),1)
        self.assertEqual(killed,[201])
        ns['RAW_CHILDREN'].clear()

    def test_status_reports_raw_tools_per_session(self):
        ns=self.ns
        ns['RAW_CHILDREN'].clear()
        sessions={self.sid:{'grant':{'expires':'2030-01-01T00:00:00Z','netns':'ctflab-111111112222'},
                            'tap_fd':None}}
        ns['RAW_CHILDREN'][301]={'session':self.sid,'deadline':0}
        ns['RAW_CHILDREN'][302]={'session':self.sid,'deadline':0}
        reply=ns['handle_daemon']({'action':'status','session':''},0,1001,sessions,None)
        self.assertEqual(reply['sessions'][0]['raw_tools'],2)
        ns['RAW_CHILDREN'].clear()

    def test_client_parses_raw_and_shell_flags_without_remainder_greed(self):
        """CLI回归：REMAINDER会吞掉--session/--tool；parse_known_args修复后
        raw与shell的会话旗标都必须正确到达客户端函数。"""
        from types import SimpleNamespace
        ns = load_assistant()
        calls = []
        ns['raw_client'] = lambda session, tool, arguments: calls.append(
            ('raw', session, tool, list(arguments)))
        ns['shell_client'] = lambda session: calls.append(('shell', session))
        ns['os'] = SimpleNamespace(geteuid=lambda: 1001)
        sid = self.sid
        cases = [(['ctflab-kali-attach', 'raw', '--session', sid, '--tool', 'ping',
                   '--', '-n', '-c', '3', '10.80.0.20'],
                  ('raw', sid, 'ping', ['-n', '-c', '3', '10.80.0.20'])),
                 (['ctflab-kali-attach', 'shell', '--session', sid],
                  ('shell', sid)),
                 (['ctflab-kali-attach', 'raw', '--session', sid, '--tool', 'nmap',
                   '--', '-sS', '-n', '-p', '6666', '192.168.243.66'],
                  ('raw', sid, 'nmap', ['-sS', '-n', '-p', '6666', '192.168.243.66']))]
        for argv, expected in cases:
            ns['sys'] = SimpleNamespace(argv=argv, stderr=io.StringIO())
            # argparse读取真实sys.argv[1:]；命名空间里的sys只用于fail输出。
            with patch('sys.argv', argv):
                ns['client']()
        self.assertEqual(calls[0], cases[0][1])
        self.assertEqual(calls[1], cases[1][1])
        self.assertEqual(calls[2], cases[2][1])

    def test_raw_command_helper_quotes_and_validates(self):
        # 宿主侧白名单名与脚本内权威RAW_TOOLS一致。
        self.assertEqual(set(host_module.RAW_TOOL_NAMES),set(self.ns['RAW_TOOLS']))
        self.assertEqual(host_module.RAW_TOOL_ARGUMENT_LIMIT,self.ns['RAW_TOOL_ARGUMENT_LIMIT'])
        command=host_raw_command(self.sid,'ping',['-c','4','10.80.0.20'])
        self.assertEqual(command,'ctflab-kali-attach raw --session %s --tool ping -- -c 4 10.80.0.20'%self.sid)
        with self.assertRaises(Exception):host_raw_command(self.sid,'nmap',['-p','80,443'])
        with self.assertRaises(Exception):host_raw_command(self.sid,'curl',[])
        with self.assertRaises(Exception):host_raw_command('短',[])
        with self.assertRaises(Exception):host_raw_command(self.sid,'ping',['a']*17)


if __name__=='__main__':unittest.main()
