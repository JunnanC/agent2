# 学生选课状态操作 Tasks

1. 修改 enrollment-exit.tsx：补齐成功回调、context 缓存失效及结果提示；验证组件退出与撤回测试。
2. 修改 courses.tsx、join-courses.tsx：提供待审核撤回和已加入退出入口，按当前选课周期匹配记录；验证页面测试。
3. 修改 course-detail.tsx：权限校验完成后启用内容查询，提供详情退出操作；验证未授权不读取内容、退出导航测试。
4. 增加课程 API 生命周期测试：申请、禁止进入、撤回、重新申请、审批、退出、再次禁止进入。
5. 运行相关 Vitest、TypeScript 检查、学生构建、Django 课程测试与 diff 检查，记录实际结果。
