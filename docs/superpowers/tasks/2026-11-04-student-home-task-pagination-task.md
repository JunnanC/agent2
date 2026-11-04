# 首页待完成任务分页 Tasks

## T1：分页展示
- 文件：frontend/apps/student-web/src/pages/home.tsx。
- 添加日期关联的分页状态、页数计算与任务切片。
- 添加仅多页时显示的导航，禁用首尾按钮，保留完整总数和任务入口。
- 验证：学生端 TypeScript 检查与构建通过。

## T2：交互验收（依赖 T1）
- 文件：frontend/apps/student-web/src/pages/home.test.tsx。
- 验证多页浏览和导航、切换日期、任务减少、少量任务与空状态。
- 验证：运行 home.test.tsx，全部通过；运行本次文件 lint。
