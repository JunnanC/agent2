# 三端 React UI 工程

采用 React 18 + TypeScript + Vite，使用 npm workspaces 管理三个独立应用。当前管理端完成 UI 迁移，学生端与教师端是可启动、可构建的预留入口。

```text
frontend/
├─ apps/
│  ├─ admin-web/src/
│  │  ├─ App.tsx          # 管理壳层、导航、页面切换
│  │  ├─ pages.tsx        # 五个管理页面
│  │  ├─ components.tsx   # 表格、指标、标签和详情弹窗
│  │  ├─ data.ts          # 类型、演示数据、筛选与 CSV
│  │  └─ styles.css       # 继承管理端原型样式
│  ├─ student-web/src/    # 学生端 UI 放在这里
│  └─ teacher-web/src/    # 教师端 UI 放在这里
├─ packages/             # 有实际复用需求时提取共享包
└─ dist/                 # 构建后生成三个站点
```

## 开发

要求 Node.js 24 LTS、npm 11。在 `frontend` 目录执行：

```powershell
npm ci
npm run dev:admin
```

管理端地址：`http://127.0.0.1:5175`。页面采用 hash 导航，刷新和前进/后退均可保留页面位置，例如 `/#audit`。

```powershell
npm run dev:student   # 127.0.0.1:5173
npm run dev:teacher   # 127.0.0.1:5174
npm run typecheck
npm test
npm run build
```

`dev:user`、`build:user` 是学生端命令的兼容别名。三个应用在一次 `npm ci` 后可独立开发。学生端使用 `student-web` 目录，与当前 Nginx 构建目标一致；旧历史中的 `user-web` 目录不应再次建立平行实现。

## 功能与数据

管理端保留平台概览、治理待办、运行资源、异常中心和操作审计。支持搜索与状态联合筛选、时间筛选、资源标签切换、详情查看、移动导航及筛选结果 CSV 导出。原 HTML 原型保留在 `outputs/admin-frontend-design/index.html` 供视觉对照。

本次交付是 UI 工程化，尚未实现登录、权限和真实 API 请求。`data.ts` 中所有记录和指标均为演示内容，演示日期基准固定为 2026-10-15；服务健康也不是实时检测结果。后续联调需根据当前 schema 明确响应类型，替换演示数据源，再加入加载、错误、登录和权限状态，不能把缺失数据回退成演示值。

## 接入与部署边界

- 正式接入时从管理端同源请求 `/api/v2`，遵循 `docs/frontend/frontend-backend-integration-guide.md` 的 Cookie/CSRF、权限、ETag、幂等约定。
- `npm run build` 分别输出 `dist/admin-web`、`dist/student-web`、`dist/teacher-web`，匹配现有 `infrastructure/nginx/Dockerfile` 的 COPY 目标。后两者当前只输出“UI 待接入”页面，不能视为业务完成。
- 未修改后端、网关、Compose 配置，未恢复历史业务功能或旧验收脚本依赖的全部共享包。旧 `verify-pXX` 全项目验收仍需在业务接入后重新适配验证。
- 现有 Nginx 在管理端显式禁止 `/api/v2/events/stream`，若将来管理端要用 SSE，需要部署方确认并调整该规则；本次不启用 SSE。
- 两端接入方法分别见 `apps/student-web/README.md`、`apps/teacher-web/README.md`。
