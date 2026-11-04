# 管理端界面与接口边界

管理端按 `prototypes/admin/index.html` 的七页结构组织：运行概览、课程与班级、学生管理、教师管理、镜像管理、服务与资源、操作日志。使用 React、现有会话认证与请求客户端，不运行 HTML 原型内的脚本，也不读取演示数据。

## 已接入

| 页面 | 接口及行为 |
| --- | --- |
| 运行概览 | 从账号、资格、课程、实例计算统计；运行时资源快照及近期审计 |
| 课程与班级 | `/platform/courses`，名称、唯一 ID、教师、成员人数及教学时间 |
| 学生 / 教师 | `/platform/users`、`teacher-qualifications`、`admin-assignments`；按用户 ID 关联，禁用恢复 PATCH 携带原因和 If-Match |
| 镜像 | `/platform/images` 登记地址与版本；详情、摘要解析；`decide` 使用 APPROVED / RETIRED 启停，未就绪镜像禁止启用 |
| 服务与资源 | `/platform/runtime-adapters`、`instances`、`operations/overview`；只读资源、健康和告警 |
| 操作日志 | `/platform/operations/audit`，搜索、操作筛选、北京时间范围及详情 |

账号列表接口没有直接的注册角色字段。当前用教师资格记录识别教师，排除管理员后将其余账号归入学生列表；教师资格状态不代替账号状态，也不向管理员暴露资格审批操作。所有列表完整读取服务端分页，再做角色关联和本地筛选，避免仅统计第一页。

写操作成功后重新读取实际数据；失败不修改本地状态。412 要求刷新数据后重试。近期认证要求沿用原密码验证流程，原生业务弹窗会先关闭，防止挡住验证窗口。

## 尚需后端提供

- 课程下架：现有 freeze 仅为返回 501 的占位接口，因此按钮禁用并显示说明。
- 管理端查询学生课程关系、课程成员名单和实验安排；不调用教师门户接口越权代查。
- 镜像独立显示名称、用途说明和基本配置编辑；当前名称取仓库路径末段，不将登记原因伪装为用途。
- 镜像的课程引用关系，学生及教师注册时间。
- 数据库、缓存、队列的独立健康检查；磁盘占用、节点 CPU 历史采样和实例级 CPU / 内存占用。运行时资源容量占用不能作为主机实时 CPU 负载。
- 审计接口的原因、变更前后字段。现接口仅返回摘要与 Trace ID。

前端显示缺失说明或禁用动作，不保存浏览器本地假状态。教师自主注册的后端资格授予规则及课程下架后的访问规则不在此次前端变更中修改。

## 检查

在 `frontend/` 执行：

```powershell
npm run build:admin
npx vitest run apps/admin-web/src
npx eslint apps/admin-web/src/console apps/admin-web/src/App.tsx apps/admin-web/src/app/App.tsx apps/admin-web/src/main.tsx apps/admin-web/src/pages/login.tsx e2e/admin-console.spec.ts e2e/admin-smoke.spec.ts
```

独立浏览器验证：先在 `frontend/apps/admin-web/` 运行 `npx vite --config vite.config.ts --port 5186 --strictPort`，再于 `frontend/` 执行 `npx playwright test e2e/admin-console.spec.ts --project admin-web`。场景使用受控 API fixture，检查真实 React 页面和请求载荷，不代替真实环境联调。

设计方法参考 unslop，作者 Damir Sokolovsky（[@heydamir](https://x.com/heydamir)），[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。灰白工作区、深青资源条、等宽课程 ID、统一线性图标；不加入生成图片或装饰动画。
