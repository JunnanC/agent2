# 用户端接口接入 Plan

## 设计
1. api-client 使用 generated/schema.d.ts 的请求和响应类型；弱类型响应根据后端 serializer 补充命名类型，统一只解包一次 data。
2. auth-client 区分 FormData 与 JSON，前者由浏览器设置 multipart 边界，同时保留 CSRF 和重试。
3. query-keys 增加课表、导入、学习历史、Agent 键；课程资源统一归属课程缓存。
4. 学生端课程页接入资源、问答；个人页接入通知偏好；通知页使用 public_id/read_at/row_version；课程列表附加课表组件。
5. reportApi 从草稿读取附件，上传预签名请求发送完整元数据，下载返回 download_path。其他尚未有 UI 的能力暴露客户端方法。

## 验证
用 fetch mock 验证 API 契约、请求头和 multipart 上传；运行共享包及学生、教师、管理端类型检查，学生和教师生产构建。真实后端课表联调作为环境依赖保留。
