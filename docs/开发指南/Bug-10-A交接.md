# Bug-10 笔记本 A 交接

## 教学班、路由和权限

- 教学班 ID 沿用 `Course.public_id`，学期 ID 沿用 `AcademicTerm.public_id`。课表导入的班号存于 `Course.timetable_code`，以教师和学期为范围。同名班可用不同班号区分。学生使用教师在「名单、课程码及申请」生成的邀请码。
- 两端班级详情都使用 `/courses/:courseId`。教师实验列表使用 `publication_id`，评审路由为 `/courses/:courseId/publishing/:publicationId/reviews`。学生实验沿用 `/experiments/:taskId` 和 `/experiments/:taskId/assessment`，返回班级通过任务的 `course_id`。
- 发布定位班级用 `course_id`。实验读取时按教师授权或学生任务关联校验班级。教学分析为 `/courses/:courseId/analytics`。

## B 的已发布成绩数据

A 的统计需要每个已发布实验的冻结快照，含应做范围内每位学生的一条结果。看板和导出共同读取这份快照。

| 记录 | 字段 |
| --- | --- |
| 实验 | `course_id`、`publication_id`、`title`、`deadline`、`released_at` |
| 学生结果 | `publication_id`、`student_id`、`student_name`、`task_id`（未建任务时可为空）、`joined_at`（对应选课周期的 `Enrollment.activated_at`）、`expected`、`submission_status`、`parts` |
| 三项计分 | `parts` 以 `CHOICE`、`PROGRAMMING`、`REPORT` 为键，值为原始量纲的 `(actual_score, max_score)`。适用项未交时实得为 0，未启用的分项省略 |
| 提交状态 | `SUBMITTED`（全部应交项完成）、`PARTIAL`、`NOT_SUBMITTED` |

未交的应做学生也须出现在快照中。若实验的截止时间早于对应选课周期入班时间，从该生总评和完成度排除。补做后的有效成绩若已发布，应归并到原实验的一条结果。无法确定选课周期的结果提供任务 ID 和原因供核对。当前分支通过 `current_released_results` 读取已经到显式放分时间的旧任务及分项数据。B 合入后由该入口接冻结快照，并重跑 OpenAPI 生成。

## 虚构数据和历史盘点

当前学期教师周老师开 `DS-01` 和 `DS-02`，均叫「数据结构」。往期另有同名 `DS-01`。学号 `20260001` 和 `20260002` 为已有账号，`20269999` 为未知学号。虚构学生 B 在第一次实验截止次日入班，第二次实验应做未交。成绩测试覆盖不同实验满分，A 的 20 + 40 分总评为 60%，B 只计第二次实验并标记未提交。

在备份库运行 `python manage.py audit_class_history`，留存迁移前后 JSON。报告列出教学班、排课、选课、实验、任务和报告数量，以及归属待确认的课表和任务、候选班级 ID 和受影响数量。迁移 0013 增加教务班号和单双周字段。旧导入在同教师、学期、班号、班名和已有节次均匹配时沿用原班级。其余待确认项可根据报告核对。
