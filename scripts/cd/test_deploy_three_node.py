import ast
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('deploy', Path(__file__).with_name('deploy-three-node.py'))
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class DeploymentTests(unittest.TestCase):
    def test_resolved_release_mounts_follow_new_source_and_secret(self):
        old = '/opt/agent2-cd/releases/old'
        volumes = [{'type':'bind','source':old,'target':'/workspace'},
                   {'type':'bind','source':old+'/secrets/workspace_upstream_token','target':'/run/secrets/token'}]
        result = deploy.render_release({'services':{'django':{'volumes':volumes}}}, 'A', 'new', '/opt/agent2-cd/releases/new', {'backend':'new-image'})
        self.assertEqual([v['source'] for v in result['services']['django']['volumes']],
                         ['/opt/agent2-cd/releases/new','/opt/agent2-cd/releases/new/secrets/workspace_upstream_token'])

    def test_release_changes_executable_images_but_preserves_frozen_adapters(self):
        adapters = {'runtime/local-docker': {'image': 'sha256:historical-A'},
                    'runtime/remote-121-43-28-192': {'image': 'sha256:historical-B'},
                    'runtime/remote-47-96-228-53': {'image': 'sha256:historical-C'}}
        manifest = {'services': {'django': {'image': 'old-backend',
            'environment': {'GIT_REVISION': 'old', 'RUNTIME_ADAPTER_CONFIGS': json.dumps(adapters)},
            'volumes': [{'type': 'bind', 'source': '/opt/agent2-cd/current', 'target': '/workspace'}]},
            'mysql': {'image': 'reviewed-data-image'}}}
        result = deploy.render_release(manifest, 'A', 'new-revision', '/opt/agent2-cd/releases/new', {'backend': 'new-backend'})
        service = result['services']['django']
        self.assertEqual(service['image'], 'new-backend')
        self.assertEqual(service['environment']['GIT_REVISION'], 'new-revision')
        self.assertEqual(json.loads(service['environment']['RUNTIME_ADAPTER_CONFIGS']), adapters)
        self.assertEqual(service['volumes'][0]['source'], '/opt/agent2-cd/releases/new')
        self.assertEqual(result['services']['mysql']['image'], 'reviewed-data-image')
        self.assertEqual(manifest['services']['django']['image'], 'old-backend')

    def test_remote_python_programs_are_valid_before_deployment(self):
        tree = ast.parse(Path(deploy.__file__).read_text())
        checked = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'python' and node.args and isinstance(node.args[0], ast.Constant):
                compile('import json\nDATA=None\n' + node.args[0].value, '<remote operation>', 'exec')
                checked += 1
        self.assertGreaterEqual(checked, 7)

    def test_ssh_arguments_are_shell_quoted_at_remote_boundary(self):
        node = deploy.Node('A', {'ssh': ['ssh', 'root@server']})
        self.assertEqual(node.command(['tar', '-C', '/path with spaces']), ['ssh', 'root@server', "tar -C '/path with spaces'"])


if __name__ == '__main__':
    unittest.main()
