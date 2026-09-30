# P15-E Agent 悬浮助手

## 一、目标

在用户工作台中增加小圆球入口和可关闭的 Agent 抽屉，让用户在不离开实验环境的情况下获得当前任务范围内的解释和排错帮助。

## 二、会话

复用现有接口：

```text
POST /api/v2/tasks/{task_id}/agent-sessions
mode = WORKSPACE_ASSIST
POST /api/v2/agent-sessions/{session_id}/messages
GET  /api/v2/agent-sessions/{session_id}/messages
```

打开抽屉时可以懒创建会话，但只能在当前任务和当前学生范围内创建。

## 三、交互

圆球要求：

- 使用熟悉图标，不放大段说明文字。
- 有明确 `aria-label` 和 tooltip。
- 显示未读或处理中状态，但不展示 token 或内部 ID。
- 不遮挡底部测试/提交按钮。

抽屉内容：

- 消息时间线。
- 输入框。
- 引用来源。
- 异步处理中状态。
- 有帮助/需改进反馈。
- 工具审批状态。

可提供快捷问题：

- 解释当前步骤。
- 分析最近一次测试失败。
- 查看当前草稿问题。
- 给出下一步排查建议。

## 四、安全边界

Agent 不得自动执行：

- 提交实验。
- 修改报告最终状态。
- 通过审核。
- 读取 hidden test 答案。
- 访问其他课程或学生的数据。

高风险工具仍使用现有逐次审批和 `If-Match` 机制。前端隐藏按钮不能代替后端 `can_start_session`、工具策略和 workspace scope 校验。

## 五、实时更新

优先使用 `PortalEventClient` 失效 Agent 消息 Query；SSE 不可用时保留短轮询降级。Agent 消息完成、工具状态变化和 Session 过期都必须能反映在抽屉中。

## 六、建议文件

- `frontend/apps/user-web/src/p12.tsx`：抽取 `TaskAgentDrawer`。
- `frontend/apps/user-web/src/p08.tsx`：挂载 `AgentOrb`。
- `frontend/packages/api-client/src/index.ts`：补齐消息和工具调用类型（如有需要）。
- `frontend/packages/query-keys/src/index.ts`：复用或补充 Agent task session key。
- `frontend/packages/ui/src/styles.css`：只增加通用 drawer/orb 视觉样式，不放 Agent 业务语义。

## 七、测试

- 圆球打开/关闭和键盘可达。
- 当前任务能创建 `WORKSPACE_ASSIST` 会话。
- 消息异步完成后能刷新。
- 引用信息只来自当前课程范围。
- 无工作区 Session、Session 过期或任务终止时工具调用被拒绝。
- 工具审批不能绕过 If-Match 和逐次审批。
- Agent 面板在 390px 视口不遮挡主要操作。

## 八、完成标准

- 用户无需离开工作台即可询问 Agent。
- Agent 不改变现有任务、报告和测试状态机。
- 敏感上下文不出现在 DOM、URL、localStorage 或日志。
- Agent 相关单元测试和用户端 E2E 通过。
