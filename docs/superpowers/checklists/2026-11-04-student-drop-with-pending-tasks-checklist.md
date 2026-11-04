# 学生有待办时退课 Checklist

- [x] 真实未完成任务存在时退课检查和提交均成功（API 测试覆盖 ASSIGNED、PROVISIONING、IN_PROGRESS、UNDER_REVIEW 检查以及带任务提交、幂等重放）。
- [x] 退出后当前列表无原待办，课程学习权限被拒绝，任务与历史记录仍保留（真实任务 API 测试）。
- [x] 非有效选课、其他阻塞仍拒绝；默认退出检查仍返回未完成任务阻塞，教师移除保留默认规则；旧版本提交返回 412 ROW_VERSION_CONFLICT（服务/API 测试）。
- [x] 弹窗说明带待办可退课，正常提交并刷新缓存（Vitest）。
- [x] 相关后端测试、前端测试、类型检查、lint、构建通过。
- [x] 本地 Django 服务同步代码并重启，manage.py check 通过、容器 healthy，/api/v2/health 返回 status=ok。

## 验证记录
- Docker 内从 /workspace/backend 运行 Django test，测试设置使用独立内存 SQLite：courses 的 test_services/test_api 与 experiments 的 test_services/test_api，共 46 项通过。
- Vitest：student-api-ui.test.tsx、courses.test.tsx、home.test.tsx，共 17 项通过。
- 学生端 TypeScript 检查、变更前端文件 ESLint、学生端生产构建通过。
- 变更后端文件 Ruff 与 git diff --check 通过。顺带补齐 courses/views.py 已有的 Course 引用导入并换行超长条件。

验证为自动化页面及 API 测试，未操作真实学生选课数据。任务记录和资源回收生命周期保持原样。
