import json
import os
from pathlib import Path

import yaml

ROOT = (
    Path(os.environ["PROJECT_ROOT"])
    if os.environ.get("PROJECT_ROOT")
    else Path(__file__).resolve().parents[3]
)


def load_yaml(relative_path: str) -> dict:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


def server_block(text: str, server_name: str) -> str:
    marker = f"server_name {server_name};"
    marker_index = text.index(marker)
    start = text.rfind("\n  server {", 0, marker_index)
    end = text.find("\n  server {", marker_index)
    return text[start : end if end >= 0 else len(text)]


def test_kong_overwrites_browser_and_machine_contexts() -> None:
    config = load_yaml("infrastructure/kong/kong.yml")
    service = config["services"][0]
    assert service["retries"] == 0
    routes = {route["name"]: route for route in service["routes"]}

    expected_portals = {
        "student-browser-api": "USER",
        "teacher-browser-api": "TEACHING",
        "admin-browser-api": "PLATFORM",
    }
    for route_name, portal in expected_portals.items():
        transformer = routes[route_name]["plugins"][0]["config"]
        assert "X-Portal" in transformer["remove"]["headers"]
        assert f"X-Portal:{portal}" in transformer["add"]["headers"]
        assert "X-Proxy-Context:ingress-v1" in transformer["add"]["headers"]

    for route_name in ("integration-token", "integration-open-api"):
        transformer = routes[route_name]["plugins"][0]["config"]
        assert "X-Portal" in transformer["remove"]["headers"]
        assert "X-Auth-Context:INTEGRATION" in transformer["add"]["headers"]


def test_kong_uses_protocol_specific_upstream_timeouts() -> None:
    config = load_yaml("infrastructure/kong/kong.yml")
    services = {service["name"]: service for service in config["services"]}

    assert services["django-api"]["read_timeout"] == 60_000
    assert services["django-events"]["read_timeout"] == 3_600_000
    assert services["django-workspace"]["read_timeout"] == 600_000
    assert services["django-files"]["read_timeout"] == 300_000
    assert all(service["retries"] == 0 for service in services.values())
    assert {plugin["name"] for plugin in config["plugins"]} >= {
        "correlation-id",
        "opentelemetry",
    }


def test_only_student_portal_exposes_event_stream() -> None:
    config = load_yaml("infrastructure/kong/kong.yml")
    events = next(service for service in config["services"] if service["name"] == "django-events")
    assert {route["name"] for route in events["routes"]} == {"student-events"}
    for relative_path, hosts in (
        (
            "infrastructure/nginx/nginx.conf",
            {
                "student.localhost student.example.edu": True,
                "teacher.localhost teacher.example.edu": False,
                "admin.localhost admin.example.edu": False,
            },
        ),
        (
            "infrastructure/nginx/nginx.prod.conf",
            {
                "${STUDENT_HOST}": True,
                "${TEACHER_HOST}": False,
                "${ADMIN_HOST}": False,
            },
        ),
    ):
        nginx = (ROOT / relative_path).read_text(encoding="utf-8")
        for host, student_access in hosts.items():
            block = server_block(nginx, host)
            event_location = block.split("location = /api/v2/events/stream {", maxsplit=1)[1]
            event_location = event_location.split("}", maxsplit=1)[0]
            if student_access:
                assert "proxy_pass http://gateway;" in event_location
                assert "proxy_buffering off;" in event_location
                assert "proxy_read_timeout 1h;" in event_location
            else:
                assert "return 403;" in event_location


def test_machine_host_has_no_static_site_and_only_integration_routes() -> None:
    nginx = (ROOT / "infrastructure/nginx/nginx.conf").read_text(encoding="utf-8")
    machine_server = nginx.split("server_name api.localhost api.example.edu;", maxsplit=1)[1]
    machine_server = machine_server.split("server {", maxsplit=1)[0]

    assert "/api/v2/integrations/oauth/token" in machine_server
    assert "/api/v2/integrations/open/" in machine_server
    assert "location / { return 404; }" in machine_server
    assert "root /srv" not in machine_server


def test_production_edge_terminates_tls_from_swarm_secrets() -> None:
    nginx = (ROOT / "infrastructure/nginx/nginx.prod.conf").read_text(encoding="utf-8")
    stack = load_yaml("infrastructure/swarm/stack.yml")

    assert "listen 8443 ssl;" in nginx
    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"' in nginx
    assert "ssl_certificate /run/secrets/tls_certificate;" in nginx
    assert "ssl_certificate_key /run/secrets/tls_private_key;" in nginx
    assert {"tls_certificate", "tls_private_key"} <= set(stack["services"]["nginx"]["secrets"])


def test_workspace_edge_allows_only_same_origin_embedding() -> None:
    for relative_path, student_host in (
        ("infrastructure/nginx/nginx.conf", "student.localhost student.example.edu"),
        ("infrastructure/nginx/nginx.prod.conf", "${STUDENT_HOST}"),
    ):
        nginx = (ROOT / relative_path).read_text(encoding="utf-8")
        student = server_block(nginx, student_host)
        workspace = student.split("location /workspace/ {", maxsplit=1)[1]
        workspace = workspace.split("}", maxsplit=1)[0]

        assert "proxy_hide_header X-Frame-Options;" in workspace
        assert "proxy_hide_header Content-Security-Policy;" in workspace
        assert "add_header X-Frame-Options SAMEORIGIN always;" in workspace
        assert "frame-ancestors 'self'" in workspace


def test_p14_workspace_internal_key_is_scoped_to_gateway_and_authority() -> None:
    stack = load_yaml("infrastructure/swarm/stack.yml")

    assert "WORKSPACE_INTERNAL_KEY_FILE" not in stack["x-app-environment"]
    for service in ("django", "workspace-gateway"):
        assert "workspace_internal_key" in stack["services"][service]["secrets"]
        assert (
            stack["services"][service]["environment"]["WORKSPACE_INTERNAL_KEY_FILE"]
            == "/run/secrets/workspace_internal_key"
        )
    for service in ("celery", "runtime-worker"):
        assert "workspace_internal_key" not in stack["services"][service]["secrets"]


def test_p14_swarm_hosts_network_and_support_images_are_deployment_injected() -> None:
    stack = load_yaml("infrastructure/swarm/stack.yml")
    environment = stack["x-app-environment"]

    assert environment["DJANGO_ALLOWED_HOSTS"] == "${DJANGO_ALLOWED_HOSTS}"
    assert environment["DJANGO_TRUSTED_ORIGINS"] == "${DJANGO_TRUSTED_ORIGINS}"
    assert environment["WORKSPACE_ALLOWED_ORIGINS"] == "${WORKSPACE_ALLOWED_ORIGINS}"
    assert environment["TRUSTED_PROXY_CIDRS"] == "${TRUSTED_PROXY_CIDRS}"
    assert stack["networks"]["app"]["ipam"]["config"][0]["subnet"] == "${APP_NETWORK_SUBNET}"
    assert "example.edu" not in (ROOT / "infrastructure/swarm/stack.yml").read_text(
        encoding="utf-8"
    )


def test_local_runtime_docker_access_is_scoped_to_runtime_worker() -> None:
    compose = load_yaml("docker-compose.dev.yml")
    services = compose["services"]
    assert "/var/run/docker.sock:/var/run/docker.sock" in services["runtime-worker"]["volumes"]
    for service, definition in services.items():
        if service == "runtime-worker":
            continue
        assert not any(
            "docker.sock" in str(item) for item in definition.get("volumes", [])
        )
    environment = compose["x-app-environment"]
    assert environment["RUNTIME_MODE"] == "${RUNTIME_MODE:-local}"
    assert environment["RUNTIME_ADAPTER_CODE"] == "${RUNTIME_ADAPTER_CODE:-runtime/local-docker}"
    assert environment["LOCAL_RUNTIME_MODE"] == "${LOCAL_RUNTIME_MODE:-REAL}"
    assert environment["AUTO_PROVISION_ON_ASSIGNMENT"] == (
        "${AUTO_PROVISION_ON_ASSIGNMENT:-true}"
    )
    assert environment["LOCAL_RUNTIME_IMAGE"] == (
        "${LOCAL_RUNTIME_IMAGE:-edu-platform-algorithm-workspace:local}"
    )
    assert environment["LOCAL_RUNTIME_NETWORK"] == (
        "${LOCAL_RUNTIME_NETWORK:-edu-platform-p14_runtime}"
    )
    assert environment["LOCAL_DOCKER_HOST"] == (
        "${LOCAL_DOCKER_HOST:-unix:///var/run/docker.sock}"
    )
    assert environment["RUNTIME_ADAPTER_CONFIGS"] == (
        '${RUNTIME_ADAPTER_CONFIGS:-{"runtime/local-docker":'
        '{"runtime_network":"edu-platform-p14_runtime","pids_limit":128}}}'
    )
    assert "q_workspace_storage" in services["runtime-worker"]["command"][-1]


def test_swarm_runtime_access_is_injected_only_into_runtime_worker() -> None:
    stack = load_yaml("infrastructure/swarm/stack.yml")
    environment = stack["x-app-environment"]
    services = stack["services"]
    assert environment["RUNTIME_MODE"] == "swarm"
    assert environment["RUNTIME_ADAPTER_CODE"] == "${RUNTIME_ADAPTER_CODE:-runtime/swarm}"
    assert "runtime/swarm" in environment["RUNTIME_ADAPTER_CONFIGS"]
    assert {
        "swarm_docker_ca",
        "swarm_docker_cert",
        "swarm_docker_key",
    } <= set(services["runtime-worker"]["secrets"])
    for service in ("django", "celery", "workspace-gateway"):
        assert not {
            "swarm_docker_ca",
            "swarm_docker_cert",
            "swarm_docker_key",
        } & set(services[service].get("secrets", []))
    assert "q_workspace_storage" in services["runtime-worker"]["command"][-1]


def test_compose_declares_foundation_services_and_isolated_app_network() -> None:
    compose = load_yaml("docker-compose.dev.yml")
    assert {
        "mysql",
        "redis",
        "mongodb",
        "minio",
        "clamav",
        "django",
        "celery",
        "kong",
        "nginx",
        "fluent-bit",
        "otel-collector",
        "prometheus",
        "mysql-users",
        "mysql-grants",
    } <= set(compose["services"])
    assert compose["networks"]["app"]["internal"] is True
    assert (
        compose["networks"]["app"]["ipam"]["config"][0]["subnet"]
        == "${APP_NETWORK_SUBNET:-172.29.20.0/24}"
    )
    assert compose["services"]["kong"]["environment"]["KONG_NGINX_WORKER_PROCESSES"] == "2"
    assert (
        "127.0.0.1:${FLUENTD_HOST_PORT:-24224}:24224" in compose["services"]["fluent-bit"]["ports"]
    )
    assert "${ENTRY_PORT:-8080}:8080" in compose["services"]["nginx"]["ports"]
    assert set(compose["services"]["fluent-bit"]["networks"]) == {"observability", "log-driver"}
    for service in ("django", "celery", "kong", "nginx"):
        assert "fluent-bit" in compose["services"][service]["depends_on"]


def test_p01_splits_migration_and_runtime_database_accounts() -> None:
    compose = load_yaml("docker-compose.dev.yml")
    app_environment = compose["x-app-environment"]
    migrate_environment = compose["services"]["migrate"]["environment"]
    bootstrap = (ROOT / "infrastructure/mysql/configure-users.sh").read_text(encoding="utf-8")

    assert "MYSQL_APP_USER" in app_environment["MYSQL_USER"]
    assert "MYSQL_MIGRATION_USER" in migrate_environment["MYSQL_USER"]
    for table in (
        "core_object_purge_log",
        "core_outbox_event",
        "core_audit_log",
        "core_failure_record",
    ):
        assert f"GRANT SELECT, INSERT ON \\`${{MYSQL_DATABASE}}\\`.{table}" in bootstrap


def test_p08_runtime_database_grants_workspace_append_only_tables_read_insert_only() -> None:
    bootstrap = (ROOT / "infrastructure/mysql/configure-users.sh").read_text(encoding="utf-8")
    assert (
        "GRANT SELECT, INSERT, UPDATE ON \\`${MYSQL_DATABASE}\\`.workspaces_workspace_session"
        in bootstrap
    )
    for table in (
        "workspaces_workspace_snapshot",
        "workspaces_workspace_autosave_log",
        "workspaces_workspace_checkpoint",
        "workspaces_operation_event",
    ):
        assert f"GRANT SELECT, INSERT ON \\`${{MYSQL_DATABASE}}\\`.{table}" in bootstrap
        assert f"GRANT SELECT, INSERT, UPDATE ON \\`${{MYSQL_DATABASE}}\\`.{table}" not in bootstrap
    assert (
        "GRANT SELECT, INSERT, UPDATE ON \\`${MYSQL_DATABASE}\\`.workspaces_execution_run"
        " TO '${MYSQL_APP_USER}'@'%'" in bootstrap
    )


def test_p09_runtime_database_grants_reports_and_download_grants_least_privilege() -> None:
    bootstrap = (ROOT / "infrastructure/mysql/configure-users.sh").read_text(encoding="utf-8")
    assert (
        "GRANT SELECT, INSERT, UPDATE ON \\`${MYSQL_DATABASE}\\`.core_file_download_grant"
        in bootstrap
    )
    assert (
        "GRANT SELECT, INSERT, UPDATE ON \\`${MYSQL_DATABASE}\\`.reports_report_draft"
        in bootstrap
    )
    for table in (
        "reports_report_attachment",
        "reports_report_version",
        "reports_report_version_attachment",
        "reports_system_artifact",
    ):
        assert f"GRANT SELECT, INSERT ON \\`${{MYSQL_DATABASE}}\\`.{table}" in bootstrap
        assert f"GRANT SELECT, INSERT, UPDATE ON \\`${{MYSQL_DATABASE}}\\`.{table}" not in bootstrap
    compose = load_yaml("docker-compose.dev.yml")
    assert compose["services"]["minio"]["ports"][0] == (
        "127.0.0.1:${MINIO_API_PORT:-9000}:9000"
    )
    assert set(compose["services"]["minio"]["networks"]) == {"data", "minio-host-access"}
    assert compose["networks"]["minio-host-access"] == {}


def test_p10_runtime_database_grants_keep_review_history_append_only() -> None:
    bootstrap = (ROOT / "infrastructure/mysql/configure-users.sh").read_text(encoding="utf-8")
    for table in (
        "reviews_review",
        "reviews_criterion_score",
        "reviews_review_annotation",
        "reviews_auto_check_run",
        "reviews_similarity_run",
        "reviews_similarity_match",
    ):
        assert rf"GRANT SELECT, INSERT, UPDATE ON \`${{MYSQL_DATABASE}}\`.{table}" in bootstrap
    for table in (
        "reviews_criterion_score_event",
        "reviews_review_decision",
        "reviews_annotation_revision",
    ):
        assert rf"GRANT SELECT, INSERT ON \`${{MYSQL_DATABASE}}\`.{table}" in bootstrap
        assert rf"GRANT SELECT, INSERT, UPDATE ON \`${{MYSQL_DATABASE}}\`.{table}" not in bootstrap


def test_p11_archive_permissions_and_scheduler_are_least_privilege() -> None:
    bootstrap = (ROOT / "infrastructure/mysql/configure-users.sh").read_text(encoding="utf-8")
    assert (
        r"GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.archives_archive_job"
        in bootstrap
    )
    for table in (
        "archives_archive_manifest",
        "archives_archive_verification",
        "archives_export_grant",
    ):
        assert rf"GRANT SELECT, INSERT ON \`${{MYSQL_DATABASE}}\`.{table}" in bootstrap
        assert rf"GRANT SELECT, INSERT, UPDATE ON \`${{MYSQL_DATABASE}}\`.{table}" not in bootstrap
    compose = load_yaml("docker-compose.dev.yml")
    assert compose["services"]["celery-beat"]["command"][3] == "beat"


def test_p15_new_experiment_tables_are_available_to_the_application_user() -> None:
    bootstrap = (ROOT / "infrastructure/mysql/configure-users.sh").read_text(encoding="utf-8")
    writable_tables = (
        "courses_academic_term",
        "labtemplates_template_chapter",
        "labtemplates_template_task",
        "labtemplates_experiment_image",
        "labtemplates_image_build_job",
        "labtemplates_legacy_template_migration",
        "provisioning_runtime_capacity_reservation",
    )
    append_only_tables = (
        "experiments_publication_chapter",
        "experiments_publication_task",
    )
    for table in writable_tables:
        assert rf"GRANT SELECT, INSERT, UPDATE ON \`${{MYSQL_DATABASE}}\`.{table}" in bootstrap
    for table in append_only_tables:
        assert rf"GRANT SELECT, INSERT ON \`${{MYSQL_DATABASE}}\`.{table}" in bootstrap


def test_p08_minio_policy_scopes_versioned_workspace_objects() -> None:
    policy = json.loads(
        (ROOT / "infrastructure/minio/app-policy.json").read_text(encoding="utf-8")
    )
    object_statement = policy["Statement"][1]
    assert set(object_statement["Resource"]) == {
        "arn:aws:s3:::edu-platform/template-assets/*",
        "arn:aws:s3:::edu-platform/workspaces/*",
        "arn:aws:s3:::edu-platform/reports/*",
        "arn:aws:s3:::edu-platform/archives/*",
    }
    assert {"s3:GetObjectVersion", "s3:DeleteObjectVersion"} <= set(object_statement["Action"])


def test_p01_declares_architecture_queue_names() -> None:
    settings = (
        ROOT
        / "backend/education_experiment_platform/settings/base.py"
    ).read_text(encoding="utf-8")
    queues = {
        "q_default",
        "q_relay",
        "q_provision",
        "q_archive",
        "q_compensate",
        "q_agent",
        "q_content",
        "q_analytics",
        "q_integrations",
    }

    assert all(queue in settings for queue in queues)


def test_django_preserves_gateway_peer_address_for_proxy_trust() -> None:
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")

    assert "--no-proxy-headers" in dockerfile
    assert "--forwarded-allow-ips=*" not in dockerfile


def test_greenfield_backend_has_target_apps_and_no_teams_package() -> None:
    app_root = ROOT / "backend/apps"
    expected = {
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
    assert {path.name for path in app_root.iterdir() if path.is_dir()} >= expected
    assert not (app_root / "teams").exists()


def test_backend_has_single_canonical_django_project() -> None:
    canonical = ROOT / "backend"

    assert (canonical / "manage.py").is_file()
    assert (canonical / "apps").is_dir()
    assert (canonical / "education_experiment_platform/settings/base.py").is_file()
    for legacy_path in (
        canonical / "education_experiment_platform/manage.py",
        canonical / "education_experiment_platform/apps",
        ROOT / "backend/config",
        ROOT / "backend/Dockerfile.prod",
    ):
        assert not legacy_path.exists()


def test_frontends_are_independent_build_entries() -> None:
    apps_root = ROOT / "frontend/apps"
    for app_name in ("student-web", "teacher-web", "admin-web"):
        app = apps_root / app_name
        assert (app / "index.html").is_file()
        assert (app / "vite.config.ts").is_file()
        assert (app / "src/main.tsx").is_file()
