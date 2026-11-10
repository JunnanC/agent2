# 三端导航与配色 Tasks

## 文件清单
共享 navigation.tsx、styles.css、navigation.test.tsx；教师 main.tsx、app/guards.tsx；管理 App.tsx、styles.css、app/guards.tsx；学生 app/guards.tsx。

## T1：共享外壳
实现品牌展开与独立收起按钮、滚动导航和底部个人菜单，统一外壳色值。验证：导航组件测试、桌面折叠交互。

## T2：教师与管理接入（依赖 T1）
教师补齐导航图标及折叠状态；管理主控制台加入折叠，滚动菜单与个人信息分离，旧路由启用共享侧栏。验证：三端构建和类型检查。

## T3：验收与提交（依赖 T2）
运行测试、lint、构建；浏览器检查三端展开/折叠和移动适配，记录结果，提交 web1 并向 main 创建 PR。
