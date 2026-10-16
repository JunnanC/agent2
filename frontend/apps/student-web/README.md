# 学生端 UI 接入位置

这是可启动、可构建的预留应用，尚未实现学生端业务。

1. 将 React 页面和组件放进 `src/`，从 `src/App.tsx` 组合页面。
2. 全局样式写入 `src/styles.css`；静态文件可放在本应用的 `public/`。
3. 在 `frontend` 目录执行 `npm run dev:student`，端口为 `5173`。
4. `npm run build:student` 输出到 `frontend/dist/student-web`。
5. 本应用不引用管理端或其他应用的 src。共享包在存在实际复用需求时放到 `frontend/packages`。
