#!/usr/bin/env python3
"""Render a private Compose manifest from an existing, validated deployment.

Input is `docker compose config --format json`. Output contains credentials and
must remain on the servers. Data volumes must already have external mappings.
"""
import argparse
import copy
import json
import os
from pathlib import Path

ROLES = {
    'A': ['django', 'celery', 'kong', 'nginx', 'fluent-bit', 'migrate', 'core-check'],
    'B': ['mysql', 'redis', 'mongodb', 'minio', 'clamav', 'log-ingest', 'fluent-bit', 'mysql-users', 'mysql-grants'],
    'C': ['runtime-worker', 'workspace-storage-worker', 'workspace-gateway', 'runtime-reference', 'fluent-bit'],
}
MAINTENANCE = {'migrate', 'core-check', 'mysql-users', 'mysql-grants'}
CONFIG_C = 'runtime/remote-47-96-228-53'
CONFIG_B = 'runtime/remote-121-43-28-192'


def render(config, role, *, staging=False):
    if role not in ROLES:
        raise ValueError('Unknown node role')
    out = {'name': 'edu-platform', 'services': {}, 'networks': {}, 'volumes': {}}
    for name in ROLES[role]:
        service = copy.deepcopy(config['services'][name])
        for key in ('build', 'depends_on', 'profiles', 'develop'):
            service.pop(key, None)
        if 'deploy' in service:
            service['deploy'] = {k: v for k, v in service['deploy'].items() if k == 'resources'}
        service['restart'] = 'no' if name in MAINTENANCE else 'unless-stopped'
        if name in MAINTENANCE:
            service['profiles'] = ['maintenance']
        service['pull_policy'] = 'never'
        env = service.get('environment', {})
        if 'RUNTIME_ADAPTER_CONFIGS' in env:
            adapters = json.loads(env['RUNTIME_ADAPTER_CONFIGS'])
            adapters.setdefault(CONFIG_C, copy.deepcopy(adapters[CONFIG_B]))
            adapters[CONFIG_C]['runtime_network'] = 'agent2_runtime_mesh'
            adapters[CONFIG_C]['base_url'] = 'unix:///var/run/docker.sock' if role == 'C' else 'tcp://172.29.20.1:23752'
            if role == 'C':
                adapters['runtime/local-docker']['base_url'] = 'tcp://172.29.20.1:23751'
                adapters[CONFIG_B]['base_url'] = 'tcp://172.29.20.1:23750'
            if role == 'A':
                adapters['runtime/local-docker']['base_url'] = 'unix:///var/run/docker.sock'
                adapters[CONFIG_B]['base_url'] = 'tcp://172.29.20.1:23750'
            env['RUNTIME_ADAPTER_CONFIGS'] = json.dumps(adapters, separators=(',', ':'))
            env['LOCAL_DOCKER_HOST'] = 'unix:///var/run/docker.sock'
            env['WORKSPACE_AUTHORITY_URL'] = 'http://django:8000'
        if role == 'A':
            if 'TRUSTED_PROXY_CIDRS' in env:
                cidrs = [v.strip() for v in env['TRUSTED_PROXY_CIDRS'].split(',') if v.strip()]
                if '10.253.73.0/24' not in cidrs:
                    cidrs.append('10.253.73.0/24')
                env['TRUSTED_PROXY_CIDRS'] = ','.join(cidrs)
            service['networks'] = {'app': None, 'data-mesh': None}
            if name == 'django':
                service['networks']['data-mesh'] = {'aliases': ['django', 'agent2-api-a']}
            if name == 'celery':
                service['networks']['default'] = None
            if name == 'kong':
                service['networks'] = {'app': None, 'edge': None, 'data-mesh': None}
            if name == 'nginx':
                service['networks'] = {'edge': None}
                # Host Nginx terminates public HTTP/TLS.
                service['ports'] = [{'target': 8080, 'published': '8080', 'host_ip': '127.0.0.1', 'protocol': 'tcp'}]
            if name == 'fluent-bit':
                service['networks'] = {'data-mesh': None, 'log-driver': None}
        if role == 'B' and name in ('mysql', 'redis', 'mongodb', 'minio', 'clamav', 'log-ingest'):
            service['networks']['data-mesh'] = {'aliases': [name]}
        if role == 'B' and name == 'fluent-bit':
            service['networks'] = {'observability': None, 'log-driver': None}
        if role == 'C':
            service['networks'] = {'app': None, 'data-mesh': None, 'runtime-mesh': None}
            if name == 'workspace-gateway':
                service['networks']['data-mesh'] = {'aliases': ['workspace-gateway-c']}
            if name == 'runtime-reference':
                service['networks'] = {'runtime-mesh': {'aliases': ['tasks.fake-runtime']}}
            if name == 'fluent-bit':
                service['networks'] = {'data-mesh': None, 'log-driver': None}
            if staging and name in ('runtime-worker', 'workspace-storage-worker'):
                service['command'] = [v.replace('q_provision,q_archive,q_compensate', 'q_provision_c_check,q_archive_c_check,q_compensate_c_check').replace('q_workspace_storage', 'q_workspace_storage_c_check') for v in service['command']]
        out['services'][name] = service
    for service in out['services'].values():
        for key in service.get('networks', {}):
            if key in ('data-mesh', 'runtime-mesh'):
                name = 'agent2_data_mesh' if key == 'data-mesh' else 'agent2_runtime_mesh'
            else:
                name = config['networks'][key]['name']
            out['networks'][key] = {'name': name, 'external': True}
        for volume in service.get('volumes', []):
            if volume['type'] == 'volume':
                key = volume['source']
                volume_config = config['volumes'][key]
                if not volume_config.get('external'):
                    raise ValueError('Existing volume requires an external mapping: ' + key)
                out['volumes'][key] = {'external': True, 'name': volume_config['name']}
    if not out['volumes']:
        out.pop('volumes')
    return out


def compose_literals(value):
    # Resolved environment values must not be interpolated a second time.
    if isinstance(value, str):
        return value.replace('$', '$$')
    if isinstance(value, list):
        return [compose_literals(v) for v in value]
    if isinstance(value, dict):
        return {k: compose_literals(v) for k, v in value.items()}
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--role', required=True, choices=ROLES)
    parser.add_argument('--staging', action='store_true')
    args = parser.parse_args()
    manifest = render(json.loads(args.input.read_text()), args.role, staging=args.staging)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(compose_literals(manifest), handle, indent=2)
        handle.write('\n')
    args.output.chmod(0o600)


if __name__ == '__main__':
    main()
