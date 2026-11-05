# GitHub Actions + ACR 个人版 + ECS

状态：四个镜像已完成 ACR 推送验证，ECS 首次升级仍待验收；DEPLOY_ENABLED 保持 false。

流程：main 的 Experimental Platform CI 成功 → GitHub 托管的 ubuntu-latest 构建四个 linux/amd64 镜像 → ACR 私有仓库 → ECS 上的专用 self-hosted runner 拉取镜像、备份 MySQL、运行 Compose 迁移和健康检查。镜像标签为完整 Git SHA，四个镜像全部推送成功后才部署；同一时刻只允许一次发布。手动触发也要求该 SHA 有成功的 push CI。

## 账号配置

在阿里云 ACR 个人版准备命名空间及四个私有仓库：agent2-backend、agent2-web、agent2-workspace、agent2-reference。登录密码为 ACR 访问凭证，不是 ECS root 密码。

GitHub 仓库 Variables：

| 名称 | 内容 |
| --- | --- |
| ACR_REGISTRY | 控制台给出的公网 Registry 域名，不含协议、命名空间 |
| ACR_NAMESPACE | 已创建的命名空间 |
| CD_ENABLED | 首先设为 true，仅启用构建推送 |
| DEPLOY_ENABLED | 首次迁移配置和备份检查完成后才设为 true |

Secrets：ACR_USERNAME、ACR_PASSWORD。不要把凭证写入 YAML 或源码。

部署使用 production environment。只在私有仓库的受信任 main 上运行生产 runner，不在 pull_request 上运行。保护 main，限制谁可以修改工作流及部署脚本。runner 用独立 Linux 用户运行；Docker 权限相当于主机 root 权限，不使用 root 运行 runner 服务。

GitHub 托管 runner 消耗账号 Actions 配额；ACR 个人版是否可免费使用及容量限制以当前账号控制台为准。这里不创建付费云资源。

## 现有 ECS 的首次迁移

检查时 ECS 为 Ubuntu 24.04 x86_64，旧项目为 /opt/agent2、Compose project 为 edu-platform。旧配置不是 Git checkout。宿主机 Nginx 已配置 80/443 → 8080，并通过 portal cookie 切换三个门户。不要覆盖宿主机 Nginx，也不要改用新的 Compose project 名。

**已发现的数据差异**：旧数据卷是 edu-platform_mysql-data 等下划线名称，新版默认是 edu-platform-mysql-data 等连字符名称。仅设置 project 名不能保留这些卷的绑定，必须设置 external 映射。新版还改变了网络、容器名、服务、运行时密钥和环境变量，需对比旧配置，先完成一次人工引导迁移，不能直接把全新默认 Compose 覆盖线上。

服务用户准备：

- 注册仓库级 runner，标签 agent2-production，配置为 systemd 服务并确认在 GitHub 显示 Online。
- 准备 /opt/agent2-cd/{releases,backups}，仅服务用户可写。
- 准备 /etc/agent2-cd/.env、compose.override.yml、secrets/workspace_upstream_token，仅服务用户可读。保留原密码和业务密钥；不要复制模板占位值到生产。
- server override 显式将 mysql-data、redis-data、mongo-data、mongo-keyfile、minio-data、clamav-data、fluent-bit-buffer 映射为原有 edu-platform_<卷名>，并设置 external: true。例如：

```yaml
volumes:
  mysql-data:
    external: true
    name: edu-platform_mysql-data
```

- 核对新版与旧版的网络名称、子网、全部应用环境变量、端口和服务资源预算。该主机 3.5 GiB RAM，检查时可用约 535 MiB；不要直接启用所有额外的监控/扫描服务而不验证容量。
- 对数据库、对象存储及相关持久化数据完成可恢复备份，保留旧配置和旧镜像；解决容器/网络名称迁移冲突。停写窗口内验证升级迁移，再启动新版服务。
- 设置 DEPLOY_ENABLED=true，触发 main 的 CI 或手动触发 CD。只有四个镜像推送成功、Compose 健康检查及 HTTP 检查通过，才记录 current。

## 首次上线预检和资源范围

在 Actions → ACR Continuous Deployment → Run workflow 中选择 main，保留 `preflight_only` 勾选。main 的 push CI 必须已通过。四镜像构建成功后，生产 runner 只检查 Compose 配置、七个旧数据卷、八个旧网络，以及 MySQL、Redis、MongoDB、MinIO、Fluent Bit 是否已运行且健康；不会拉取镜像、迁移或重启服务。该预检允许在 DEPLOY_ENABLED=false 时执行。首次切换前还需验证镜像可拉取、容器读取挂载文件以及升级迁移。

此 ECS 的部署脚本只管理 Django、Celery、runtime-worker、workspace-storage-worker、workspace-gateway、log-ingest、runtime-reference、Kong 和 Nginx。MySQL、Redis、MongoDB、MinIO、Fluent Bit 继续使用已有容器，基础设施更新需另行安排。ClamAV、监控、celery-beat 和一个空闲的 algorithm-workspace 不会被自动启动；这保留了旧服务器的启用范围，并新增独立存储任务 worker。若业务需要这些服务，先单独评估资源和启动方式。动态实验使用预拉取的 workspace 镜像。两个可调并发 worker 在这台主机上固定 concurrency=1。

实际发布会在备份成功后停止受管理的应用写入进程，依次运行 mysql-users、migrate、mysql-grants，然后启动应用和代理。因此会有短暂 API 中断；若迁移或启动失败，应用可能保持停止，需要人工恢复。旧源码 /opt/agent2 仍被基础设施容器挂载，不能删除。

发布目录中的源码用容器可读的权限解包，工作区令牌复制为真实文件，避免 /workspace 内的绝对主机链接失效。环境文件和解析后的配置仍保持 0600，发布目录的父目录保持 0700。

## 日常发布和失败处理

推送 main 自动走上述流程。每次部署在独立 releases/<SHA>.<随机后缀> 内保存源码、受限权限的环境文件与 Compose 配置，并在 backups 下创建 MySQL 逻辑备份。脚本不执行 down -v、卷删除、全局 prune 或演示数据种子；失败直接让 Actions 显示失败。current 只在成功后更新，失败现场保留以便排查。

失败不自动回滚数据库。迁移可能已部分执行，必须检查 schema 兼容性；选择旧镜像只能回退应用，不能撤销数据库迁移。需要恢复数据时，从已验证的备份按维护流程恢复，避免覆盖升级后产生的数据。按容量制定 releases 和 backups 保留策略；此脚本不自动删除备份。

ACR 登录、四镜像推送和 runner 注册已完成。脚本语法及工作流结构检查通过；首次迁移、切换及 HTTP 验收尚未执行。未验收前保持 DEPLOY_ENABLED 关闭。
