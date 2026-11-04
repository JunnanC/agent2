# 首页待完成任务分页 Checklist

- [x] 9 项任务分页为 4、4、1，完整总数保持 9，首尾按钮禁用（页面交互测试通过）。
- [x] 分页后的任务点击进入正确详情或工作台（路由交互测试通过）。
- [x] 日期切换回到第一页；少量任务隐藏分页，空日期显示空状态（页面交互测试通过）。
- [x] 数据刷新减少任务时使用有效页码（查询缓存刷新测试通过）。
- [x] 学生端类型检查、构建和变更文件 lint 通过（下列命令均退出 0）。

## 验证记录
- `npx vitest run apps/student-web/src/pages/home.test.tsx`：1 个文件、7 项测试通过。
- `npx tsc -p apps/student-web --noEmit`：通过。
- `npx eslint apps/student-web/src/pages/home.tsx apps/student-web/src/pages/home.test.tsx --max-warnings=0`：通过。
- `npm run build:student`：通过。
- `git diff --check`：通过。

以上为自动化页面交互验证，未进行浏览器视觉验收。
