#!/usr/bin/env python3
"""Local preparation and explicitly selected p02 operations. No implicit deployment."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENV_FILE = HERE / '.env'
REMOTE = 'p02'
SECRET_KEYS = (
    'DJANGO_SECRET_KEY', 'IDENTITY_HMAC_KEY', 'AUDIT_IP_HASH_SALT',
    'COURSE_INVITATION_HMAC_KEY', 'MYSQL_ROOT_PASSWORD', 'MYSQL_MIGRATION_PASSWORD',
    'MYSQL_APP_PASSWORD', 'MONGO_INITDB_ROOT_PASSWORD', 'MONGO_REPLICA_SET_KEY',
    'MINIO_ROOT_PASSWORD', 'MINIO_APP_SECRET_KEY',
)


def process_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith('COMPOSE_')
            and k not in {'DOCKER_HOST', 'DOCKER_CONTEXT', 'BUILDX_BUILDER'}}


def run(args: list[str], *, capture: bool = False, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=capture,
                          env=kwargs.pop('env', process_env()), **kwargs)


def values() -> dict[str, str]:
    if not ENV_FILE.exists():
        raise ValueError('先执行 p02.py init 生成本机私有配置')
    return dict(line.split('=', 1) for line in ENV_FILE.read_text().splitlines()
                if line and not line.startswith('#') and '=' in line)


def set_values(changes: dict[str, str]) -> None:
    lines = ENV_FILE.read_text().splitlines()
    remaining = dict(changes)
    for i, line in enumerate(lines):
        key = line.split('=', 1)[0]
        if key in remaining:
            lines[i] = key + '=' + remaining.pop(key)
    lines.extend(k + '=' + v for k, v in remaining.items())
    ENV_FILE.write_text('\n'.join(lines) + '\n')
    ENV_FILE.chmod(0o600)


def init() -> None:
    if not ENV_FILE.exists():
        fd = os.open(ENV_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as file:
            file.write((HERE / '.env.example').read_text())
    data = values()
    set_values({key: secrets.token_hex(32) for key in SECRET_KEYS if not data.get(key)})
    print('已生成/保留本机 .env（600）；未输出密钥。')


def docker(context: str, *args: str) -> list[str]:
    return ['docker', '--context', context, *args]


def local_context() -> str:
    context = values()['LOCAL_DOCKER_CONTEXT']
    info = json.loads(run(['docker', 'context', 'inspect', context], capture=True).stdout)[0]
    if not info['Endpoints']['docker']['Host'].startswith(('unix://', 'npipe://')):
        raise ValueError('本机构建 Context 必须连接本地 socket')
    return context


def compose(file: str, context: str, *, runtime: bool = False) -> list[str]:
    args = docker(context, 'compose', '--env-file', str(ENV_FILE), '-f', str(HERE / file))
    if runtime:
        args += ['-f', str(HERE / 'compose.runtime.yml')]
    return args


def rendered(*, runtime: bool = False, file: str = 'compose.server.yml') -> dict:
    output = run(compose(file, values()['LOCAL_DOCKER_CONTEXT'], runtime=runtime)
                 + ['config', '--format', 'json'], capture=True)
    return json.loads(output.stdout)


def validate(config: dict, *, runtime: bool = False) -> None:
    if config['name'] != 'p02' or set(config.get('networks', {})) != {'p02'}:
        raise ValueError('项目和网络必须只属于 p02')
    net = config['networks']['p02']
    if not net.get('internal') or net.get('external') or net['name'] != 'p02_p02':
        raise ValueError('必须使用 p02_p02 internal 网络')
    for name, service in config['services'].items():
        if 'build' in service or 'network_mode' in service or service.get('privileged'):
            raise ValueError(f'{name}: 禁止服务器构建、其他网络模式或特权模式')
        if set(service.get('networks', {})) != {'p02'}:
            raise ValueError(f'{name}: 只能连接 p02')
        if not service.get('container_name', '').startswith('p02-'):
            raise ValueError(f'{name}: 容器名必须以 p02- 开头')
        for port in service.get('ports', []):
            if not 1020 <= int(port['published']) <= 1039:
                raise ValueError(f'{name}: 端口越界')
        for volume in service.get('volumes', []):
            if volume['type'] == 'bind':
                socket = runtime and name == 'runtime-worker' and volume['source'] == '/var/run/docker.sock'
                if not socket and not volume['source'].startswith('/mnt/A/p02/'):
                    raise ValueError(f'{name}: 不允许的远程绑定路径')
    if not runtime and any(v.get('type') == 'bind' for s in config['services'].values()
                           for v in s.get('volumes', [])):
        raise ValueError('基础配置不得有远程 bind mount')
    for volume in config.get('volumes', {}).values():
        if volume.get('external') or not volume['name'].startswith('p02_'):
            raise ValueError('命名卷必须属于 p02')


def check() -> None:
    config = rendered()
    validate(config)
    # Render the gated overlay using a non-secret placeholder for validation only.
    old = values().get('DOCKER_SOCKET_GID', '')
    if not old:
        set_values({'DOCKER_SOCKET_GID': '0'})
    try:
        validate(rendered(runtime=True), runtime=True)
    finally:
        if not old:
            set_values({'DOCKER_SOCKET_GID': ''})
    result = {'services': len(config['services']), 'network': 'p02_p02',
              'ports': sorted(int(p['published']) for s in config['services'].values()
                              for p in s.get('ports', [])), 'remote_changed': False}
    (HERE / 'validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


def install_context(identity: Path) -> None:
    identity = identity.expanduser().resolve(strict=True)
    if identity.stat().st_mode & 0o077:
        raise ValueError('私钥权限必须为 600 或更严格')
    path = Path.home() / '.ssh/config'
    path.parent.mkdir(mode=0o700, exist_ok=True)
    old = path.read_text() if path.exists() else ''
    stanza = ('Host p02-lab\n    HostName 192.168.100.3\n    User hk\n    Port 5422\n'
              f'    IdentityFile "{identity}"\n    IdentitiesOnly yes\n'
              '    BatchMode yes\n    ConnectTimeout 10\n')
    if re.search(r'^Host\s+.*\bp02-lab\b', old, re.MULTILINE):
        effective = run(['ssh', '-G', 'p02-lab'], capture=True).stdout
        expected = ('hostname 192.168.100.3', 'user hk', 'port 5422', f'identityfile {identity}')
        if any(line not in effective.splitlines() for line in expected):
            raise ValueError('已存在不同的 p02-lab 配置；未覆盖')
    else:
        with path.open('a') as file:
            file.write('\n# 02 group Docker Context\n' + stanza)
        path.chmod(0o600)
    found = run(['docker', 'context', 'ls', '--format', '{{.Name}}'], capture=True).stdout.splitlines()
    if REMOTE in found:
        info = json.loads(run(['docker', 'context', 'inspect', REMOTE], capture=True).stdout)[0]
        if info['Endpoints']['docker']['Host'] != 'ssh://p02-lab':
            raise ValueError('已存在其他地址的 p02 Context；未覆盖')
    else:
        run(['docker', 'context', 'create', REMOTE, '--docker', 'host=ssh://p02-lab'])
    print('本机 SSH 条目和 p02 Context 已就绪；未连接服务器，未切换当前 Context。')


def preflight() -> None:
    info = json.loads(run(docker(REMOTE, 'info', '--format', '{{json .}}'), capture=True,
                          timeout=25).stdout)
    platform = {'x86_64': 'linux/amd64', 'aarch64': 'linux/arm64',
                'amd64': 'linux/amd64', 'arm64': 'linux/arm64'}.get(info['Architecture'])
    if not platform:
        raise ValueError('未知服务器架构')
    safe = {key: info.get(key) for key in ('Name', 'ServerVersion', 'Architecture', 'OSType')}
    safe['target_platform'] = platform
    safe['endpoint'] = 'ssh://p02-lab'
    (HERE / 'server-info.json').write_text(json.dumps(safe, indent=2) + '\n')
    set_values({'TARGET_PLATFORM': platform})
    print(json.dumps(safe, ensure_ascii=False))
    run(docker(REMOTE, 'ps', '-a', '--filter', 'label=com.docker.compose.project=p02',
               '--format', '{{.Names}}\t{{.Status}}\t{{.Ports}}'), timeout=25)


def build() -> None:
    if not (HERE / 'server-info.json').exists():
        raise ValueError('先经批准执行只读 preflight，核实目标架构')
    context = local_context()
    env = process_env()
    # A separate local packaging container; the frontend Dockerfile only copies dist.
    revision = run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture=True).stdout.strip()
    run(docker(context, 'run', '--rm', '--mount',
               f'type=bind,src={ROOT / "frontend"},dst=/app', '-w', '/app',
               '-e', 'VITE_GIT_REVISION=' + revision, 'node:24-alpine',
               'sh', '-ec', 'npm ci --ignore-scripts && npm run build'))
    for portal in ('student', 'teacher', 'admin'):
        if not (ROOT / 'frontend/dist' / (portal + '-web') / 'index.html').exists():
            raise ValueError('前端产物不完整')
    run(compose('compose.build.yml', context) + ['build'], env=env)
    print('本机打包与自定义镜像构建完成。执行 lock 前先在本机准备基础镜像。')


def lock() -> None:
    context = local_context()
    config = rendered()
    images = sorted({s['image'] for s in config['services'].values()}
                    | {'p02-stdio:' + values()['RELEASE_TAG']})
    records = []
    for image in images:
        obj = json.loads(run(docker(context, 'image', 'inspect', image), capture=True).stdout)[0]
        platform = obj['Os'] + '/' + obj['Architecture']
        if platform != values()['TARGET_PLATFORM']:
            raise ValueError(f'{image}: 镜像架构不匹配')
        records.append({'reference': image, 'id': obj['Id'], 'platform': platform})
    data = {'git_revision': run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture=True).stdout.strip(),
            'target_platform': values()['TARGET_PLATFORM'], 'images': records}
    (HERE / 'release-lock.json').write_text(json.dumps(data, indent=2) + '\n')
    print(f'已锁定 {len(records)} 个镜像完整 ID；未上传。')


def transfer() -> None:
    context = local_context()
    data = json.loads((HERE / 'release-lock.json').read_text())
    for image in data['images']:
        actual = run(docker(context, 'image', 'inspect', image['reference'], '--format', '{{.Id}}'), capture=True).stdout.strip()
        if actual != image['id']:
            raise ValueError('镜像已变化，请重新生成发布清单')
    # File transport preserves binary bytes on Windows as well as macOS.
    with tempfile.TemporaryDirectory(prefix='p02-images-') as tmp:
        archive = Path(tmp) / 'images.tar'
        run(docker(context, 'save', '-o', str(archive), *[i['reference'] for i in data['images']]))
        run(docker(REMOTE, 'load', '-i', str(archive)))
    for image in data['images']:
        actual = run(docker(REMOTE, 'image', 'inspect', image['reference'], '--format', '{{.Id}}'), capture=True).stdout.strip()
        if actual != image['id']:
            raise ValueError('远程镜像 ID 不匹配')
    print('上传镜像已逐一核对完整 ID；未启动业务服务。')


def probe() -> None:
    # Only explicit probe writes to the remote engine. Leave the group network in place.
    if run(docker(REMOTE, 'ps', '-q', '--filter', 'publish=1025'), capture=True).stdout.strip():
        raise ValueError('1025 已有运行容器；未启动探针')
    args = compose('compose.probe.yml', REMOTE)
    run(args + ['up', '-d', '--pull', 'never'])
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://192.168.100.3:1025', timeout=10) as response:
            if response.status != 200:
                raise ValueError('入口未返回 200')
        network = json.loads(run(docker(REMOTE, 'network', 'inspect', 'p02_p02'), capture=True).stdout)[0]
        if not network['Internal']:
            raise ValueError('探测网络未隔离')
        subnets = [item['Subnet'] for item in network['IPAM']['Config']]
        for subnet in subnets:
            ipaddress.ip_network(subnet)
        set_values({'P02_PROXY_CIDRS': ','.join(subnets)})
        (HERE / 'probe-result.json').write_text(json.dumps({'passed': True, 'subnets': subnets}) + '\n')
        print('internal 网络入口验证通过；已记录本组网络实际子网。')
    finally:
        run(args + ['rm', '--stop', '--force', 'probe'])


def deploy() -> None:
    data = values()
    runtime = data.get('P02_RUNTIME_APPROVED') == 'true'
    config = rendered(runtime=runtime)
    validate(config, runtime=runtime)
    for required in ('server-info.json', 'release-lock.json', 'probe-result.json'):
        if not (HERE / required).exists():
            raise ValueError('缺少 ' + required + '；先完成经批准的预检、入口验证和镜像锁定')
    budget_cpu = int(data.get('P02_GROUP_CPU_MILLICORES') or 0)
    budget_memory = int(data.get('P02_GROUP_MEMORY_MB') or 0)
    required_cpu = sum(int(float(s.get('cpus', 0)) * 1000) for s in config['services'].values())
    required_memory = sum(int(s.get('mem_limit', 0)) // 1024**2 for s in config['services'].values())
    if runtime:
        runtime_cpu = int(data.get('P02_RUNTIME_CPU_MILLICORES') or 0)
        runtime_memory = int(data.get('P02_RUNTIME_MEMORY_MB') or 0)
        if min(runtime_cpu, runtime_memory) <= 0 or not data.get('DOCKER_SOCKET_GID'):
            raise ValueError('运行服务尚未配置明确的 Docker 权限和动态运行资源限额')
        required_cpu += runtime_cpu
        required_memory += runtime_memory
    if budget_cpu < required_cpu or budget_memory < required_memory:
        raise ValueError(f'组配额未填写或不足；当前各容器上限合计至少需要 {required_cpu} millicores / {required_memory} MiB，需按获批配额调整后再验收')
    if data.get('P02_CLAMAV_DATABASE_READY') != 'true':
        raise ValueError('先经批准导入并验证 ClamAV 病毒库')
    lock_data = json.loads((HERE / 'release-lock.json').read_text())
    revision = run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture=True).stdout.strip()
    if lock_data['git_revision'] != revision:
        raise ValueError('发布清单不属于当前代码版本')
    if run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, capture=True).stdout.strip():
        raise ValueError('代码存在未提交改动，请重新检查、提交并构建')
    for image in lock_data['images']:
        actual = run(docker(REMOTE, 'image', 'inspect', image['reference'], '--format', '{{.Id}}'), capture=True).stdout.strip()
        if actual != image['id']:
            raise ValueError('远程镜像和发布清单不一致')
    cmd = compose('compose.server.yml', REMOTE, runtime=runtime)
    # This command is deliberately explicit; it is never called by init/check/build.
    run(cmd + ['up', '-d', '--no-build', '--pull', 'never'])
    run(cmd + ['ps', '--all'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'check', 'install-context', 'preflight', 'build', 'lock', 'transfer', 'probe', 'deploy'])
    parser.add_argument('--identity', type=Path)
    args = parser.parse_args()
    if args.command == 'install-context':
        if args.identity is None:
            parser.error('install-context requires --identity')
        install_context(args.identity)
    else:
        globals()[args.command]()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        # Avoid echoing Compose output/environment containing private values.
        print('操作未完成：' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), file=sys.stderr)
        sys.exit(1)
