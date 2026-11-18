# 学生端 A Tasks

## 文件清单
| 操作 | 文件 | 职责 |
| --- | --- | --- |
| 新建 | docs/bug-9-student-a/{spec,plan,task,checklist,contract}.md | 需求/设计/验收/交接 |
| 修改/新建 | frontend/apps/student-web/src/components/{chapter-resources,asset-actions}.tsx | 授权预览下载 |
| 修改 | frontend/apps/student-web/src/pages/{assessment,course-detail}.tsx、src/styles.css | 报告/自测/滚动 |
| 修改/新建 | backend/apps/accounts/{models,selectors,student_imports,student_import_views,urls}.py、migrations | 学号与批量账号 |
| 修改 | backend/apps/courses/content_services.py | 按学号预检 |
| 修改 | frontend/packages/api-client/src、frontend/apps/admin-web/src/console | 批量导入入口 |
| 修改/新建 | 对应前后端测试 | 行为验证 |

## T1 契约（无依赖）
写明 CSV 字段、唯一性、口令策略与逐行响应示例。验证：契约覆盖 F5 全部边界。
## T2 材料动作（依赖 T1）
封装受控预览与下载，接入章节材料。验证：授权错误与双操作前端测试。
## T3 编程导航（依赖 T2）
改为可点击列表，保留切换前保存；样例与运行输出分区。验证：assessment 页面测试。
## T4 附件报告（依赖 T3）
移除正文编辑并接入教师附件下载，保留草稿版本、扫描与旧历史。验证：相关前后端报告测试。
## T5 滚动（依赖 T4）
桌面内容容器与导航各自滚动，窄屏自然滚动，适配活动章节追踪。验证：课程页测试与浏览器检查。
## T6 学号模型（依赖 T1）
加迁移，兼容旧登录，排除标识冲突。验证：迁移检查与登录测试。
## T7 批量账号（依赖 T6）
实现逐行验证/事务、平台权限/幂等、导入结果。验证：混合成功、重复与越权测试。
## T8 课程名单（依赖 T7）
扩展现有 CSV 预检按学号匹配，校验双列一致。验证：课程导入测试。
## T9 管理端接入（依赖 T7）
共享 API、管理端 CSV 输入与结果反馈、学生登录文案、生成 OpenAPI。验证：typecheck 和构建。
## T10 综合验收（依赖 T2-T9）
运行相关测试、lint、迁移检查、构建、浏览器场景，更新 checklist 证据并提交。验证：记录命令实际结果，未执行项不标通过。

执行顺序：T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10。每组相关任务验证后本地提交，不自动推送。

## 执行记录

- T1–T9 已实现并完成对应自动化验证。
- T10 自动化与本地浏览器验收已完成；真实存储/扫描/容器的部署环境端到端验收待联调，见 checklist.md。
- 实际新增文件：accounts/student_imports.py、student_import_views.py、0003_user_student_number.py；core/tests/test_file_preview.py；courses/tests/test_student_number_import.py；学生 asset-actions.tsx 及测试；管理端 console/StudentImport.tsx 及测试。
- 现有前端设计沿用原门户字体、颜色与组件，仅调整材料动作、样例、输出、代码区与滚动容器；未另建视觉主题。
