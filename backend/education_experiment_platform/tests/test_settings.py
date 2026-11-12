import os
import subprocess
import sys
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

ROOT = (
    Path(os.environ["PROJECT_ROOT"])
    if os.environ.get("PROJECT_ROOT")
    else Path(__file__).resolve().parents[3]
)

EXPECTED_DOMAIN_APPS = {
    "core",
    "accounts",
    "courses",
    "governance",
    "labtemplates",
    "experiments",
    "provisioning",
    "workspaces",
    "reports",
    "reviews",
    "archives",
    "agents",
    "notifications",
    "analytics",
    "integrations",
}


class SettingsTests(SimpleTestCase):
    def test_functional_setting_names_preserve_legacy_env_fallbacks(self) -> None:
        aliases = {
            "AUTO_CHECK_MAX_ATTEMPTS": "P10_AUTO_CHECK_MAX_ATTEMPTS",
            "PUBLICATION_SYNC_LIMIT": "P06_PUBLICATION_SYNC_LIMIT",
            "PUBLICATION_CHUNK_SIZE": "P06_PUBLICATION_CHUNK_SIZE",
        }
        environment = os.environ.copy()
        environment["DJANGO_SETTINGS_MODULE"] = "education_experiment_platform.settings.test"
        for current, legacy in aliases.items():
            environment.pop(current, None)
            environment[legacy] = "7"
        probe = (
            "import education_experiment_platform.settings.base as config; "
            f"print([getattr(config, key) for key in {list(aliases)!r}])"
        )
        for use_current_name, expected in ((False, "[7, 7, 7]"), (True, "[11, 11, 11]")):
            if use_current_name:
                environment.update(dict.fromkeys(aliases, "11"))
            result = subprocess.run(
                [sys.executable, "-c", probe],
                cwd=ROOT / "backend",
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            assert result.stdout.strip() == expected

    def test_unit_test_settings_require_explicit_real_execution(self) -> None:
        assert settings.LOCAL_RUNTIME_MODE == "STUB"

    def test_production_rejects_fake_runtime_without_adapter_configuration(self) -> None:
        environment = os.environ.copy()
        environment.update({
            "DJANGO_SETTINGS_MODULE": "education_experiment_platform.settings.prod",
            "DJANGO_SECRET_KEY": "test-secret",
            "IDENTITY_HMAC_KEY": "test-identity",
            "WORKSPACE_UPSTREAM_HMAC_KEY": "test-upstream",
            "DJANGO_ALLOWED_HOSTS": "localhost",
            "DJANGO_TRUSTED_ORIGINS": "http://localhost",
            "TRUSTED_PROXY_CIDRS": "127.0.0.1/32",
            "RUNTIME_MODE": "fake",
            "RUNTIME_ADAPTER_CODE": "runtime/fake",
            "RUNTIME_ADAPTER_CONFIGS": "{}",
        })
        result = subprocess.run(
            [sys.executable, "-c", "import education_experiment_platform.settings.prod"],
            cwd=ROOT / "backend",
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "Production requires RUNTIME_MODE=local|swarm" in result.stderr
        environment.update({
            "RUNTIME_MODE": "local",
            "RUNTIME_ADAPTER_CODE": "assessment/local",
            "RUNTIME_ADAPTER_CONFIGS": '{"assessment/local":{"docker_host":"unix:///var/run/docker.sock"}}',
            "LOCAL_RUNTIME_MODE": "REAL",
        })
        for mode, expected in (("REAL", 0), ("STUB", 1)):
            environment["LOCAL_RUNTIME_MODE"] = mode
            result = subprocess.run(
                [sys.executable, "-c", "import education_experiment_platform.settings.prod"],
                cwd=ROOT / "backend",
                env=environment,
                capture_output=True,
                text=True,
            )
            assert (result.returncode != 0) == bool(expected), result.stderr

    def test_all_target_apps_exist_without_teams(self) -> None:
        installed = {config.label for config in apps.get_app_configs()}
        assert installed >= EXPECTED_DOMAIN_APPS
        assert "teams" not in installed

    def test_contract_revision_and_api_prefix_are_fixed(self) -> None:
        assert settings.OPENAPI_REVISION == "v2-p15"

    def test_celery_preserves_structured_application_logging(self) -> None:
        assert settings.CELERY_WORKER_HIJACK_ROOT_LOGGER is False

    def test_retired_lifecycle_models_are_removed(self) -> None:
        self.assertEqual(
            {m.__name__ for m in apps.get_app_config("provisioning").get_models()},
            {"RuntimeCapacityReservation"},
        )
        self.assertEqual(
            {m.__name__ for m in apps.get_app_config("workspaces").get_models()},
            {"WorkspaceSnapshot"},
        )
        self.assertEqual(
            {m.__name__ for m in apps.get_app_config("reviews").get_models()},
            {"Rubric", "RubricVersion", "RubricCriterion"},
        )
        self.assertEqual(
            {m.__name__ for m in apps.get_app_config("reports").get_models()},
            {"ReportDraft", "ReportVersion", "ReportAttachment", "ReportVersionAttachment"},
        )
