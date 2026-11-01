"""专用来宾安装材料生成；宿主上只生成新目录，不安装或修改网络。"""
import argparse
import hashlib
import json
from pathlib import Path
import os
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_guest_policy import service_units,agent_unit,agent_path_unit

MODULES=('ctflab_guest_agent.py','ctflab_guest_policy.py','ctflab_contract.py',
         'ctflab_storage_bind.py',
         'ctflab_generation_store.py','ctflab_local_service.py','ctflab_scenario_v2.py',
         'ctflab_tls_endpoint.py','ctflab_windows_native.py','ctflab_windows_security.py','ctflab_oci.py','ctflab_guest_routes.py','ctflab_guest_routed.py','ctflab_guest_analysis.py','ctflab_linux_native.py','ctflab_runtime_inventory.py','ctflab_storage_boundary.py')

INSTALLER=r'''"""仅在新的专用Linux QEMU来宾中显式安装，不操作宿主或已有实验。"""
import argparse,hashlib,json,os,platform,stat,subprocess,sys,uuid
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--expected-vm',required=True)
parser.add_argument('--enable-routed-containers',action='store_true')
args=parser.parse_args()
def check(value):
    if not value:raise ValueError('guest-install-precondition-failed')
try:
    check(platform.system()=='Linux' and os.geteuid()==0)
    expected=str(uuid.UUID(args.expected_vm));check(expected==args.expected_vm)
    check(Path('/sys/class/dmi/id/product_uuid').read_text().strip().lower()==expected)
    check(Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU','Bochs'))
    source=Path(__file__).resolve().parent
    manifest=json.loads((source/'MANIFEST.json').read_text())
    check(manifest['kind']=='dedicated-guest-bootstrap' and manifest['schema']==1)
    for name,sha in manifest['files'].items():
        check(not name.startswith('/') and '..' not in Path(name).parts)
        check(hashlib.sha256((source/name).read_bytes()).hexdigest()==sha)
    TOOLS={'nft':'/usr/sbin/nft','ip':'/usr/sbin/ip','sysctl':'/usr/sbin/sysctl','docker':'/usr/bin/docker',
           'dnsmasq':'/usr/sbin/dnsmasq','chronyd':'/usr/sbin/chronyd','systemctl':'/usr/bin/systemctl'}
    if args.enable_routed_containers:TOOLS.update({'nsenter':'/usr/bin/nsenter','iptables-save':'/usr/sbin/iptables-save','ip6tables-save':'/usr/sbin/ip6tables-save'})
    runtime={}
    for tool,filename in TOOLS.items():
        p=Path(filename);info=p.stat()
        check(info.st_uid==0 and not info.st_mode&0o022 and p.is_file())
        runtime[tool]=hashlib.sha256(p.read_bytes()).hexdigest()
    if args.enable_routed_containers:
        check(not Path('/etc/docker/daemon.json').exists() and not Path('/etc/docker/daemon.json').is_symlink())
        containers=Path('/var/lib/docker/containers')
        check(not containers.is_symlink() and (not containers.exists() or containers.is_dir() and not list(containers.iterdir())))
    check(not Path('/etc/ctflab-managed-guest.json').exists())
    check(not Path('/usr/local/lib/ctflab').exists() and not Path('/var/lib/ctflab-guest').exists())
    payload={name:(source/name).read_bytes() for name in manifest['files'] if name.startswith(('usr/','etc/'))}
    if not args.enable_routed_containers:payload.pop('etc/docker/daemon.json')
    modules=('ctflab_guest_agent.py','ctflab_guest_policy.py','ctflab_contract.py','ctflab_generation_store.py','ctflab_storage_bind.py',
             'ctflab_local_service.py','ctflab_scenario_v2.py','ctflab_tls_endpoint.py','ctflab_windows_native.py','ctflab_windows_security.py','ctflab_oci.py','ctflab_guest_routes.py','ctflab_guest_routed.py','ctflab_guest_analysis.py','ctflab_linux_native.py','ctflab_runtime_inventory.py','ctflab_storage_boundary.py')
    allowed={'usr/local/lib/ctflab/'+name for name in modules}|{'etc/systemd/system/ctflab-'+name+'.service' for name in ('agent','dns','time')}|{'etc/systemd/system/ctflab-agent.path'}
    if args.enable_routed_containers:allowed.add('etc/docker/daemon.json')
    check(set(payload)==allowed)
    check(all(hashlib.sha256(data).hexdigest()==manifest['files'][name] for name,data in payload.items()))
    for name in payload:
        target=Path('/')/name
        check(not target.exists() and not target.is_symlink())
        for parent in target.parents:
            if parent.exists():
                info=parent.lstat();check(not stat.S_ISLNK(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022)
    # 所有预检完成后才写；失败保留已写部分，绝不覆盖或自动清理。
    for name,data in payload.items():
        target=Path('/')/name;target.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o644)
        with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
    Path('/var/lib/ctflab-guest').mkdir(mode=0o700)
    Path('/var/lib/ctflab-guest/oci').mkdir(mode=0o700)
    marker={'schema':1,'role':'managed-router','runtime_sha256':runtime}
    if args.enable_routed_containers:
        marker['routing_mode']='point-to-point-v1'
        marker['docker_config_sha256']=hashlib.sha256(payload['etc/docker/daemon.json']).hexdigest()
    fd=os.open('/etc/ctflab-managed-guest.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as out:json.dump(marker,out,sort_keys=True);out.flush();os.fsync(out.fileno())
    subprocess.run(['/usr/bin/systemctl','daemon-reload'],check=True,timeout=15)
    subprocess.run(['/usr/bin/systemctl','enable','ctflab-agent.path'],check=True,timeout=15)
    print(json.dumps({'state':'installed-for-next-boot','services_started':False,'network_modified':False,'runtime_verified':False}))
except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
    print(json.dumps({'state':'refused-or-partial','preserved':True,'automatic_cleanup':False}));raise SystemExit(2)
'''


def build(source,destination):
    source=Path(source);destination=Path(destination)
    data={'usr/local/lib/ctflab/'+name:(source/'tools'/name).read_bytes() for name in MODULES}
    data.update({'etc/systemd/system/'+name:text.encode() for name,text in service_units().items()})
    data['etc/systemd/system/ctflab-agent.service']=agent_unit().encode()
    data['etc/systemd/system/ctflab-agent.path']=agent_path_unit().encode()
    data['etc/docker/daemon.json']=(json.dumps({'iptables':False,'ip6tables':False,'ip-forward':False,'bridge':'none','userland-proxy':False},sort_keys=True)+'\n').encode()
    data['install.py']=INSTALLER.encode()
    manifest={'schema':1,'kind':'dedicated-guest-bootstrap','guest_validated':False,
              'files':{n:hashlib.sha256(raw).hexdigest() for n,raw in sorted(data.items())}}
    destination.mkdir(mode=0o700)
    for name,raw in data.items():
        path=destination/name;path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw)
    (destination/'MANIFEST.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('destination',type=Path)
    args=parser.parse_args();result=build(Path(__file__).resolve().parents[1],args.destination)
    print(json.dumps({'state':'source-created','files':len(result['files']),'guest_validated':False}))
