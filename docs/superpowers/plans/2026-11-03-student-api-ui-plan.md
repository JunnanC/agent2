# 用户端新版接口页面接入 Plan

1. 从 frontend/openapi.json 更新生成类型；后端弱类型课表、Agent 响应按实际序列化定义，保留现有客户端。
2. 新建 LearningHistory 与 EnrollmentExit 组件，在我的课程页使用；弹窗按最新 enrollment.row_version 提交 drop/withdraw，失败刷新预检。
3. CourseAgent 组件复用于课程详情和任务详情：按服务端 modes 选模式，保存会话至 React Query，在 QUEUED/RUNNING 回复或工具执行期间轮询，离开页面停止轮询。
4. 扩展课表面板的字段和行错误显示；评审结果使用 rounds 与 allowed_actions，支持退回状态。
5. API 测试覆盖头、路径及异步响应；组件测试覆盖阻塞退课、异步回复及课表映射确认。
