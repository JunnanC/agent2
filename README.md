# Experimental Platform

教学实验平台，包含 React 学生端、教师端和管理端，以及 Django API、Celery 后台任务、Docker 实验工作区、报告审核和受控 Agent 等模块。

## 本地 Docker 部署

只运行容器时需要 Docker Desktop（Linux containers）和 Compose v2。主机运行前端工具需要 Node.js 24，运行后端工具需要 Python 3.14。

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
New-Item -ItemType Directory -Force secrets | Out-Null
# 随机生成工作区令牌；不要覆盖已有令牌。
if (-not (Test-Path secrets/workspace_upstream_token)) {
    $tokenBytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Fill($tokenBytes)
    [IO.File]::WriteAllText((Join-Path $PWD 'secrets/workspace_upstream_token'), [Convert]::ToBase64String($tokenBytes))
}
# 先为 .env 中的密码及密钥占位值设置独立随机值。
docker compose --profile runtime up -d --build
```

默认项目名为 `experimental-platform`。`.env.example` 中的 `COMPOSE_FILE` 选择 `docker-compose.dev.yml`；本机额外覆盖文件应只放环境差异。例如 Windows 的 `.env` 可以设置 `COMPOSE_FILE=docker-compose.dev.yml;docker-compose.override.local`。Linux/macOS 多文件分隔符为 `:`。显式 `-f` 会覆盖文件选择，使用前确认加载范围。

## Frontend hot-reload development

The `:8080` portals are built into the Nginx image. Use the separate Vite development
entry when editing frontend source files; it mounts `frontend/` read-only and polls for
changes, so saving a source file updates the browser without rebuilding Nginx.

```powershell
.\scripts\frontend-dev-up.ps1
```

Development portal URLs:

- `http://student.localhost:5173`
- `http://teacher.localhost:5174`
- `http://admin.localhost:5176`

To start only the frontend services when the backend stack is already running:

```powershell
.\scripts\frontend-dev-up.ps1 -SkipBackend
```

View or stop the frontend development services:

```powershell
docker compose --project-name edu-platform-frontend-dev -f docker-compose.frontend-dev.yml logs -f
.\scripts\frontend-dev-down.ps1
```

Keep using `http://*.localhost:8080` for the static, deployment-style Nginx build.

The edge entry point listens on port `8080`. Use the hostnames below so portal cookies and trusted host mapping remain isolated:

| 门户 | 地址 |
| --- | --- |
| 学生 | http://student.localhost:8080 |
| 教师 | http://teacher.localhost:8080 |
| 管理 | http://admin.localhost:8080 |
| 集成 API | http://api.localhost:8080（只开放集成接口） |

前端构建后由 Nginx 提供，后端在容器中运行，网页统一从 8080 访问。Vite 开发服务器需要另外运行：在 `frontend/` 执行 `npm run dev:student`、`npm run dev:teacher` 或 `npm run dev:admin`。

## 镜像与资源名称

| 本机镜像 | 构建入口 |
| --- | --- |
| `experimental-platform-backend:local` | `backend/Dockerfile` |
| `experimental-platform-web:local` | `infrastructure/nginx/Dockerfile`，包含三个前端 |
| `experimental-platform-workspace:local` | `runtime/algorithm-workspace/Dockerfile` |
| `experimental-platform-reference:local` | `runtime/reference-workspace/Dockerfile` |

后端服务共享一个镜像。容器、网络、持久卷由 Compose 项目名生成，例如 `experimental-platform-django`、`experimental-platform-runtime`、`experimental-platform-minio-data`。独立验证使用不同的 `-p` 项目名，并选择独立端口、应用子网及运行时配置；不要把本机固定资源覆盖文件带入测试环境。

学生实验资源由运行时动态管理，使用 `experimental-platform-lab-<短标识>-<摘要>`、`experimental-platform-workspace-<短标识>-<摘要>` 和 `experimental-platform-secret-<短标识>-<摘要>`。任务归属依靠 labels，不能仅凭名称删除资源。

更新源码后：

```powershell
docker compose build django nginx
docker compose --profile runtime up -d --no-build
docker compose restart kong nginx
```

重启代理刷新后端重建前缓存的地址。`docker compose --profile runtime stop` 保留数据并停止服务。六个初始化任务正常完成后显示 `Exited (0)`，无需常驻。动态实验容器请从平台业务入口停止和回收。

## 演示数据

以下种子仅用于可丢弃的 local/integration/test 环境，不能用于真实用户库：

```powershell
docker compose --profile tools run --rm --no-deps core-check python manage.py seed_demo_full --scale small
```

演示账号为 `admin.demo@example.edu`、`teacher-01.demo@example.edu`、`student-001.demo@example.edu`。密码取 `DEMO_SEED_PASSWORD`，模板默认是 `Demo-Seed-Only-2026!`，仅用于本地演示。种子的判题附件可能包含占位记录，真实判题前需上传并扫描有效测试附件，不能把种子生成成功视为完整验收。

## 开发与验证

- 后端命令、迁移和检查：[backend/README.md](backend/README.md)。唯一 Django 项目位于 `backend`。
- 前端：在 `frontend/` 运行 `npm ci --ignore-scripts`、`npm run typecheck`、`npm test`、`npm run build`。
- 工作区镜像验证：`scripts/verify/workspace-image.ps1 -Image experimental-platform-workspace:local -SkipBuild`。
- 文档导航：[项目资料索引](docs/项目资料索引.md)。`docs/` 统一存放架构设计、前端对接、阶段规划和历史执行记录。
- 脚本入口与前置条件：[脚本索引](scripts/README.md)；旧编号与功能名称的对应见[命名约定与迁移表](docs/naming-conventions.md)。
- `.env`、`secrets/`、本机覆盖配置、临时日志和个人材料留在本地，不上传 GitHub；具体边界见 `.gitignore`。

Compose 本机通过只证明已验证的本地范围。Swarm 模板、Registry 晋级、真实 DNS/TLS、外部存储、故障恢复和 HA 需要在对应环境单独验收，参见 [Swarm 部署说明](infrastructure/swarm/README.md)。历史记录保留原日期、镜像及项目名称，不作为当前启动命令。
