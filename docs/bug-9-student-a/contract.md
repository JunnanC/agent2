# A/B 学号接入契约

学号 strip/casefold 后全站唯一，3–32 位字母、数字、点、下划线、连字符；导入账号 username=学号（至少3位，沿用账号约束）。旧账号 student_number=null 不影响邮箱/用户名登录。学号不能占用其他账号的用户名；导入不会覆盖已有账号。邮箱必填且唯一，初始密码逐行显式提供，使用现有密码强度规则，不返回口令，不增加默认密码或新首次登录规则。

平台管理员 POST /api/v2/platform/student-imports，JSON {"csv":"student_number,email,display_name,password\n2026001,s1@example.edu,学生一,School-2026!a"}，带 CSRF 与 Idempotency-Key。最多500行，结构错误拒绝整个请求，业务错误逐行返回。

成功 HTTP 200，data.rows=[{"row_number":2,"student_number":"2026001","status":"CREATED","user_id":"ULID"},{"row_number":3,"student_number":"2026001","status":"FAILED","error":"duplicate_identifier"}]；不回显密码。

B 继续调用现有 POST /api/v2/teaching/courses/{course_id}/enrollment-imports/precheck，CSV 可用 student_number 列代替 username；保留 username 格式。若两列均有值必须匹配同一学生。未找到、重复、禁用、非学生账号走既有逐行失败结果。查询/确认沿用 enrollment-imports/{job_id}，UI 由 B 负责。
