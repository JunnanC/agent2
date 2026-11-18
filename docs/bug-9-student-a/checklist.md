# 学生端 A Checklist

- [x] AC1 材料预览/下载独立且受控（验证：组件测试）。
- [x] AC2 附件报告无正文输入，教师附件可下载，扫描仍阻止未安全附件提交（验证：页面与后端测试）。
- [x] AC3 题目列表切换先保存、样例与自测输出分区（验证：assessment 测试）。
- [x] AC4 两列独立滚动，活动章节同步，窄屏自然滚动（验证：课程测试和浏览器）。
- [x] AC5 学号与旧标识登录、重复/非法批次逐行错误、权限和课程名单导入（验证：后端服务与 API 测试）。
- [x] 集成：共享客户端类型与 OpenAPI 一致（验证：生成 API 和 typecheck）。
- [x] 前端 typecheck、相关测试、build 通过（验证：npm scripts）。
- [x] 后端迁移未遗漏、相关测试与 lint 通过（验证：Django/pytest/ruff）。
- [x] 端到端：管理员创建学生 → 学号登录 → 教师学号导入课程（验证：集成测试）。
- [ ] 端到端：学生进课程 → 预览/下载 → 编程自测 → 附件交卷（验证：浏览器或集成测试；注明 mock/真实环境）。

## 实际证据
- 后端命令（backend 目录）：`..\.venv\Scripts\python.exe -m pytest apps/accounts/tests apps/courses/tests/test_student_number_import.py apps/courses/tests/test_content_services.py apps/experiments/tests/test_assessment.py apps/experiments/tests/test_assessment_acceptance.py apps/core/tests/test_file_preview.py apps/reports -q` → **61 passed**。
- `manage.py makemigrations --check --dry-run --settings=education_experiment_platform.settings.test` → **No changes detected**；SQLite 测试数据库实际应用了迁移。
- 后端改动范围 `ruff check` → **All checks passed**。
- OpenAPI 导出成功、0 errors；存在主干已有的教学任务 operationId 重名 warning；`npm run generate:api` 已生成类型。
- 前端 `npm run typecheck`、生产构建与全部 Vitest 测试结果见下方最终记录；改动组件/页面/API 的 ESLint 成功。
- Ego Browser 使用本地 React fixture（真实组件、模拟 API），验证 24 章节双列独立滚动、活动章节同步、1440/768/390px 无横向溢出、两题切换、自定义输入运行、标准输出与错误区、无正文输入，以及材料双入口。截图在本机 `.tmp/course-*.png` 和 `.tmp/assessment-final-*.png`，未提交。
- 真实服务的 MinIO 上传、ClamAV 扫描、运行容器和完整附件交卷未做环境联调，最后一项保留未勾选；并未在实际业务数据库执行 migrate。
- Windows 本地测试使用 Python 3.14.5 和锁定依赖，跳过 SQLite 测试不需要的 mysqlclient；未修改项目依赖文件。

## 最终自动化结果

- `npm test -- --maxWorkers=2`：**44 files passed, 147 tests passed**。
- 一次默认高并发重跑出现两个未改动教师端用例等待模拟数据超时；限制为 2 workers 后全量通过，未修改教师端业务或测试来绕过失败。
- `npm run typecheck`：通过（三门户和共享包）；新增管理端测试的可空访问已修正后复验。
- `npm run build` 的学生/教师构建通过；最终学生端 `npm run build:student` 和管理端 `npm run build:admin` 均通过。构建保留既有编辑器大 chunk 提示。
- 最终改动范围 ESLint：退出码 0；`git diff --check`：通过。
- 自动化及本地模拟浏览器验收 **9/10**，唯一未勾选项为真实部署环境完整附件流程。
