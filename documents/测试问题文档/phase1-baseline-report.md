## 第一阶段基线 — 复现证据记录

**部署环境**: 阿里云 ECS (47.114.58.170)，EduTech P15 版本
**Git 提交号**: `071f03de47a2ccd52098ef130eae565d3dffe3d1`
**采集时间**: 2026-10-09（日志覆盖 2026-10-08）
**Django 容器**: `edu-platform-django-1`（另有 Swarm 服务 `edutech_api.1/2`）

---

### 一、Provisioning Job 失败记录（服务器真实证据）

#### 任务 7 — `01M3R4MVJGND8K1B60FNWQ2EGS`

| 次数 | Job ID | 状态 | 失败阶段 | 错误码 | Trace ID | 时间 (UTC) |
|------|--------|------|----------|--------|----------|------------|
| 1 | `01M4CKPDR95FRHMG3PTA9JPMDP` | 失败 | QUOTA_CHECK | RUNTIME_CLIENT_UNAVAILABLE | `manual-fix` | 01:57–02:00 |
| 2 | `01M4CKZKPF0Y5YFQESZYYMM0E4` | 失败 | QUOTA_CHECK | RUNTIME_NETWORK_CREATE_FAILED | `retry-fix` | 02:02 |
| 3 | `01M4D2T0X24MHV6NNAXWF1TA62` | 失败 | IMAGE_PREPARE | RUNTIME_IMAGE_QUERY_FAILED | `retry-after-build` | 06:22 |
| 4 | `01M4D6VNSREFZA7AGMTJYCWHYH` | **通过** | WORKSPACE_READY | — | `fresh-start` | 07:32 |

**状态流转**: ASSIGNED → PROVISIONING → FAILED → PROVISIONING → FAILED → PROVISIONING → FAILED → ASSIGNED（重置）→ PROVISIONING → READY → IN_PROGRESS

**失败记录**:
- 失败 #6: `RUNTIME_CLIENT_UNAVAILABLE`，阶段 QUOTA_CHECK（job `01M4CKPDR95FRHMG3PTA9JPMDP`）
- 失败 #2275: `RUNTIME_NETWORK_CREATE_FAILED`，阶段 QUOTA_CHECK（job `01M4CKZKPF0Y5YFQESZYYMM0E4`）
- 失败 #2282: `RUNTIME_IMAGE_QUERY_FAILED`，阶段 IMAGE_PREPARE（job `01M4D2T0X24MHV6NNAXWF1TA62`）

**最终 Session**: Session #4 `01M4D911ADZPTWBD6RCDYH6T7T` — 状态 ACTIVE，08:10 进入，过期时间 2026-10-09 09:38

#### 任务 8 — `01M3R4MYZPZSCTY9TE4RC4E27T`

| 次数 | Job ID | 状态 | 失败阶段 | 错误码 | Trace ID | 时间 (UTC) |
|------|--------|------|----------|--------|----------|------------|
| 1 | `01M4CKPDKKW9GTQ521MGC3VEBE` | 失败 | QUOTA_CHECK | RUNTIME_CLIENT_UNAVAILABLE | `manual-fix` | 01:57–02:00 |
| 2 | `01M4CKZKJ4VCNYXAM7KNFBZ92X` | 失败 | IMAGE_PREPARE | RUNTIME_IMAGE_QUERY_FAILED | `retry-fix` | 02:02 |
| 3 | `01M4D2T0RV9Q7KKDR79FJX6M71` | **通过** | WORKSPACE_READY | — | `retry-after-build` | 07:34 |

**状态流转**: ASSIGNED → PROVISIONING → FAILED → PROVISIONING → FAILED → PROVISIONING → READY → IN_PROGRESS

**失败记录**:
- 失败 #5: `RUNTIME_CLIENT_UNAVAILABLE`，阶段 QUOTA_CHECK（job `01M4CKPDKKW9GTQ521MGC3VEBE`）
- 失败 #2276: `RUNTIME_IMAGE_QUERY_FAILED`，阶段 IMAGE_PREPARE（job `01M4CKZKJ4VCNYXAM7KNFBZ92X`）

**最终 Session**: Session #5 `01M4DB269105Y2FX2DPNPFGTB3` — 状态 ACTIVE，08:46 进入，过期时间 2026-10-09 09:32

#### Celery 异常

Celery 任务 `523fbeef-e8be-40cf-b557-87467eb140b4` 在 07:34:13 UTC 抛出 `ProvisioningJob.DoesNotExist` —— worker 尝试处理时，对应的 job 记录已经不存在了。这是补偿/清理逻辑和重试派发之间的竞态条件。

---

### 二、运行时对账失败

10 月 8 日 02:01 和 03:00 UTC，治理对账扫描发现 6 条 `RUNTIME_EXTERNALLY_ABSENT` —— 数据库记录显示容器处于活跃状态，但 Docker 中实际找不到对应容器：

| 失败 ID | 实例 | 关联任务 | 时间 |
|---------|------|----------|------|
| #2272 | `01M3JVDRJNBCB7108SEYJ985S4` | 任务 1 (`01M3JVDFNPS3796A8GDRV9HE86`) | 02:01 |
| #2273 | `01M3JVDW6TEZQF719PAN1TPWAP` | 任务 2 (`01M3JVDW4ZDP13AHBYYMAAG3RB`) | 02:01 |
| #2274 | `01M3R4MDJ54RY12VX5Q43G4Y1P` | 任务 6 (`01M3R4KXQNWQ2HD3CDAVJHDGSD`) | 02:01 |
| #2278 | `01M3JVDRJNBCB7108SEYJ985S4` | 任务 1（重复扫描） | 03:00 |
| #2279 | `01M3JVDW6TEZQF719PAN1TPWAP` | 任务 2（重复扫描） | 03:00 |
| #2280 | `01M3JVDW6TEZQF719PAN1TPWAP` | 任务 2（重复扫描） | 03:00 |

这些是旧种子数据（任务 1、2、6）的残留，P09→P15 迁移时容器已被销毁，但数据库记录仍显示活跃。

---

### 三、待修复代码点（已确认）

**A 点 — `crypto.randomUUID()` 在 HTTP 环境下不可用**
文件: `/opt/agent2/frontend/packages/api-client/src/index.ts:302`
```typescript
constructor(key: string = crypto.randomUUID()) {
  this.key = key
}
```
问题: `crypto.randomUUID()` 要求安全上下文（HTTPS 或 localhost）。测试服务器运行在 `http://47.114.58.170:8080`，使用浏览器不信任的自签名证书 —— 这不是安全上下文。任何浏览器走到这段代码都会抛出 `TypeError: crypto.randomUUID is not a function`。

**B 点 — p08.tsx 根据本地缓存状态做路由分流**
文件: `/opt/agent2/frontend/apps/user-web/src/p08.tsx:264`
```typescript
mutationFn: async (item: TaskData) => {
  intent.current ??= new RequestIntent()
  if (item.status === 'READY') return enterWorkspace(taskId, `"${item.row_version}"`, intent.current)
  return createWorkspaceSession(taskId, intent.current)
},
```
问题: 根据本地缓存的 `item.status` 决定调用 `enterWorkspace` 还是 `createWorkspaceSession`。如果本地缓存过期了（比如服务端已有 active session 但本地仍显示 READY），就会走错分支。

**C 点 — p08.tsx 对 409 只弹提示，不自动恢复**
文件: `/opt/agent2/frontend/apps/user-web/src/p08.tsx:182`
```typescript
if (error.status === 409) return '工作区状态已变化，请刷新后重试。'
```
问题: 收到 409（STATE_CONFLICT）时，前端只显示错误文案。应该自动刷新任务状态并尝试恢复 —— 先 GET 查询已有 session，如果存在则直接进入，而不是让用户手动刷新。

---

### 四、浏览器复现证据与剩余缺口

| 证据类型 | 状态 | 说明 |
|----------|------|------|
| nginx 中的 409 响应 | **已观测** | 浏览器收到 `STATE_CONFLICT`，`detail.status=ASSIGNED`，`trace_id=fcc7646032a5e413d46015fe163810ea` |
| 浏览器 Console/Network 抓包 | **部分满足** | 已获得 `crypto.randomUUID` TypeError 和接口错误响应；仍需保存完整请求头、响应头、Initiator 和原始 HAR |
| crypto.randomUUID 崩溃 | **已触发** | HTTP 页面控制台报 `crypto.randomUUID is not a function`；实际页面为 `http://47.114.58.170:8080`，前端加载 `assets/index-BDcIwFxi.js` |
| Idempotency-Key 缺失 | **已观测** | `/workspace-sessions` 返回 `428 IDEMPOTENCY_KEY_REQUIRED`，`trace_id=be9c02d65c9cf4dbf397e8813d7d93b8` |
| 409 恢复流程 | **未完成验证** | 已触发 `STATE_CONFLICT`，但当前服务端状态为 `ASSIGNED`，尚未形成 READY/IN_PROGRESS 与服务端状态不一致的对照 |

浏览器端页面同时显示 `v0.15.0-p15`、`API v2-p15` 和提交号
`071f03de47a2ccd52098ef130eae565d3dffe3d1`。任务 7、8 的详情页均显示历史
`PROVISIONING → READY → IN_PROGRESS`，但当前页面任务状态为 `ASSIGNED`；该现象应作为状态一致性证据保留，不能直接等同于 Active Session 或 409 恢复缺陷。

---

### 五、第一阶段出口标准评估

| 标准 | 是否满足 | 证据 |
|------|----------|------|
| 失败案例的 task_id | **已满足** | 任务 7 和 8 均经历了多阶段 provisioning 失败 |
| provisioning job_id | **已满足** | 6 个失败 job 均已记录 ID |
| session_id | **已满足** | 恢复后创建了 Session #4 和 #5；Session #3 已撤销 |
| trace_id | **已满足** | `manual-fix`、`retry-fix`、`retry-after-build`、`fresh-start` |
| 任务详情 | **已满足** | ExperimentTask 全字段已采集 |
| Provisioning Job 详情 | **待核对** | 当前正文表格列出任务 7 的 4 个 Job、任务 8 的 3 个 Job，共 7 个；“全部 10 个 job”的表述需要补齐清单或修正数量 |
| 状态流水 | **已满足** | 38 条 TaskStateTransition 记录覆盖完整生命周期 |
| Session 请求/响应 | **基本满足** | 已有服务端 Session 记录和浏览器错误响应；仍缺完整请求头、响应头及 HAR/Network 原始证据 |
| Git 提交号 | **已满足** | `071f03de` |

**结论**: 第一阶段基线在 provisioning 失败路径上已基本完整，浏览器端已补充
`crypto.randomUUID`、`428 IDEMPOTENCY_KEY_REQUIRED` 和 `STATE_CONFLICT` 证据。
正式关闭第一阶段前仍需补齐完整 Session 请求/响应原始记录、7/10 个 Job 数量不一致，
以及 READY/IN_PROGRESS 状态竞争场景的前后状态对照。

---

### 六、建议后续步骤

1. **补齐浏览器原始证据**: 保存 `/enter` 或 `/workspace-sessions` 的完整请求头、响应头、Initiator 和 HAR；特别核对 `Idempotency-Key`、`If-Match` 和 `X-Request-ID`。

2. **第二阶段（UUID 修复）**: 在 `RequestIntent` 构造函数中添加降级方案:
   ```typescript
    constructor(key: string = createUuid()) {
   ```

3. **第三阶段（409 恢复）**: 在 p08.tsx 中，收到 409 时先自动 GET 查询已有 session，再决定是否显示错误。

4. **第四阶段（本地状态路由）**: 将 `item.status === 'READY'` 的判断改为查询服务端 session 状态，避免本地缓存过期导致走错分支。
