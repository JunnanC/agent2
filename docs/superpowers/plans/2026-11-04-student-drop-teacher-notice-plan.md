# 学生退课通知老师 Plan

courses 新增 enrollment.student_dropped 事件，在 drop_enrollment 的同一事务内保存教师收件人及学生/课程/原因/时间快照。接收者为有效课程成员且具有 MANAGE_ENROLLMENT 权限，沿用负责人全权限规则。既有 enrollment.ended 学生消息保持原样。

notifications 消费该事件，通过专用教师收件人分支投递 TEACHING，利用现有 OutboxDelivery 与 Notification 唯一约束去重。正文使用快照避免后续修改影响通知。投递沿用定时消费者，不将老师读通知与退课状态关联。

teacher-web 新增 notifications.tsx，复用 meApi 通知/已读接口与现有 UI；页头按钮展示未读计数，入口与列表轮询 30 秒；route 为 /notifications。学生退课弹窗说明即时生效和通知老师。
