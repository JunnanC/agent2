# 阶段：P14 Docker Swarm 真实适配、HA 与全链路验收

开始条件：P13-C 本地门禁通过；既有 P12/P13 工作区改动保留。

## 本次范围

- 实现 Docker Swarm `RuntimeAdapter`，保留 `FAKE` 单元测试驱动，不实现 Libvirt。
- 接入 digest 固定镜像、CPU/内存 reservation/limit、runtime 节点约束、内部 overlay、健康探针、TTL、非 privileged、`no-new-privileges`、无宿主端口、幂等创建/销毁、失败补偿和容量协调。
- 将运行时治理、归档对账、孤儿人工处置、MinIO 版本回读/digest 校验/retention 清理接入现有事实模型。
- 增加独立 workspace-gateway、同源 workspace URLs、短期 HttpOnly/Secure 工作区 Cookie，以及 WebIDE/Notebook/Terminal/Preview 标签页。
- 升级 Compose/Swarm stack 到 `0.14.0-p14` / `v2-p14`，拆分 runtime Worker，补齐 mTLS Secret/Config 约定和部署、回滚、证据脚本。

## 本地门禁

开发环境：Windows Docker Desktop `desktop-linux`，Docker Engine `28.5.1`，单 Manager/单 runtime 节点。

执行结果：

- `scripts/verify-p13-c.ps1`：后端 `197 passed`，Ruff 通过，OpenAPI 校验无错误，前端 Vitest `23 passed`，user/teacher/admin typecheck 与 build 通过，Compose config 通过。
- gateway 安全回归：Origin、路径/能力、非法 authority upstream、ASGI 早期拒绝测试通过。
- Swarm adapter 单元测试：digest、资源限制、网络、幂等、托管标签、ALLOWLIST 失败关闭、健康降级、销毁和 inventory 测试通过。
- `scripts/p14-runtime-smoke.py`：真实 Docker Engine 创建服务并等待 `READY`；`/healthz` 加四能力 HTTP 路径 `4/4`、Terminal WebSocket 回显通过；销毁后 `ABSENT` 且 managed inventory `0`。
- Swarm stack 使用部署变量注入 Host/CIDR/基础镜像；`docker stack config`、Kong 3.9 declarative config parse、PowerShell 和 Nginx entrypoint shell syntax 均通过。生产 Nginx 镜像构建因当前 Docker Hub `node:24-alpine` token/network 不可达未完成，需在可访问私有/镜像仓库的部署环境重试。

真实 reference workspace 镜像：

- 基础镜像固定为 `m.daocloud.io/docker.io/library/python:3.14-slim@sha256:caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2`。
- 构建 tag：`edu-platform-reference-workspace:0.14.0-p14`。
- 本地验证 digest：`sha256:65791738241eb34bbfb657b9c0ab276227c3dbe549376d2687839d49b43fb074`。
- 镜像以非 root `workspace` 用户运行，仅监听容器 `8080`，不发布宿主端口；`curl` 健康探针和 WebSocket contract 已验证。

证据目录：`evidence/p14/local-20260925/`，包含 Docker 版本、单节点 Swarm、内部 runtime network 和采集时间；不包含 Secret。

## 真实环境门禁

状态：待验收，不能标记正式通过。

尚未具备或未在本机可证明的项目：三 Manager quorum、Manager/Worker/数据节点故障与恢复、正式 DNS/TLS/入口、防火墙与可信代理、私有仓库推送/鉴权/回滚、外部 MySQL/Redis/MongoDB/MinIO 冗余和恢复、Secret/Config 轮换、滚动发布自动回滚、50 实例/20 并发启动/100 在线用户性能、RPO/RTO，以及经 Nginx → Kong → Django → Celery runtime Worker 的完整业务旅程。

当前 reference workspace 是固定版本的本地 contract fixture；正式环境必须用经过审批的 WebIDE、Jupyter、Web Terminal、Preview 组合镜像替换，并重新锁定 digest、执行模板预检和全链路证据。

## 出口结论

**P14 实现完成；本地单节点真实 Runtime 验证完成；正式环境 HA、性能、恢复和完整业务验收阻塞。**

本记录不把单节点结果写成“正式通过”，也不声明 VM/LIBVIRT 已通过。
