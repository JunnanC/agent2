# 课程申请流程 Checklist

- [x] 未形成有效选课的课程不能通过课程详情接口进入；待审核课程不能进入，公开课程即时加入后可进入。
- [x] 邀请码解析成功后直接提交关联课程申请。
- [x] 邀请码无效时不发送申请命令。
- [x] 课程详情显示已加入状态，不显示申请拦截提示。
- [x] 前端类型检查、构建和后端语法检查通过：`npm run typecheck`、`npm run build:student`、`python -m compileall -q backend/apps/courses/views.py backend/apps/courses/urls.py` 和 `git diff --check` 通过。
- [ ] 使用真实教师邀请码完成浏览器端到端验证。

后端 Django API 测试未能启动：当前 Python 环境缺少 `prometheus_client`，因此未执行数据库级接口验证。
