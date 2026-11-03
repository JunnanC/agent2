# 前端热更新开发模式 Plan

## 架构概览

新增一个独立的 `docker-compose.frontend-dev.yml` 覆盖文件，使用 Node.js 24 镜像运行学生、教师和管理端 Vite 开发服务器。前端源码以只读绑定挂载进入容器，三个服务分别映射到宿主机 5173、5174、5176（管理端容器内仍监听 5175，因为宿主机 5175 已被占用）；每个服务使用独立的匿名 `node_modules` 卷，避免宿主机依赖污染。

开发服务器通过 `host.docker.internal:8080` 访问现有 Nginx/Kong API 入口，并在各自 Vite 配置中注入对应门户 Host 和 Origin。现有 `docker-compose.dev.yml`、Nginx 静态构建入口和数据卷保持不变。

## 模块设计

### Vite 开发服务器配置

三个门户的 `server.host` 改为读取 `VITE_DEV_HOST`，默认仍为 `127.0.0.1`，容器开发模式设置为 `0.0.0.0`。API 目标继续读取 `VITE_DEV_API_TARGET`，默认值保持现有本机静态入口。

### Compose 开发覆盖

覆盖文件定义三个前端服务，使用 Node 24 Alpine，挂载 `frontend/` 源码和独立依赖卷，启动时执行 `npm ci --ignore-scripts` 后运行对应 workspace 的 Vite dev 命令。服务只依赖宿主机 8080 入口，不重建或替换 Nginx。

### PowerShell 启停入口

新增脚本负责检查 Docker、Compose 文件和端口，启动或停止三个前端服务，并打印访问地址、日志命令和静态入口说明。停止脚本只删除 `frontend-dev` Compose 项目，不删除任何数据卷。

### 文档

README 增加开发模式入口、端口、热更新行为、常见问题和静态部署入口的区别。

## 文件组织

```text
docker-compose.frontend-dev.yml
scripts/frontend-dev-up.ps1
scripts/frontend-dev-down.ps1
docs/superpowers/specs/2026-11-02-frontend-hot-reload-dev-mode-spec.md
docs/superpowers/plans/2026-11-02-frontend-hot-reload-dev-mode-plan.md
docs/superpowers/tasks/2026-11-02-frontend-hot-reload-dev-mode-task.md
docs/superpowers/checklists/2026-11-02-frontend-hot-reload-dev-mode-checklist.md
frontend/apps/*/vite.config.ts
README.md
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 前端运行位置 | Node 24 Docker 容器 | 当前宿主机 Node 22 不满足项目声明版本；容器可保证版本一致 |
| 源码同步 | 只读绑定挂载 | 支持 HMR，同时避免容器反向修改工作区 |
| API 入口 | 复用宿主机 8080 | 保留现有 Host 路由、Kong、认证和 WebSocket 行为 |
| 依赖存储 | 每个服务独立匿名卷 | 避免 Windows 宿主机 `node_modules` 与 Linux 容器二进制冲突 |
| 静态入口 | 保留 8080 | 继续支持部署式构建和验收，不与开发端口混淆 |
