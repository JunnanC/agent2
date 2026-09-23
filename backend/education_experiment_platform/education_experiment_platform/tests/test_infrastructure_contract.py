from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]


def load_yaml(relative_path: str) -> dict:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


def test_kong_overwrites_browser_and_machine_contexts() -> None:
    config = load_yaml("infrastructure/kong/kong.yml")
    service = config["services"][0]
    assert service["retries"] == 0
    routes = {route["name"]: route for route in service["routes"]}

    expected_portals = {
        "user-browser-api": "USER",
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


def test_p01_declares_architecture_queue_names() -> None:
    settings = (
        ROOT
        / "backend/education_experiment_platform/education_experiment_platform/settings/base.py"
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
    app_root = ROOT / "backend/education_experiment_platform/apps"
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
    canonical = ROOT / "backend/education_experiment_platform"

    assert (canonical / "manage.py").is_file()
    assert (canonical / "education_experiment_platform/settings/base.py").is_file()
    for legacy_path in (
        ROOT / "backend/apps",
        ROOT / "backend/config",
        ROOT / "backend/manage.py",
        ROOT / "backend/Dockerfile.prod",
    ):
        assert not legacy_path.exists()


def test_frontends_are_independent_build_entries() -> None:
    apps_root = ROOT / "frontend/apps"
    for app_name in ("user-web", "teacher-web", "admin-web"):
        app = apps_root / app_name
        assert (app / "index.html").is_file()
        assert (app / "vite.config.ts").is_file()
        assert (app / "src/main.tsx").is_file()
