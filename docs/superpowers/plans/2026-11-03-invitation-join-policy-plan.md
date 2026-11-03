# 邀请码加入策略 Plan

后端在选课服务中先规范化邀请码并消费有效邀请码，再按“有邀请码/无邀请码”选择 ACTIVE/PENDING。前端加入课程弹窗移除对课程 enrollment_mode 的即时生效判断，改为根据邀请码输入动态说明和按钮文案；接口成功返回的选课状态决定提示内容。

ACTIVE 成功结果使选课、学生汇总和上下文缓存失效并导航到关联课程；PENDING 保持申请页面。邀请码入口独立于课程列表的空状态。课程演示脚本和依赖激活选课的测试通过教师审批服务获得学习权限。

涉及文件：

- `backend/apps/courses/services.py`
- `backend/apps/courses/tests/test_services.py`
- `frontend/apps/student-web/src/pages/join-courses.tsx`
- `frontend/apps/student-web/src/pages/join-courses.test.tsx`
- `backend/apps/core/demo/catalog.py`
- 课程与评审演示脚本、治理 API 测试
- `docs/frontend/frontend-backend-integration-guide.md`
