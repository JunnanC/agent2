# 课程章节定位 Checklist

- [x] 全部章节连续渲染，导航点击调用对应章节的平滑滚动（代码检查）。
- [x] 导航固定布局与章节空状态保留（代码检查）。
- [x] 学生端类型检查、构建通过：`npx tsc -p apps/student-web --noEmit`、`npm run build:student` 均退出 0；`git diff --check` 通过。
- [ ] 浏览器场景：点击第 2 章滚动定位，再向上查看第 1 章。
