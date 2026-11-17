"""Regression checks for resource isolation on the shared company engine."""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from apps.provisioning.adapters import DockerLocalAdapter, RuntimeAdapterFailure
from apps.provisioning.stdio import StdioExecutor

DEPLOY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('p02_deployment', DEPLOY / 'p02.py')
assert spec and spec.loader
p02 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p02)


def valid_config():
    return {'name': 'p02', 'networks': {'p02': {'name': 'p02_p02', 'internal': True}},
            'services': {'nginx': {'container_name': 'p02-nginx', 'networks': {'p02': {}},
                                   'ports': [{'published': '1025'}]}}, 'volumes': {}}


@pytest.mark.parametrize('mutation', [
    lambda c: c['services']['nginx'].update(build='.'),
    lambda c: c['services']['nginx'].update(networks={'bridge': {}}),
    lambda c: c['services']['nginx'].update(ports=[{'published': '8080'}]),
    lambda c: c['services']['nginx'].update(volumes=[{'type': 'bind', 'source': '/etc'}]),
    lambda c: c['networks']['p02'].update(internal=False),
    lambda c: c.update(volumes={'shared': {'name': 'p03_data'}}),
])
def test_rejects_cross_group_and_remote_build_configuration(mutation):
    config = valid_config()
    p02.validate(config)
    mutation(config)
    with pytest.raises(ValueError):
        p02.validate(config)


def test_stdio_names_and_labels_belong_to_group(settings):
    settings.RUNTIME_RESOURCE_PREFIX = 'p02'
    client = Mock()
    executor = StdioExecutor(client, 'p02-stdio:v1', owner='assessment-1')
    executor._container(memory_mb=256, volumes={})
    args = client.containers.create.call_args.kwargs
    assert args['name'].startswith('p02-stdio-')
    assert args['labels']['edu.platform.project'] == 'p02'
    assert args['network_mode'] == 'none'
    assert args['cap_drop'] == ['ALL']
    executor._volume({'main.py': b'print(1)'})
    assert client.volumes.create.call_args.kwargs['name'].startswith('p02-stdio-data-')


def test_image_administration_cannot_build_or_pull(settings):
    settings.RUNTIME_IMAGE_OPERATIONS_ENABLED = False
    client = Mock()
    adapter = DockerLocalAdapter(client=client)
    with pytest.raises(RuntimeAdapterFailure, match='RUNTIME_IMAGE_OPERATIONS_DISABLED'):
        adapter.build_image(registry='r', repository='x', tag='v1', context={}, build_args={})
    with pytest.raises(RuntimeAdapterFailure, match='RUNTIME_IMAGE_OPERATIONS_DISABLED'):
        adapter.resolve_image(registry='r', repository='x', tag='v1')
    client.build.assert_not_called()
    client.pull.assert_not_called()


def test_shared_engine_capacity_is_capped(settings):
    settings.RUNTIME_CAPACITY_CPU_MILLICORES = 1000
    settings.RUNTIME_CAPACITY_MEMORY_MB = 1024
    client = Mock()
    client.info.return_value = {'NCPU': 64, 'MemTotal': 128 * 1024**3}
    result = DockerLocalAdapter(client=client).health()
    assert result['capacity_cpu_millicores'] == 1000
    assert result['capacity_memory_mb'] == 1024


def test_expiry_cleanup_preserves_other_groups_even_if_engine_ignores_filter(settings):
    from apps.experiments.assessment_workers import cleanup_assessment_resources

    settings.RUNTIME_RESOURCE_PREFIX = 'p02'
    settings.RUNTIME_ADAPTER_CONFIGS = {}
    current = Mock(labels={'edu.platform.project': 'p02', 'edu.platform.expires_at': '0'})
    other = Mock(labels={'edu.platform.project': 'p03', 'edu.platform.expires_at': '0'})
    legacy = Mock(labels={'edu.platform.expires_at': '0'})
    current_volume = Mock(attrs={'Labels': current.labels})
    other_volume = Mock(attrs={'Labels': other.labels})
    client = Mock()
    client.containers.list.return_value = [current, other, legacy]
    client.volumes.list.return_value = [current_volume, other_volume]
    query = MagicMock()
    query.first.return_value = None
    query.__iter__.return_value = iter([])
    with (
        patch('apps.experiments.assessment_workers.docker.DockerClient', return_value=client),
        patch('apps.experiments.assessment_workers.QuotaReservation.objects.filter', return_value=query),
    ):
        assert cleanup_assessment_resources() == 2
    assert 'edu.platform.project=p02' in client.containers.list.call_args.kwargs['filters']['label']
    current.remove.assert_called_once_with(force=True)
    current_volume.remove.assert_called_once_with(force=True)
    other.remove.assert_not_called()
    legacy.remove.assert_not_called()
    other_volume.remove.assert_not_called()


@pytest.mark.parametrize('approved,queue', [('false', 'q_content'), ('true', 'q_provision')])
def test_scanning_does_not_require_docker_and_precheck_follows_runtime_approval(monkeypatch, approved, queue):
    for key in p02.SECRET_KEYS:
        monkeypatch.setenv(key, 'test-value')
    monkeypatch.setenv('DJANGO_ALLOWED_HOSTS', 'django')
    monkeypatch.setenv('DJANGO_TRUSTED_ORIGINS', 'http://student.p02.test:1025')
    monkeypatch.setenv('TRUSTED_PROXY_CIDRS', '127.0.0.1/32')
    monkeypatch.setenv('P02_RUNTIME_APPROVED', approved)
    spec = importlib.util.spec_from_file_location(
        'education_experiment_platform.settings.p02_lab', DEPLOY / 'settings_lab.py',
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.CELERY_TASK_ANNOTATIONS['apps.reports.tasks.scan_report_asset']['queue'] == 'q_scan'
    assert module.CELERY_TASK_ANNOTATIONS['apps.labtemplates.tasks.run_template_precheck']['queue'] == queue
    assert module.SESSION_COOKIE_SECURE is False
    assert module.DEBUG is False
