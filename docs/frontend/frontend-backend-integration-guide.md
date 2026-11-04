# 前端开发与联调

> 核对日期：2026-11-04。依据当前三端源码、共享包、Vite 配置和 npm scripts。返回[文档索引](../README.md)。

## 一、应用与共享代码

| 位置 | 当前内容 |
| --- | --- |
| [student-web](../../frontend/apps/student-web/src/app/App.tsx) | 首页、课程与加入课程、实验详情、全屏工作台、通知和个人资料 |
| [teacher-web](../../frontend/apps/teacher-web/src/app/App.tsx) | 课程、选课审核、模板编辑、实验发布、学生、成果审核与教学分析 |
| [admin-web](../../frontend/apps/admin-web/src/app/App.tsx) | 管理控制台、账号、运行治理、资源、镜像、事件、审计与 Agent |
| `packages/auth-client` | Session/CSRF 请求、错误分类、幂等和版本头 |
| `packages/api-client` | API 调用、业务类型及生成的 OpenAPI 类型 |
| `packages/query-keys`、`event-client`、`ui` | 查询缓存键、SSE、共享组件与样式 |

仓库使用 React 18、TypeScript、Vite、React Router 和 TanStack Query；具体版本以 [package.json](../../frontend/package.json)和锁文件为准。当前页面按业务命名，不从旧静态原型或编号页面推断路由。

## 二、本地启动

先按[根 README](../../README.md)启动 8080 后端入口。Docker 热更新方式从仓库根目录执行：

```powershell
.\scripts\frontend-dev-up.ps1 -SkipBackend
```

学生、教师、管理入口分别为 `http://student.localhost:5173`、`http://teacher.localhost:5174`、`http://admin.localhost:5176`。源码以只读卷挂载，依赖卷单独管理。

已有标准 Compose 后端时使用 `-SkipBackend`；省略该参数会按 `.env` 选择的 Compose 配置和 `runtime` profile 构建并启动标准后端。脚本的端口检查要求与实际映射一致；不要仅修改访问 URL。

主机安装 Node.js 24 时，也可在 `frontend/` 执行 `npm ci --ignore-scripts`，分别运行 `npm run dev:student`、`npm run dev:teacher`、`npm run dev:admin`。主机模式的管理端端口以该应用的 dev script 为准，不等同于 Docker 的 5176 映射。

Vite 代理 `/api`、`/files`、`/workspace`，按对应门户 Host 和后端 Origin 转发；工作区启用 WebSocket。后端目标由 `VITE_DEV_API_TARGET` 指定，Docker 开发配置使用 `host.docker.internal:8080`。

## 三、请求与权限

- 通过 `@edu/auth-client` 和 `@edu/api-client` 访问 `/api/v2`，Session 请求使用 `credentials: "include"`。首次写入前获取 `/auth/csrf`，写请求发送 `X-CSRFToken`。
- 业务重试复用幂等键；需要版本控制的修改携带当前资源版本。412 时保留用户输入，重新获取并解决冲突，不能静默覆盖。
- 页面资格和按钮状态辅助交互，后端仍负责授权。会话失效时清理查询缓存并跳转登录。
- 学生工作台查询聚合接口，不自行拼装隐藏测试或内部执行命令；工作区访问通过服务端下发的受控会话。
- 错误形状、分页与接口修改流程见[数据与接口](../架构设计/数据与接口.md)。

## 四、状态、工作台与 UI

- 服务端数据统一进入查询缓存；SSE 触发相应刷新。断线、游标失效或 resync 后重新查询 REST，不能只根据事件修改业务事实。
- 当前 Nginx 只放行学生端 SSE；教师端、管理端事件流被入口配置拒绝，不能把共享客户端存在写成三端实时更新已打通。
- 学生工作台位于 `/experiments/:taskId/workbench`，采用全屏布局；代码入口是[workbench.tsx](../../frontend/apps/student-web/src/pages/workbench.tsx)。
- 保存、恢复、语言切换、运行测试和完成提交均依据后端状态启用。运行中、失败和版本冲突需要明确反馈，保留尚未保存的编辑。
- 优先复用 `@edu/ui` 及[共享样式](../../frontend/packages/ui/src/styles.css)。旧静态原型的页面、色值和布局不再作为当前规范。
- 修改页面时检查加载、空态、错误、无权限、窄屏与键盘操作；不要另建一套重复组件或状态映射。

## 五、验证命令

在 `frontend/` 执行：

```powershell
npm run typecheck
npm run lint
npm test
npm run build
npx tsc -p e2e/tsconfig.json --noEmit
```

当前五份浏览器用例为 `admin-smoke`、`teacher-smoke`、`student-workbench`、`analytics-notifications` 和 `real-workspace`。执行配置见 [playwright.config.ts](../../frontend/playwright.config.ts)。

浏览器测试需要可访问服务和对应数据；部分冒烟用例在缺少账号环境变量时会跳过。真实工作区流程需要任务、登录凭据及运行时，优先使用[集成脚本](../../scripts/verify/real-workspace-integration.ps1)。用例存在、类型检查通过或部分跳过都不等于完整业务验收。

## 六、构建与契约更新

三个应用分别构建到 `frontend/dist/student-web`、`teacher-web`、`admin-web`，部署时由 [Nginx 镜像](../../infrastructure/nginx/Dockerfile)统一提供。

后端接口修改后，从仓库根目录运行 `./scripts/dev/export-openapi.ps1`，再检查 API 客户端和页面调用。不要手改生成的 `schema.d.ts`，也不单独维护一份手写全量 API 目录。

## 七、共享资源类型

[types.ts](../../frontend/packages/api-client/src/types.ts)表达前端业务资源类型，[生成类型](../../frontend/packages/api-client/src/generated/schema.d.ts)来自 OpenAPI；两者都需要与当前 serializer 保持一致。资源标识、任务与审核状态、运行证据和工具链字段以当前实现为准，页面不能自行扩展后端枚举或假定所有列表响应相同。
