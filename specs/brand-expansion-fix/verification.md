# Verification

## 根因与覆盖范围
已同步 origin/main 的 f44d8be。当前管理入口 App.tsx 转导出 console/Console.tsx；该新控制台品牌只是 SVG，没有展开事件，折叠后仍渲染 nav-collapse 箭头。教师端共享 AppShell 虽有事件，但 styles.css 中 brand-mark 和 nav-collapsed .brand-lockup 的 display:none 使展开按钮不可见。本次修改实际入口，而非旧控制台。
同步时同时保留学生账户末行约束，并与主线的品牌+箭头双列 grid 相匹配。主线原先 align-content:start 且没有伸缩导航行，这也解释了用户之前侧栏账户紧跟菜单的截图；上次检查的是旧样式版本。

## 工程验证
- npm run build：学生、教师、管理三端生产构建通过。
- npm run typecheck：通过。
- npm run lint：通过。
- npm run test：38 个文件、183 项通过。首次与构建并发时旧健康状态测试在默认 1 秒等待内超时；单独运行该文件 3/3 通过，再运行全套 183/183 通过。
- 新增实际 Console 的重复收起/品牌展开回归测试。
- git diff --check：通过。

## 浏览器验证
使用生产构建和本地模拟空数据账号访问实际管理 Console 及教师 AuthGuard 路由，而非共享组件演示页：
- 管理端重复两次：收起后 nav-collapse 数量 0，40px 品牌按钮可见；点击 SVG 展开，第二轮按 Enter 展开。
- 教师端重复两次：收起后 sidebar-toggle 数量 0，品牌按钮及父区域均可见；点击 SVG 展开，第二轮按 Enter 展开。
- 学生端同步后视口高 900px，账户底边 872px，保留主线 28px 底部内边距，grid-area=account。
- 未连接生产后端、未修改真实账号或业务数据。

## 截图与设计检查
Ego 截图因窗口最小化不可用，改用设计 skill 的检查器捕获生产页面。临时预览服务使用 collapse=1 参数在应用挂载后点击实际收起按钮；没有修改生产 bundle 或伪造折叠 CSS。已查看管理、教师在 1440/768/390px 的截图，桌面折叠栏只显示品牌和导航图标，无独立箭头。
管理检查的 tiny-text 失败来自按需求隐藏的 7 个导航标签 font-size:0，按钮均有原有 aria-label；属于折叠导航有意隐藏文本。教师内容区仍有既有 10px 图表文字、缺少 h1 两项失败，以及指标图标/空数据留白/无数据色/对比度警告，本次不扩大到业务内容重设计。未宣称设计全绿。

ROUND 1
Seen in one second: 两端折叠侧栏顶部品牌可见，无独立展开箭头。
Idea (one sentence): 产品品牌同时作为展开导航的入口。
Live thing: 品牌鼠标点击、Enter 与再次收起。
Layout words by section: shell=品牌展开入口 / content=保留当前主线内容。
Scores: design 7.5 · usability 8 · creativity 7 · content 7 → overall 7.5
Caps applied: 本次组件修复不重评既有内容区。
Top three problems (most visible first), each with the screenshot it shows in and the fix:
1. 管理 desktop-fold：旧独立箭头已移除，品牌成为按钮。
2. 教师 desktop-fold：旧隐藏品牌规则已移除，图标可见。
3. 教师 mobile-fold：原有图表轴文字小，本次保留业务内容并记录限制。
