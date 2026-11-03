# 演示课程数据与学生退出课程 Plan

## 架构概览

后端沿用 `seed_demo_full` 的配置驱动模型：扩充课程定义池，并提高 `demo` 规模的课程数；课程目录构建器按稳定课程代码创建缺失课程并补齐内容、花名册和课程资源。前端复用现有 `EnrollmentExit` 组件，在我的申请页为待审核选课挂载同一组件，在我的课程卡片的操作区保留主动退课入口。

## 核心数据结构

- `DemoConfig.courses`: 当前演示规模要生成的课程数。
- `COURSE_DEFS`: 课程标题、简介和描述池；课程索引通过 `course_code(index)` 形成稳定唯一代码。
- `EnrollmentExit`: 接收一条选课记录，根据最新状态在 `ACTIVE` 与 `PENDING` 间选择退课或撤回流程。

## 模块设计

### 演示课程目录

**职责：** 生成课程实体和其章节、材料、公告、日历、邀请码等关联数据。

**依赖：** `DemoConfig`、`COURSE_DEFS`、课程服务层。

### 学生课程列表

**职责：** 展示激活课程，提供进入课程和退出课程操作。

**依赖：** 学生 API、`EnrollmentExit`、React Query 缓存。

### 学生申请列表

**职责：** 展示待审核申请并提供撤回入口。

**依赖：** 学生 API、`EnrollmentExit`、申请列表刷新。

## 模块交互

种子命令读取规模配置 → 课程目录按稳定代码创建/复用课程 → 内容与花名册构建器补齐关联数据。学生点击退出或撤回 → 组件读取最新选课版本 → 调用退课/撤回接口 → 使课程、申请和学生相关查询失效 → 页面重新读取列表。

## 文件组织

```text
backend/apps/core/demo/config.py       # 演示规模
backend/apps/core/demo/banks.py        # 课程定义池
frontend/apps/student-web/src/pages/courses.tsx      # 我的课程退出入口
frontend/apps/student-web/src/pages/join-courses.tsx # 我的申请撤回入口
frontend/apps/student-web/src/components/enrollment-exit.tsx # 退出/撤回流程
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 课程扩充方式 | 扩充定义池并提高 demo 规模 | 保持现有种子流水线和稳定代码规则 |
| 退出交互 | 复用 `EnrollmentExit` | 已包含最新版本、阻塞检查和错误提示 |
| 待审核申请操作 | 同样复用 `EnrollmentExit` | 组件已支持撤回申请，避免重复实现 |
