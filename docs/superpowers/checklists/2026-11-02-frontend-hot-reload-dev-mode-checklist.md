# 前端热更新开发模式 Checklist

- [x] `docker compose -f docker-compose.frontend-dev.yml --project-name edu-platform-frontend-dev config` 通过。
- [x] 学生端、教师端、管理端分别监听 5173、5174、5176；管理端容器内部仍监听 5175。
- [x] 三个开发入口页面返回 200，并显示对应门户标题。
- [x] 三个开发入口的 `/api/v2/health` 通过代理返回 200，门户标识正确。
- [x] 至少一个门户修改源码后，开发服务器日志显示模块更新且无需重建 Nginx。
- [x] `frontend` typecheck 通过。
- [x] 三个门户 build 通过。
- [x] 停止脚本只移除前端开发容器，MySQL/Redis/MongoDB/MinIO 数据卷仍存在。
- [x] `http://*.localhost:8080` 静态入口仍可访问。
