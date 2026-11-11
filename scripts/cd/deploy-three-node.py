#!/usr/bin/env python3
"""Coordinate one A/API, B/data and C/runtime release from the sole B runner."""
import fcntl
import gzip
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import uuid

ROLE_FILE = '/etc/agent2-cd/role.production.compose.json'
BACKENDS = {'django', 'celery', 'migrate', 'core-check', 'runtime-worker',
            'workspace-storage-worker', 'workspace-gateway', 'log-ingest'}
SERVICES = {
    'A': ['django', 'celery', 'kong', 'nginx', 'fluent-bit'],
    'B': ['mysql', 'redis', 'mongodb', 'minio', 'clamav', 'log-ingest', 'fluent-bit'],
    'C': ['runtime-worker', 'workspace-storage-worker', 'workspace-gateway', 'runtime-reference', 'fluent-bit'],
}


class Node:
    def __init__(self, name, config):
        self.name, self.config = name, config
        self.ssh = config['ssh']

    def command(self, args):
        return self.ssh + [shlex.join(args)] if self.ssh else args

    def python(self, source, data=None, *, capture=False):
        script = 'import json\nDATA=json.loads(' + repr(json.dumps(data)) + ')\n' + source
        result = subprocess.run(self.command(['python3', '-']), input=script,
                                text=True, check=True, capture_output=capture)
        return result.stdout if capture else None

    def compose(self, manifest, *args):
        subprocess.run(self.command(['docker', 'compose', '-p', 'edu-platform', '-f', manifest, *args]), check=True)


def preflight(nodes):
    manifests, hostnames = {}, set()
    for role, node in nodes.items():
        raw = node.python('''
from pathlib import Path
import socket,subprocess
p=Path(DATA['path'])
if p.stat().st_mode & 0o077:raise SystemExit('Private role manifest must have mode 0600')
c=json.loads(p.read_text())
if not Path('/etc/agent2-cd/secrets/workspace_upstream_token').stat().st_size:
 raise SystemExit('Workspace upstream secret is missing')
for v in c.get('volumes',{}).values():
 if not v.get('external'):raise SystemExit('Volume mapping must be external')
 subprocess.run(['docker','volume','inspect',v['name']],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['docker','compose','-p','edu-platform','-f',str(p),'--profile','maintenance','config','-q'],check=True)
containers=json.loads(subprocess.check_output(['docker','inspect',*[c['services'][s]['container_name'] for s in DATA['services']]]))
for container in containers:
 state=container['State']
 if not state['Running'] or state.get('Health',{}).get('Status','healthy')!='healthy':
  raise SystemExit('Required service is unhealthy: '+container['Name'])
 if container['Config']['Labels'].get('com.docker.compose.service') in ['celery','runtime-worker','workspace-storage-worker']:
  probe="import socket;from education_experiment_platform.celery import app;name='celery@'+socket.gethostname();reply=app.control.inspect(destination=[name],timeout=5).ping();assert reply and reply.get(name,{}).get('ok')=='pong','Worker does not answer broker control'"
  subprocess.run(['docker','exec',container['Id'],'python','-c',probe],check=True,stdout=subprocess.DEVNULL)
print(json.dumps({'hostname':socket.gethostname(),'manifest':c}))
''', {'path': ROLE_FILE, 'services': SERVICES[role]}, capture=True)
        result = json.loads(raw)
        hostname = result['hostname']
        if hostname in hostnames or hostname != node.config['expected_hostname']:
            raise RuntimeError('Unexpected node identity: ' + role)
        hostnames.add(hostname)
        manifests[role] = result['manifest']
        print(f'{role}: {hostname}, role manifest and existing volumes verified', flush=True)
    # A must continue to use B's database; A's historical databases stay stopped.
    nodes['A'].python('''
import subprocess
for name in ['mysql','redis','mongodb','minio']:
 c=json.loads(subprocess.check_output(['docker','inspect','edu-platform-'+name+'-1']))[0]
 if c['State']['Running'] or c['HostConfig']['RestartPolicy']['Name']!='no':
  raise SystemExit('Retired A database is enabled: '+name)
''')
    return manifests


def render_release(manifest, role, revision, release, images):
    """Change executable images/paths, preserving frozen runtime adapter images."""
    result = json.loads(json.dumps(manifest))
    for name, service in result['services'].items():
        if name in BACKENDS:
            service['image'] = images['backend']
        if name == 'nginx':
            service['image'] = images['web']
        if name == 'runtime-reference':
            service['image'] = images['reference']
        env = service.get('environment', {})
        if 'GIT_REVISION' in env:
            env['GIT_REVISION'] = revision
        if 'LOCAL_RUNTIME_IMAGE' in env:
            env['LOCAL_RUNTIME_IMAGE'] = images['workspace']
        # Config refs and their per-host images are frozen independently of CD.
        for volume in service.get('volumes', []):
            if volume['type'] == 'bind' and volume['source'].startswith('/opt/agent2-cd/'):
                source = volume['source']
                if source == '/opt/agent2-cd/current':
                    volume['source'] = release
                elif '/infrastructure/' in source:
                    volume['source'] = release + '/infrastructure/' + source.split('/infrastructure/', 1)[1]
        if role == 'A' and name == 'kong':
            for volume in service.get('volumes', []):
                if volume['target'] == '/kong/declarative/kong.yml':
                    volume['source'] = release + '/infrastructure/kong/kong.yml'
    return result


def stream_images(node, ids):
    save = subprocess.Popen(['docker', 'image', 'save', *ids], stdout=subprocess.PIPE)
    compress = subprocess.Popen(['gzip', '-1'], stdin=save.stdout, stdout=subprocess.PIPE)
    save.stdout.close()
    receive = subprocess.Popen(node.command(['bash', '-o', 'pipefail', '-c', 'gzip -d | docker image load']), stdin=compress.stdout)
    compress.stdout.close()
    statuses = [receive.wait(), compress.wait(), save.wait()]
    if any(statuses):
        raise RuntimeError('Image transfer failed for node ' + node.name)
    node.python('''
import subprocess
for image in DATA:
 found=json.loads(subprocess.check_output(['docker','image','inspect',image]))[0]['Id']
 if found!=image:raise SystemExit('Image identity mismatch')
''', ids)


def worker_control(node, containers, *, restore=None):
    if len(containers) != 1:
        raise ValueError('Drain and record one worker at a time')
    return json.loads(node.python('''
import subprocess
states=[]
for index,container in enumerate(DATA['containers']):
 code="""import json,socket,time
from education_experiment_platform.celery import app
name='celery@'+socket.gethostname()
inspect=app.control.inspect(destination=[name],timeout=5)
if RESTORE is not None:
 for queue in RESTORE:app.control.add_consumer(queue,destination=[name],reply=True)
 print(json.dumps(RESTORE))
else:
 queues=inspect.active_queues()
 if not queues or name not in queues:raise SystemExit('Worker control is unavailable')
 names=[q['name'] for q in queues[name]]
 complete=False
 try:
  for queue in names:app.control.cancel_consumer(queue,destination=[name],reply=True)
  deadline=time.monotonic()+300
  while time.monotonic()<deadline:
   batches=[inspect.active(),inspect.reserved(),inspect.scheduled()]
   if all(batch is not None and name in batch and not batch[name] for batch in batches):
    complete=True;break
   time.sleep(2)
  if not complete:raise SystemExit('Worker is busy; release aborted before stopping services')
 finally:
  if not complete:
   for queue in names:app.control.add_consumer(queue,destination=[name],reply=True)
 print(json.dumps(names))
"""
 restore=DATA['restore'][index] if DATA['restore'] is not None else None
 source='RESTORE='+repr(restore)+'\\n'+code
 p=subprocess.run(['docker','exec','-i',container,'python','-'],input=source,text=True,capture_output=True,check=True)
 states.append(json.loads(p.stdout))
print(json.dumps(states))
''', {'containers': containers, 'restore': restore}, capture=True))


def main():
    revision = os.environ['RELEASE_SHA']
    registry, namespace = os.environ['ACR_REGISTRY'], os.environ['ACR_NAMESPACE']
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise SystemExit('A full release commit is required')
    if not re.fullmatch(r'[a-zA-Z0-9.-]+(?::[0-9]+)?', registry) or not re.fullmatch(r'[a-z0-9_-]+', namespace):
        raise SystemExit('Invalid image repository')
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() != revision:
        raise SystemExit('Checkout and release revision differ')
    inventory = json.loads(Path(os.getenv('AGENT2_TOPOLOGY_FILE', '/etc/agent2-cd/topology.json')).read_text())
    if set(inventory['nodes']) != {'A', 'B', 'C'} or inventory['nodes']['B']['ssh']:
        raise SystemExit('Run the single coordinator on B')
    nodes = {name: Node(name, config) for name, config in inventory['nodes'].items()}
    lock = open('/opt/agent2-cd/deploy.lock', 'a')
    deadline = time.monotonic() + 30
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise SystemExit('Another deployment or recovery holds the release lock')
            time.sleep(1)
    manifests = preflight(nodes)
    if os.getenv('DEPLOY_PREFLIGHT_ONLY', 'false') == 'true':
        print('Three-node preflight passed. No images pulled, migrations run, or services changed.')
        return
    if inventory['phase'] != 'active':
        raise SystemExit('Three-node cutover has not been completed')
    archive = subprocess.check_output(['git', 'archive', 'HEAD'])
    release = f'/opt/agent2-cd/releases/{revision}.three-{uuid.uuid4().hex[:8]}'
    images = {}
    with tempfile.TemporaryDirectory(prefix='agent2-docker-auth-') as auth:
        docker_env = {**os.environ, 'DOCKER_CONFIG': auth}
        subprocess.run(['docker', 'login', registry, '--username', os.environ['ACR_USERNAME'], '--password-stdin'],
                       input=os.environ['ACR_PASSWORD'], text=True, env=docker_env, check=True)
        for kind in ['backend', 'web', 'reference', 'workspace']:
            ref = f'{registry}/{namespace}/agent2-{kind}:{revision}'
            subprocess.run(['docker', 'pull', ref], env=docker_env, check=True)
            images[kind] = json.loads(subprocess.check_output(['docker', 'image', 'inspect', ref]))[0]['Id']
    stream_images(nodes['A'], [images['backend'], images['web']])
    stream_images(nodes['C'], [images[k] for k in ['backend', 'reference', 'workspace']])
    candidates = {}
    for role, node in nodes.items():
        node.python('from pathlib import Path\np=Path(DATA);p.mkdir(parents=True,mode=0o755);p.chmod(0o755)\n', release)
        subprocess.run(node.command(['tar', '-xf', '-', '-C', release]), input=archive, check=True)
        candidate = render_release(manifests[role], role, revision, release, images)
        candidates[role] = release + '/node.compose.json'
        node.python('''
from pathlib import Path
import os,shutil
p=Path(DATA['release']);dest=p/'node.compose.json'
dest.write_text(json.dumps(DATA['manifest'],indent=2)+'\\n');dest.chmod(0o600)
secrets=p/'secrets';secrets.mkdir(exist_ok=True,mode=0o755)
shutil.copy2('/etc/agent2-cd/secrets/workspace_upstream_token',secrets/'workspace_upstream_token')
(secrets/'workspace_upstream_token').chmod(0o444)
if DATA['role']=='A':
 import yaml
 k=p/'infrastructure/kong/kong.yml';c=yaml.safe_load(k.read_text())
 for s in c['services']:
  if s.get('url')=='http://workspace-gateway:8080':s['url']='http://workspace-gateway-c:8080'
 k.write_text(yaml.safe_dump(c,sort_keys=False))
''', {'role': role, 'release': release, 'manifest': candidate})
        node.compose(candidates[role], '--profile', 'maintenance', 'config', '-q')
    backup = Path('/opt/agent2-cd/backups') / f'mysql-{revision}-{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}.sql.gz'
    backup.parent.mkdir(exist_ok=True)
    mysql = manifests['B']['services']['mysql']['container_name']
    with backup.open('wb') as handle:
        dump = subprocess.Popen(['docker', 'exec', mysql, 'sh', '-c',
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --routines --triggers --events --set-gtid-purged=OFF --no-tablespaces --databases "$MYSQL_DATABASE"'], stdout=subprocess.PIPE)
        with gzip.GzipFile(fileobj=handle, mode='wb') as compressed:
            for chunk in iter(lambda: dump.stdout.read(1024*1024), b''):
                compressed.write(chunk)
        if dump.wait():
            raise RuntimeError('Database backup failed before writers were stopped')
    backup.chmod(0o600)
    with gzip.open(backup, 'rb') as handle:
        for _ in iter(lambda: handle.read(1024*1024), b''):
            pass
    # Stop accepting new jobs and drain already reserved tasks before shutdown.
    drained = []
    try:
        for role, services in [('A', ['celery']), ('C', ['runtime-worker','workspace-storage-worker'])]:
            for name in services:
                containers = [manifests[role]['services'][name]['container_name']]
                queues = worker_control(nodes[role], containers)
                drained.append((role, containers, queues))
    except Exception:
        for role, containers, queues in reversed(drained):
            worker_control(nodes[role], containers, restore=queues)
        raise
    # Stop only the workers/API assigned to A/C. Data services remain on B.
    nodes['A'].compose(ROLE_FILE, 'stop', '-t', '300', 'celery', 'django')
    nodes['C'].compose(ROLE_FILE, 'stop', '-t', '300', 'runtime-worker', 'workspace-storage-worker')
    nodes['B'].compose(candidates['B'], '--profile', 'maintenance', 'run', '--rm', '--no-deps', 'mysql-users')
    nodes['A'].compose(candidates['A'], '--profile', 'maintenance', 'run', '--rm', '--no-deps', 'migrate')
    nodes['B'].compose(candidates['B'], '--profile', 'maintenance', 'run', '--rm', '--no-deps', 'mysql-grants')
    for role, services in [('B', ['log-ingest','fluent-bit']), ('A', ['django','fluent-bit']), ('C', SERVICES['C']), ('A', ['celery','kong','nginx'])]:
        nodes[role].compose(candidates[role], 'up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240', *services)
    nodes['A'].python('''
import urllib.request
for host in ['student.edutech-lab.top','teacher.edutech-lab.top','platform.edutech-lab.top']:
 request=urllib.request.Request('http://127.0.0.1:8080/api/v2/health',headers={'Host':host})
 data=json.loads(urllib.request.urlopen(request,timeout=10).read())
 if data['data']['git_revision']!=DATA:raise SystemExit('Entry release differs')
print('All three A portal entries report the release revision.')
''', revision)
    for role, container in [('A','django'),('B','log-ingest'),('C','runtime-worker'),('C','workspace-storage-worker'),('C','workspace-gateway')]:
        nodes[role].python('''
import subprocess
c=json.loads(subprocess.check_output(['docker','inspect',DATA['container']]))[0]
env=dict(v.split('=',1) for v in c['Config']['Env'] if '=' in v)
if env.get('GIT_REVISION')!=DATA['revision']:raise SystemExit('App/worker release mismatch')
''', {'container': manifests[role]['services'][container]['container_name'], 'revision': revision})
    for role, node in nodes.items():
        node.python('''
from pathlib import Path
import os,shutil
root=Path('/opt/agent2-cd');release=Path(DATA)
temp=root/'current.next';temp.unlink(missing_ok=True);temp.symlink_to(release);temp.replace(root/'current')
p=Path('/etc/agent2-cd/role.production.compose.json');tmp=p.with_suffix('.next')
shutil.copyfile(release/'node.compose.json',tmp);tmp.chmod(0o600);tmp.replace(p)
''', release)
    print(f'Deployed {revision} on A/B/C. Database backup: {backup}')


if __name__ == '__main__':
    main()
