# Bug-10 B 端联调接口

教师从教学班的 **实验发布** 进入 **实验环境**、**新建实验** 和 **报告与评审**。新实验从班级直接创建，应用按课程权限校验环境和发布。历史实验仍可读取模板和既有发布快照。学生答题工作台继续使用 `task_id`。

## 教学班和页面入口

`Course.public_id` 为教学班 ID。教师实验列表使用 `GET /api/v2/teaching/courses/{course_id}/experiments`，列表的 `public_id` 就是 `publication_id`。学生使用 `/experiments/{task_id}/assessment`。教师评审入口为 `/courses/{course_id}/publishing/{publication_id}/reviews`，可加 `?tab=reports` 直接打开报告列表。

## 已发布成绩

`GET /api/v2/teaching/courses/{course_id}/experiments/{publication_id}/published-grades` 需要教学班的进度查看权限。返回 `data.grades_published_at` 与 `data.rows`。未发布时日期为 `null` 且列表为空。

| 字段 | 含义 |
| --- | --- |
| `course_id`、`publication_id`、`task_id`、`student_id`、`enrollment_id` | 使用已有公开 ID。未分配任务时 `task_id` 为 `null` |
| `deadline`、`grades_published_at` | ISO 时间，分别为实验截止及实际成绩发布时间 |
| `should_do` | 该学生是否应计入该实验。截止后入班为 `false` |
| `status` | `NOT_SUBMITTED`、`PARTIAL`、`SUBMITTED` 或 `NOT_ASSIGNED` |
| `score`、`max_score` | 分项分数与满分之和，保留两位小数。无需参与且无任务时为 `null` |
| `parts` | 每项包含 `kind`、`score`、`max_score` 和 `status`。启用的分项分别为 `CHOICE`、`PROGRAMMING`、`REPORT` |

统计纳入 `should_do = true` 的记录，按实得分之和除以满分之和折算百分制。应做但未交为 0 分。教师在截止后可以调用 `POST .../{publication_id}/grade-release`；待处理报告、未完成正式评测或开放补做会阻止发布。成功后再次调用复用原发布时间和结果。

学生使用 `GET /api/v2/tasks/{task_id}/published-grade` 读取自己的发布快照，通过 `GET /api/v2/tasks/{task_id}/report/reviewed` 下载自己的批阅 Word。发布前这两个入口均返回 404。批阅使用课程负责人姓名作为落款。

## 环境和验证

实验环境和批阅数据分别随 `experiments`、`reports` 新迁移创建。部署先迁移，再执行 MySQL 应用账号的权限配置。环境测试和用量采样走 `q_provision`，使用共享 Redis 缓存。Docker 采样成功且容器数为 0 时显示空闲，采样失败时显示指标不可用。

AI 草稿与 Word 批阅使用已有的 `RUBRIC_AI_API_KEY`、`RUBRIC_AI_BASE_URL`、`RUBRIC_AI_MODEL_NAME` 配置。Word 批阅提取正文、段落定位及有效字号。代码截图等图片仍可在原始和批阅版 Word 中由教师查看。

B 端使用已存在的实验客户端模块。OpenAPI 文件和共享生成类型由 A 端在双方合并时统一更新。
