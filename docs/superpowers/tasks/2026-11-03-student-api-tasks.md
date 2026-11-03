# 用户端接口接入 Tasks

1. 修正并补齐 packages/api-client/src/types.ts、index.ts；检查路径、请求模式、解包和返回类型。验证：契约测试。
2. packages/auth-client/src/index.ts 支持 FormData，packages/query-keys/src/index.ts 增加缓存键。验证：JSON/文件请求和重试测试。
3. student-web 的 course-detail、profile、notifications 连接真实接口；新增课表组件接入 courses。验证：交互测试和类型检查。
4. 更新接口接入说明，重新生成 schema 类型，运行测试和学生、教师构建。验证：记录命令结果、diff 检查。
