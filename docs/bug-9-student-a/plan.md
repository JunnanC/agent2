# 学生端 A Plan

## 架构概览
沿用 React/TypeScript 门户和 Django/DRF 后端。学生组件调用 api-client，通过受控文件 grant 预览/下载。报告沿用附件资产和扫描提交校验。账号新增可空唯一 student_number，导入复用创建账号事务与审计；课程名单预检增加 student_number 列匹配。

## 核心数据结构与接口
- User.student_number: varchar(32), unique, null，统一 strip/casefold，旧数据为 null。
- POST /api/v2/platform/student-imports: {csv: string}，CSV 表头 student_number,email,display_name,password；username 使用学号，逐行事务；响应 data.rows=[{row_number,student_number,status,user_id?,error?}]；最大500行，受平台权限与幂等保护。
- 课程现有 enrollment-imports/precheck 接口 CSV 增加 student_number，保留 username；两列同时提供则必须指向同一账号，错误逐行反馈；B 沿用现有预检/确认任务接口。
- 文件动作组件: assetId/title，preview 使用新窗口，download 使用受控路径导航；独立忙状态/失败提示。

## 模块设计及覆盖
- 文件组件和章节资源：F1、教师附件下载 F2。
- assessment 页面：F2 附件报告、F3 题目导航与自测分区；原 flushAll、幂等和扫描协议保持。
- course-detail 与 CSS：F4 内容容器监听与响应式滚动。
- accounts 模型、导入服务/视图、登录 selector、迁移、管理 UI 与共享客户端：F5。
- courses 名单预检：F5，通过 accounts 查询已创建学生，不创建账号。

## 模块交互
管理员 CSV → 平台权限/幂等 → 逐行校验/事务创建 → 结果；学号登录 → selector → 现有口令及 Portal 校验；教师 CSV → 课程权限 → 预检 → 原确认任务。

## 文件组织
学生组件 chapter-resources.tsx、asset-actions.tsx；pages/assessment.tsx、course-detail.tsx、styles.css；accounts/student_imports.py、student_import_views.py、models.py、selectors.py、migrations；courses/content_services.py；api-client/index.ts、types.ts；admin console；对应测试与本目录契约文档。

## 技术决策
选择扩展现有闭环（推荐），避免另建门户和认证系统；单纯把学号当用户名不能存储独立字段，另建学校组织模型又超出范围。全站唯一与当前单平台账号空间一致。必填邮箱和显式初始密码沿用既有安全规则。独立文件操作组件复用授权与错误提示。
