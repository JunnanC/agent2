# 标准输入输出执行镜像

使用 `Dockerfile.stdio` 构建 `experimental-platform-stdio:local`。镜像包含 Python、C、C++、Java 和 Go 工具链，不包含 IDE、终端服务或 HTTP 路由。

```powershell
docker build -f runtime/algorithm-workspace/Dockerfile.stdio -t experimental-platform-stdio:local runtime/algorithm-workspace
python scripts/verify/assessment-runtime-smoke.py
```

容器由可信 worker 按需创建，用完回收；不向学生开放端口。隐藏测试调度和比较在 worker 执行。发布、正式种子和验收见 [轻量答题验收](../../docs/开发指南/轻量答题验收.md)。
