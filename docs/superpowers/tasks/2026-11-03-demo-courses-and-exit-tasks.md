# 演示课程数据与学生退出课程 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `backend/apps/core/demo/config.py` | 提高默认演示课程数 |
| 修改 | `backend/apps/core/demo/banks.py` | 增加独立课程定义 |
| 修改 | `frontend/apps/student-web/src/pages/join-courses.tsx` | 给待审核申请挂载撤回入口 |
| 修改 | `frontend/apps/student-web/src/pages/courses.tsx` | 保持已加入课程退课入口可见 |
| 修改 | `frontend/apps/student-web/src/components/student-api-ui.test.tsx` | 覆盖退出与撤回入口行为 |

## T1: 扩充演示课程规模

**文件：** `backend/apps/core/demo/config.py`, `backend/apps/core/demo/banks.py`

**依赖：** 无

**步骤：**
1. 增加课程定义池中的课程主题。
2. 将 `DEMO` 规模课程数提高到定义池覆盖的数量。
3. 保留稳定课程代码和既有种子幂等逻辑。

**验证：** 运行 Python 编译检查，并执行种子 dry-run 确认规模输出。

## T2: 接入申请撤回入口

**文件：** `frontend/apps/student-web/src/pages/join-courses.tsx`

**依赖：** T1

**步骤：**
1. 引入 `EnrollmentExit`。
2. 在“我的申请”课程卡片中为 PENDING 选课显示撤回按钮。
3. 保持发现课程页不重复显示退出控件。

**验证：** 组件测试确认 PENDING 记录显示撤回按钮并调用撤回接口。

## T3: 校验课程退课入口

**文件：** `frontend/apps/student-web/src/pages/courses.tsx`, `frontend/apps/student-web/src/components/student-api-ui.test.tsx`

**依赖：** T2

**步骤：**
1. 确认 ACTIVE 课程卡片操作区显示退出课程按钮。
2. 增加页面级渲染覆盖，避免按钮只存在于孤立组件。

**验证：** 运行相关 Vitest，确认按钮可见且不阻断进入课程链接。

## T4: 全量验收

**文件：** 无新增

**依赖：** T1、T2、T3

**步骤：**
1. 执行 `npm run typecheck`。
2. 执行学生端组件 Vitest。
3. 执行 `npm run build:student` 和 Python `compileall`。

**验证：** 所有命令成功退出；若后端环境依赖缺失，记录实际阻塞原因。

## 执行顺序

```text
T1 → T2 → T3 → T4
```
