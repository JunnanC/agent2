# 部署与 Swarm 边界

核对日期：2026-11-12。

当前编程题真实运行以 Docker Local 验收。`infrastructure/swarm/stack.yml` 保留门户、数据服务连接和后台进程模板，但分布式 stdio 判题尚未实现。编程题发布预检要求 `DOCKER_LOCAL` 与真实执行；不支持的驱动明确拒绝，不回退模拟结果。

部署模板已移除旧工作区网关、常驻学生容器、参考容器、存储 worker 及上游令牌。保留 worker、Beat、对象存储与扫描服务。学生页面不公开容器端口，不挂载应用密钥或 Docker socket。

ACR/CD 的实际本地 Docker 发布入口见 [ACR-CD](ACR-CD.md)。该流程先检查既有卷与配置、扫描服务健康和资源归属，备份后执行迁移；新链路需要 Beat 与 ClamAV，原小内存主机应单独验证容量。脚本预检拒绝仍声明旧服务的 override，不会隐式创建空业务库。

部署命令以 `scripts/deploy` 当前文件为准。`docker stack config --skip-interpolation` 只证明模板语法，不证明运行成功。生产 DNS/TLS、存储、备份恢复、镜像回滚、并发容量和多节点故障必须在目标环境验收；本地浏览器与容器测试不能代替这些结论。

## 运行时环境配置

服务器部署完成后执行一次（按编码幂等，可重复执行）：

```powershell
docker compose exec django python manage.py configure_runtime_adapters --admin <平台管理员账号>
```

- 默认登记并启用本机 Docker 适配器：编码 `DOCKER-LOCAL`，配置引用取 `RUNTIME_ADAPTER_CODE`（默认 `runtime/local-docker`），驱动 `DOCKER_LOCAL`
- 同时登记 Docker 集群适配器：编码 `DOCKER-SWARM`，配置引用 `runtime/swarm`（驱动 `DOCKER_SWARM`），但保持停用；集群判题驱动实现后再加 `--enable-swarm` 启用
- 适配器容量与健康由 `probe_runtime_adapters` 定时任务刷新，管理端「服务与资源」可查看

环境变量按部署形态二选一：

| 形态 | 关键变量 |
| --- | --- |
| 本机 Docker | `RUNTIME_MODE=local`、`LOCAL_DOCKER_HOST`（只接受本机 socket）、`LOCAL_RUNTIME_IMAGE`、`LOCAL_RUNTIME_NETWORK`、`RUNTIME_ADAPTER_CONFIGS` 含 `runtime/local-docker` |
| Docker 集群 | `RUNTIME_MODE=swarm`、`SWARM_DOCKER_*`（含 mTLS 证书）、`SWARM_RUNTIME_NETWORK`、`RUNTIME_ADAPTER_CONFIGS` 含 `runtime/swarm`；`infrastructure/swarm/stack.yml` 已按此预设 |

教师端不选择运行环境：新建版本自动取「已启用且判题驱动受支持的适配器 + 已审批镜像」，所以切换本机/集群不需要改教师界面。集群判题驱动未实现前，即使启用适配器，编程题预检也会拒绝执行。

测试使用独立 Compose 项目及数据卷，清理必须按明确项目和受管标签限定，禁止全局清理。删除旧表的迁移会丢弃旧测试业务事实，部署前保留备份；不转换旧作业数据。
