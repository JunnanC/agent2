import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('roles', Path(__file__).with_name('render-node-role.py'))
roles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roles)


def fixture():
    config = {'services': {}, 'networks': {}, 'volumes': {'mysql-data': {'external': True, 'name': 'existing-mysql'}}}
    for network in ('app', 'data', 'edge', 'default', 'observability', 'log-driver'):
        config['networks'][network] = {'name': 'existing-' + network}
    for name in set(sum(roles.ROLES.values(), [])):
        config['services'][name] = {
            'image': 'backend:revision', 'networks': {'data': None},
            'depends_on': {'mysql': {'condition': 'service_healthy'}},
            'environment': {'LOCAL_DOCKER_HOST': 'unix:///var/run/docker.sock',
                'RUNTIME_ADAPTER_CONFIGS': json.dumps({
                    'runtime/local-docker': {'base_url': 'tcp://172.29.20.1:23751'},
                    roles.CONFIG_B: {'base_url': 'unix:///var/run/docker.sock', 'image': 'sha256:reviewed'},
                })},
            'command': ['celery', '--queues=q_provision,q_archive,q_compensate' if name == 'runtime-worker' else '--queues=q_workspace_storage'],
        }
    config['services']['mysql']['volumes'] = [{'type': 'volume', 'source': 'mysql-data', 'target': '/var/lib/mysql'}]
    return config


class RoleTests(unittest.TestCase):
    def test_api_trusts_both_ingress_paths_without_trusting_public_ranges(self):
        config = fixture()
        config['services']['django']['environment']['TRUSTED_PROXY_CIDRS'] = '172.29.20.0/24'
        manifest = roles.render(config, 'A')
        self.assertEqual(manifest['services']['django']['environment']['TRUSTED_PROXY_CIDRS'], '172.29.20.0/24,10.253.73.0/24')
        self.assertEqual(config['services']['django']['environment']['TRUSTED_PROXY_CIDRS'], '172.29.20.0/24')
        config['services']['django']['environment']['TRUSTED_PROXY_CIDRS'] += ',10.253.73.0/24'
        again = roles.render(config, 'A')['services']['django']['environment']['TRUSTED_PROXY_CIDRS']
        self.assertEqual(again.count('10.253.73.0/24'), 1)

    def test_historical_config_refs_keep_their_host_on_every_node(self):
        expected = {
            'A': ['unix:///var/run/docker.sock', 'tcp://172.29.20.1:23750', 'tcp://172.29.20.1:23752'],
            'B': ['tcp://172.29.20.1:23751', 'unix:///var/run/docker.sock', 'tcp://172.29.20.1:23752'],
            'C': ['tcp://172.29.20.1:23751', 'tcp://172.29.20.1:23750', 'unix:///var/run/docker.sock'],
        }
        for node in ('A', 'B', 'C'):
            service = roles.render(fixture(), node)['services'][roles.ROLES[node][0]]
            adapters = json.loads(service['environment']['RUNTIME_ADAPTER_CONFIGS'])
            self.assertEqual([adapters[k]['base_url'] for k in ('runtime/local-docker', roles.CONFIG_B, roles.CONFIG_C)], expected[node])

    def test_roles_cannot_expand_into_other_nodes_services(self):
        for node in roles.ROLES:
            manifest = roles.render(fixture(), node)
            self.assertEqual(set(manifest['services']), set(roles.ROLES[node]))
            self.assertTrue(all('depends_on' not in s and 'build' not in s for s in manifest['services'].values()))
            for name, service in manifest['services'].items():
                self.assertEqual(service.get('profiles', []), ['maintenance'] if name in roles.MAINTENANCE else [])

    def test_missing_existing_data_volume_mapping_is_rejected(self):
        config = fixture()
        config['volumes']['mysql-data']['external'] = False
        with self.assertRaisesRegex(ValueError, 'external mapping'):
            roles.render(config, 'B')

    def test_staged_workers_consume_only_isolated_queues(self):
        manifest = roles.render(fixture(), 'C', staging=True)
        self.assertEqual(manifest['services']['runtime-worker']['command'][-1], '--queues=q_provision_c_check,q_archive_c_check,q_compensate_c_check')
        self.assertEqual(manifest['services']['workspace-storage-worker']['command'][-1], '--queues=q_workspace_storage_c_check')
        production = roles.render(fixture(), 'C')
        self.assertEqual(production['services']['runtime-worker']['command'][-1], '--queues=q_provision,q_archive,q_compensate')

    def test_existing_literal_secrets_survive_second_compose_interpolation(self):
        self.assertEqual(roles.compose_literals({'password': 'keep$this${literal}'}), {'password': 'keep$$this$${literal}'})


if __name__ == '__main__':
    unittest.main()
