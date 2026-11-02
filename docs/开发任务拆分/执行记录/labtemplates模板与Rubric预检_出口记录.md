> 历史命令说明（2026-10-30）：本文保留原开发阶段编号及当时执行记录。当前脚本、管理命令和 Compose 配置档已按功能重命名，执行前请查看[现入口迁移表](../../naming-conventions.md)；原命令不作为当前可用性证明。

# 实验模板 labtemplates 模板、Rubric 与预检出口记录

阶段：实验模板 labtemplates 模板、Rubric、受控资产与异步预检

日期：2026-09-22

## 范围与边界

- 已建立 `labtemplates` 四张架构表：模板、模板版本、自动检查规则、模板预检 run。
- 已建立 `reviews` 三张架构表：Rubric、Rubric 版本、Rubric criterion。
- 已实现模板/Rubric 状态机、版本冻结、课程资料冻结快照、治理 options、digest、权限 grant、CAS/If-Match、幂等、行锁、审计、Outbox 和 `q_provision` 异步预检。
- 已实现 MinIO/S3 受控上传、大小/MIME/magic/digest 校验、ClamAV 流式扫描、EICAR 拒绝和资产关联边界。
- 已接入课程复制注册式 handler，支持 `include_templates`、`include_rubrics` 及课程资料引用映射。
- 已接入 teacher-web 模板/Rubric 页面和 admin-web 只读预检监管页；OpenAPI revision 为 `v2-p05`，产品版本为 `0.6.0-p05`。
- 明确不进入 实验发布/实验环境装载：未创建 publication、个人任务、运行实例或 FakeRuntime。

## 静态与后端证据

- 后端 pytest：`105 passed`。
- Ruff：通过。
- mypy：通过（176 个源文件）。
- Django check：通过。
- migration dry-run：`No changes detected`。
- OpenAPI 生成并 validate：无错误；仅有 `status`、`runtime_type` enum 命名 warning。
- 前端 typecheck、lint、test、build：通过。
- Compose config、Swarm stack config、PowerShell 脚本解析：通过。

## 隔离 Compose 证据

执行入口：`scripts/verify-p05-integration.ps1`，独立 Compose project、空 MySQL 和独立网络/端口；验证结束自动清理 volumes、containers 和 networks。

- 空 MySQL 建表并确认 实验模板 七张表存在，应用数据库账号只获得最小业务权限。
- MinIO bucket、应用 policy、ClamAV `PONG` 和 Celery `q_provision` 通过。
- Django/OpenAPI validate、账号与门户身份/课程协作/资源治理/实验模板 disposable seed 通过。
- 真实 MinIO 上传入口读取 EICAR，资产被拒绝且未关联模板版本。
- edge stack（Nginx → Kong → Django 双副本）启动成功。
- 启动预热 health/CSRF 后执行 teacher/admin Playwright；两个测试均通过：
  - teacher 模板与 Rubric 页面可达、登录和课程导航通过。
  - admin 预检监管页只读事实和监管提示通过。
  - 1440、920、390 三种视口无横向溢出或遮挡。

## 修正记录

- 修正 admin 窄屏门户头部导航的 flex 最小宽度和内部横向滚动，避免导航撑大文档宽度。
- 实验模板 Playwright 登录断言增加冷启动容忍窗口；隔离脚本在浏览器前等待双门户 health/CSRF，避免将 edge 冷启动误判为业务失败。

## 真实环境门禁与出口

结论：**本地通过（真实环境待验收）**。

该结论仅表示本地静态检查和隔离 Compose 证据全部通过，不代表生产就绪。Swarm HA、正式 DNS/TLS、外部存储恢复、真实运行时容量/故障恢复和生产性能继续列为 真实运行环境 阻塞项；真实环境验收前不得将本记录解释为生产批准。
