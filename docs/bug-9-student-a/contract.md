# A/B 学号接入契约

学号 strip/casefold 后全站唯一，3–32 位字母、数字、点、下划线、连字符；导入账号 username=学号（至少3位，沿用账号约束）。旧账号 student_number=null 不影响邮箱/用户名登录。学号不能占用其他账号的用户名；导入不会覆盖已有账号。邮箱必填且唯一，初始密码逐行显式提供，使用现有密码强度规则，不返回口令，不增加默认密码或新首次登录规则。

平台管理员 POST /api/v2/platform/student-imports，JSON {"csv":"student_number,email,display_name,password\n2026001,s1@example.edu,学生一,School-2026!a"}，带 CSRF 与 Idempotency-Key。最多500行，结构错误拒绝整个请求，业务错误逐行返回。

成功 HTTP 200，data.rows=[{"row_number":2,"student_number":"2026001","status":"CREATED","user_id":"ULID"},{"row_number":3,"student_number":"2026001","status":"FAILED","error":"duplicate_identifier"}]；不回显密码。

B 继续调用现有 POST /api/v2/teaching/courses/{course_id}/enrollment-imports/precheck，CSV 可用 student_number 列代替 username；保留 username 格式。若两列均有值必须匹配同一学生。未找到、重复、禁用、非学生账号走既有逐行失败结果。查询/确认沿用 enrollment-imports/{job_id}，UI 由 B 负责。

## 文件与报告补充

- GET /files/{token}?preview=1：PDF、PNG/JPEG/GIF/WebP、纯文本使用 inline 响应并加 sandbox；DOCX、HTML、SVG 等不支持安全内嵌的格式返回 415 和下载提示，不消耗下载次数。无 preview 参数始终附件下载。
- assessment 返回 report_required 与 report_template（asset_id/file_name 或 null），report_required=false 不展示报告上传区域。
- 必交报告以至少一个已关联且扫描 CLEAN、状态 ACTIVE 的附件为准，正文不再是必交条件；原有正文历史与版本接口保留兼容。教师报告附件下载要求学生持有该模板的发布任务且选课有效。
- 部署需运行 `python manage.py migrate` 应用 accounts.0003；新字段可空，旧账号无需回填。接口与前端需随此后端一起部署，避免仍按正文必交的旧接口拒绝附件报告。
