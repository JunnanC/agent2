# Experimental Platform

教学实验平台，包含 React 学生端、教师端和管理端，以及 Django API、Celery 后台任务、Docker 短生命周期代码执行、报告审核和受控 Agent 等模块。

## 本地 Docker 部署

只运行容器时需要 Docker Desktop（Linux containers）和 Compose v2。主机运行前端工具需要 Node.js 24，运行后端工具需要 Python 3.14。

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 先为 .env 中的密码及密钥占位值设置独立随机值。
docker compose --profile runtime up -d --build
```

默认项目名为 `experimental-platform`。`.env.example` 中的 `COMPOSE_FILE` 选择 `docker-compose.dev.yml`；本机额外覆盖文件应只放环境差异。例如 Windows 的 `.env` 可以设置 `COMPOSE_FILE=docker-compose.dev.yml;docker-compose.override.local`。Linux/macOS 多文件分隔符为 `:`。显式 `-f` 会覆盖文件选择，使用前确认加载范围。

## Frontend hot-reload development

The `:8080` portals are built into the Nginx image. Use the separate Vite development
entry when editing frontend source files; it mounts `frontend/` read-only and polls for
changes, so saving a source file updates the browser without rebuilding Nginx.

```powershell
.\scripts\frontend-dev-up.ps1 -SkipBackend
```

Development portal URLs:

- `http://student.localhost:8081`
- `http://teacher.localhost:8082`
- `http://admin.localhost:8083`

The command above uses an already running backend. Omit `-SkipBackend` to also build and start the standard backend with the Compose configuration selected by `.env` and the `runtime` profile.

View or stop the frontend development services:

```powershell
docker compose --project-name experimental-platform-frontend -f docker-compose.frontend-dev.yml logs -f
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
| `experimental-platform-stdio:local` | `runtime/algorithm-workspace/Dockerfile.stdio` |

后端服务共享一个镜像。容器、网络、持久卷由 Compose 项目名生成，例如 `experimental-platform-django`、`experimental-platform-runtime`、`experimental-platform-minio-data`。独立验证使用不同的 `-p` 项目名，并选择独立端口、应用子网及运行时配置；不要把本机固定资源覆盖文件带入测试环境。

学生在平台轻量页面答题，代码由短生命周期 stdio 容器执行，不维持常驻 IDE 容器。执行资源依靠受管 labels 标识，不能仅凭名称删除资源。种子与验证见[轻量答题验收](docs/开发指南/轻量答题验收.md)。

更新源码后：

```powershell
docker compose build django nginx
docker compose --profile runtime up -d --no-build
docker compose restart kong nginx
```

重启代理刷新后端重建前缓存的地址。`docker compose --profile runtime stop` 保留数据并停止服务。六个初始化任务正常完成后显示 `Exited (0)`，无需常驻。动态实验容器请从平台业务入口停止和回收。

## 测试种子

新答题链路使用 `seed_assessment_e2e`，包含纯选择、纯编程和混合实验。需先创建测试课程、教师、选课学生及已审批的 stdio 运行资源，命令及参数见[轻量答题验收](docs/开发指南/轻量答题验收.md)。在独立测试库和存储中执行。

`seed_demo_full` 与旧生命周期种子尚待内部清理，生成旧格式任务，不能用于新链路验收。

## 开发与验证

- 后端命令、迁移和检查：[docs/开发指南/后端开发.md](docs/开发指南/后端开发.md)。唯一 Django 项目位于 `backend`。
- 前端：在 `frontend/` 运行 `npm ci --ignore-scripts`、`npm run typecheck`、`npm test`、`npm run build`。
- 代码执行验证：`python scripts/verify/assessment-runtime-smoke.py --image experimental-platform-stdio:local`。
- 项目文档：[文档索引](docs/README.md)，保留九份当前说明，覆盖架构、数据与接口、前后端开发、脚本、工作区、部署和记录模板。
- 过程产物：`outputs/` 当前为空，仅在需要时生成临时报告和证据，不维护历史资料索引。
- 脚本入口与前置条件：[脚本索引](docs/开发指南/脚本索引.md)；文件、脚本和命令直接按功能命名，不再使用阶段编号，见[命名约定](docs/README.md#命名约定)。
- `.env`、`secrets/`、本机覆盖配置、临时日志和个人材料留在本地，不上传 GitHub；具体边界见 `.gitignore`。

Compose 本机通过只证明已验证的本地范围。Swarm 模板、Registry 晋级、真实 DNS/TLS、外部存储、故障恢复和 HA 需要在对应环境单独验收，参见 [Swarm 部署说明](docs/开发指南/Swarm部署.md)。历史记录保留原日期、镜像及项目名称，不作为当前启动命令。
