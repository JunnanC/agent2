# 学生有待办时退课 Plan

`enrollment_exit_check` 增加默认关闭的 `allow_unfinished_tasks` 参数，仅学生 drop-check 与 drop 提交启用，过滤 UNFINISHED_TASK；非 ACTIVE 与其他阻塞继续返回。教师移除保留默认行为。

`paged_user_tasks` 对非有效选课仅保留终态任务，未完成任务保留在学习历史；`allowed_actions` 在选课非 ACTIVE 时返回空操作。现有 start、enter 和工作台会话权限继续负责后端拒绝操作。

退课组件更新说明文字并保留服务端检查结果驱动确认按钮。新增服务层规则测试、真实任务退课 API 回归与前端文案/提交流程测试。
