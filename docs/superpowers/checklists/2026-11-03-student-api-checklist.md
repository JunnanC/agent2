# 用户端接口接入 Checklist

- [x] 新用户接口路径、请求体、data 解包和并发头通过契约测试。
- [x] 课表文件上传保留文件内容，映射、确认和异步状态可查询。
- [x] 通知按真实字段显示，标记已读携带 row_version 和幂等键。
- [x] 课程资源、问答和通知偏好有真实页面调用及失败处理。
- [x] 学生和教师共享调用方类型检查及构建通过，相关测试通过。
- [ ] 真实后端端到端：导入课表→映射→确认→课表更新（需运行服务和有效登录会话，本次未执行）。

验证记录：`npm run typecheck`、`npm run build:student`、`npm run build:teacher` 均通过；`npx vitest run packages/api-client/src/index.test.ts packages/api-client/src/student-contract.test.ts packages/auth-client/src/index.test.ts` 为 17/17 通过；`git diff --check` 通过。全仓 `npm test` 未执行；真实后端端到端留待联调环境。
