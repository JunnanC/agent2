# 课程章节定位 Plan

课程详情页按接口章节顺序渲染全部 Panel，以章节 public_id 生成稳定目标 id。导航点击更新选中标识并通过 scrollIntoView 平滑定位；使用 scroll-margin-top 留出页头空间。
