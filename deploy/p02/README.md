# 02 组部署配置

本目录用于公司共享服务器 `192.168.100.3` 的 02 组部署。Compose 项目名是 `p02`，唯一网络是 internal 的 `p02_p02`，Nginx 入口使用 `1025`。本目录与旧云服务器 CD 独立，不执行 SSH Shell 登录。

当前交付阶段为本机配置和评审。公司服务器尚未连接或修改；先按用户要求逐项确认远程操作。`settings_lab.py` 是 **HTTP 内网验证配置**；正式 HTTPS 仍需公司域名、证书及单独配置，不作为已完成事项。

## 已配置内容

- `compose.build.yml`：只在本机构建后端、Nginx、配置/初始化和 stdio 镜像。
- `Dockerfile.frontend`：只复制本机生成的三个 `dist`；不含 Node、npm 或前端构建阶段。打包使用独立的本机 Node 24 临时容器。
- `compose.server.yml`：17 个服务/初始化任务，全部显式加入本组网络；无 build、源码挂载、跨组路径或 Docker socket。数据采用项目命名卷。
- `compose.runtime.yml`：明确获准后才合并的 runtime-worker，包含 Docker socket；默认不启用。
- `nginx.conf`：学生/教师/管理三个独立域名及文件上传域名。保留 Kong 的门户上下文，不开放其管理接口。
- `settings_lab.py`：独立的 HTTP Cookie 配置；公网 AI 留空、邮件不发送。附件扫描使用不需要 Docker 的 `q_scan` 队列。
- `p02.py`：私有配置初始化、Compose 边界校验、Context 配置、预检、打包、锁定、传输和发布入口。每个远程操作均为独立命令，不被本机初始化/检查隐式调用。

私钥不在代码仓库中。真实 `.env` 已在本机生成，权限为 `600`，不提交、不输出密码。SSH/Context 安装后不切换全局 Context，也不立即发起连接。

## 当前本机用法

在仓库根目录运行：

```bash
python3 deploy/p02/p02.py init
python3 deploy/p02/p02.py check
```

如需在另一台电脑创建连接（替换私钥绝对路径）：

```bash
python3 deploy/p02/p02.py install-context --identity /absolute/path/p02/id_ed25519
```

这一步只改本机 `~/.ssh/config` 和 Docker Context。初次实际连接时，需要按管理员提供的指纹确认服务器身份，不关闭主机指纹校验。

本机 hosts 或公司 DNS 需要配置 `hosts.example` 中的四个名称。未修改系统 hosts。地址为：

- `http://student.p02.test:1025`
- `http://teacher.p02.test:1025`
- `http://admin.p02.test:1025`
- `http://files.p02.test:1025`（签名上传入口，非 MinIO 管理控制台）

## 待逐步确认的远程操作

1. **只读预检**：确认网络可达、服务器身份与 Docker 权限后运行 `python3 deploy/p02/p02.py preflight`。只读取 Docker 信息和本组容器，记录目标架构，不启动容器。
2. **最小入口验证**：准备服务器可用的 Nginx 成品镜像并获准后，运行 `python3 deploy/p02/p02.py probe`。只创建本组网络及临时 `p02-probe`、使用 1025；成功或失败都移除探针容器，保留本组网络。成功时记录实际子网，供后端可信代理设置使用。端口冲突或 internal 网络不通时停下，不增加外联网络。
3. **本机构建**：`python3 deploy/p02/p02.py build`。先核实目标架构，再在本机 Node 24 容器执行 npm 打包；随后本机构建所有自定义镜像。基础镜像可通过 Compose build args 更换获准来源。
4. **锁定镜像**：在本机准备好所有基础镜像及自定义镜像后运行 `python3 deploy/p02/p02.py lock`，记录完整镜像 ID、架构、代码版本。基础镜像也纳入清单，避免服务器临时访问镜像源。
5. **传输镜像**：获得确认后运行 `python3 deploy/p02/p02.py transfer`。本机 `save -o` 导出到临时 tar，再通过 Context `load -i`，逐一核对完整 ID；支持 Windows 二进制文件传输，结束后自动清理本机临时包。此步骤不启动业务容器。
6. **准备病毒库和配额**：管理员提供有效的 ClamAV 离线签名库和允许的导入方式；在本组命名卷准备并验证，才将私有配置 `P02_CLAMAV_DATABASE_READY` 设为 `true`。填写真实获批 `P02_GROUP_CPU_MILLICORES` 和 `P02_GROUP_MEMORY_MB`。当前默认容器上限是检查起点，需要按组配额调整并实测，并非已经获批容量。
7. **启动基础业务**：确认发布窗口和备份/恢复后，运行 `python3 deploy/p02/p02.py deploy`。缺少入口验证、配额、病毒库、镜像清单或远程镜像 ID 不符都会停止；不在服务器构建或拉取镜像。依赖顺序包含 MySQL 用户、数据库迁移、权限、MinIO 和 MongoDB 初始化。
8. **开启真实判题**：另行取得直接 Docker socket 的明确授权，填写其 GID 以及单独的动态判题 CPU/内存预算，才设置 `P02_RUNTIME_APPROVED=true`。`deploy` 会合并运行扩展文件，并将动态预算计入组上限。如果管理员只提供受限 Docker API，需要另行适配，不直接把 socket 配置套上去。

初始化镜像和 API 服务健康并不代表全部业务验收。无 runtime-worker 时，编程执行和自动判题尚不可用；模板预检、归档等需要 Docker 的业务也须实测后才能计入验收，不以假结果代替。ClamAV 未准备好时不跳过扫描。

## 回退与日常操作

所有命令必须显式指定 `--context p02`、同一 `--env-file` 和 `-f`。日志与状态命令不打印环境变量：

```bash
docker --context p02 compose --env-file deploy/p02/.env -f deploy/p02/compose.server.yml ps --all
docker --context p02 compose --env-file deploy/p02/.env -f deploy/p02/compose.server.yml logs --tail 100
```

启用运行服务后，状态命令也添加 `-f deploy/p02/compose.runtime.yml`。保留上一版镜像清单和私有配置，常规更新不删除数据卷。发布前单独备份本组 MySQL、MongoDB 和 MinIO 数据；涉及不可逆迁移时先验证恢复，不只回退镜像。禁止全局 prune、`down -v`、跨组资源清理或修改宿主机网络。

代码中的判题资源新增 `edu.platform.project` 标签；过期清理只处理标签相符的本组资源。历史没有该标签的资源不会由新清理器接管，旧环境如采用此提交，应另行盘点旧资源后处理。

## 本次验证

本机已验证 Compose 基础/运行扩展的网络、端口、卷和挂载边界；Django 系统检查通过；已有后端相关回归和新增共享服务器隔离测试通过。前端三个 dist 构建完成，Nginx 成品镜像构建、语法、三门户静态页和健康检查通过。

前端镜像的 `review` 标签是本机架构的验证产物，不是服务器最终发布镜像。目标架构、内网连通、internal 网络上的入口、组配额、病毒库、Docker 运行权限和 HTTPS 均待现场确认。后端 Linux 镜像构建结果另见本次提交说明，不把 SQLite 检查描述为 MySQL 部署验收。
