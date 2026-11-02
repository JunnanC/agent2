# Swarm staging deployment

## Execution timing

This stack is the real-environment baseline and is not required for day-to-day local development, which uses `docker-compose.dev.yml`. Local verification does not certify production readiness. Validate infrastructure, business flows, runtime isolation, rollback and recovery in the target environment before release. The original stage sequence is retained in the [deployment agreement](../../docs/开发任务拆分/00A_本地开发与最终真实部署约定.md); current executable names are listed in the [script inventory](../../scripts/README.md).

The stack runs stateless platform services only. MySQL, Redis, MongoDB Replica Set, and MinIO must be supplied through an external managed service or a separately reviewed replicated data stack with non-local persistent storage. A single-node volume does not establish high availability.

Required node labels are boolean labels under `edu.role`: `edge`, `app`, `worker`, `runtime`, and `data`. A node may carry more than one label in a small staging cluster, but data and student runtime workloads should not be co-located without an explicit review. Configure each node's Docker daemon to permit the Fluentd logging driver; the global Fluent Bit service listens on host port 24224 and buffers locally when the MongoDB sink is unavailable. The local single-node helper is `scripts/deploy/bootstrap-local-swarm.ps1`; it is an adapter smoke environment only and does not certify HA.

The runtime overlay network is external to the stack and shared with dynamically created experiment services. Its default name is `experimental-platform-swarm-runtime`, separate from the local Compose bridge. Create it once before deployment with `docker network create --driver overlay --internal --label edu.platform.managed=true --label edu.platform.kind=runtime-gateway-network experimental-platform-swarm-runtime`, or use the local helper in a disposable single-node environment. Set `SWARM_RUNTIME_NETWORK` consistently when choosing another name.

Build the staging edge image with `infrastructure/nginx/Dockerfile.prod`; it renders the four deployment Hosts at container start, redirects port 80 to TLS, and reads the certificate from Swarm secrets. Create versioned configs and secrets before deploying. Never pass secret values through Swarm configs or the command line history. Required environment variables are `REGISTRY`, `IMAGE_TAG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_TRUSTED_ORIGINS`, `WORKSPACE_ALLOWED_ORIGINS`, `TRUSTED_PROXY_CIDRS`, `APP_NETWORK_SUBNET`, `STUDENT_HOST`, `TEACHER_HOST`, `ADMIN_HOST`, `API_HOST`, `KONG_IMAGE`, `FLUENT_BIT_IMAGE`, `OTEL_COLLECTOR_IMAGE`, `MYSQL_HOST`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `MINIO_ENDPOINT`, `CLAMAV_HOST`, and `SWARM_DOCKER_HOST`. Required secrets are `django_secret_key`, `identity_hmac_key`, `course_invitation_hmac_key`, `mysql_app_password`, `mongodb_uri`, `minio_app_access_key`, `minio_app_secret_key`, `workspace_internal_key`, `swarm_docker_ca`, `swarm_docker_cert`, `swarm_docker_key`, `tls_certificate`, and `tls_private_key`. The identity HMAC key is independent from Django's signing key and must be generated, stored, and rotated as a separate secret. Runtime workers alone receive Docker API mTLS material; Django Web, ordinary Celery, and workspace-gateway do not.

```powershell
./scripts/deploy/label-swarm-nodes.ps1 -ManagerNodes manager-1,manager-2,manager-3
docker stack deploy --with-registry-auth -c infrastructure/swarm/stack.yml experimental-platform
```

The three-manager quorum, external storage failover, rolling rollback, and node-loss exercises must be recorded in a staging environment. They cannot be certified by a single-node Docker Desktop run.
