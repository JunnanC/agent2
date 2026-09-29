# P16-G 镜像 Registry 晋级出口记录

阶段：P16-G 镜像 Registry 晋级

## 实现

- 新增 `scripts/p16-promote-image.ps1`，从已通过 P16-F 的本地镜像读取不可变 digest。
- 推送 promotion/rollback 标签，并拒绝覆盖已指向其他 digest 的 promotion 标签。
- 按 `repository@sha256:<digest>` 拉取并 inspect，生成允许镜像、部署配置、发布和回滚清单。
- 新增 `-JourneyUseExistingEnvironment`，支持在已通过的 Docker Compose 基线上按 digest 复验，不重新构建工作区镜像。
- `scripts/verify-p16-integration.ps1` 增加 `-SkipRuntimeBuild`、`-SeedPrerequisites`，并为独立复验支持独立子网和端口。

## Docker 验证结果

- Docker Engine：28.5.1，Compose/Playwright 均在容器内执行。
- 源镜像：`edu-platform-algorithm-workspace:p16-b`。
- 源、晋级和回滚 manifest digest：`sha256:0a14d72d6649e7d4114970d581199a89f3869b502cbc4abdf1192289d628e7ff`。
- 本地 Registry：`127.0.0.1:5000`，仅用于本地 P16-L 验证，不代表生产 Registry。
- 按 digest 重新拉取后执行 P16-F：Playwright `1 passed`。
- 工作区文件、MinIO 对象和快照 digest 一致；跨任务边界、恢复、提交和资源清理通过；清理后容器和 Volume 均为空。

证据目录：`evidence/p16/20260929-071857-p16-g/`

## 出口结论

**P16-G 本地通过（真实环境待验收）。**

服务器必须使用发布清单中的 digest 拉取镜像，禁止服务器重新 build；P16-H 的 Swarm、Registry 鉴权、节点迁移、Volume、容量、性能和 RPO/RTO 验收仍待真实环境完成。
