# 技术设计

复用 CourseDetail 的课程权限检查和目录，为独立路由 /courses/:courseId/questions 传入 discussionPage 标记。该模式只展示 CourseDiscussion，普通详情移除问答并独立显示日历。目录末尾追加顺序编号的问答链接。

目录点击普通章节时，在详情页平滑定位；在问答页则导航回带章节 hash 的课程详情，待章节加载完成后定位。问答页禁用详情滚动同步，始终高亮问答入口。沿用 CourseDiscussion 的查询和变更接口。

不改变后端。所有课程资源仍须等待课程访问检查成功；问答组件仅在授权详情渲染后挂载。
