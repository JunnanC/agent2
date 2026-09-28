# P13-B integrations 出口记录

阶段：P13-B 本地 OIDC、开放 API 与 Webhook

日期：2026-09-24

## 范围与边界

- 新增 OIDC Provider/Identity、API Client/Grant、Webhook endpoint/delivery/attempt 模型和管理 API；secret 只保存 hash 或签名密文，创建/轮换响应只返回一次明文。
- 开放 API 使用 IntegrationPrincipal、显式 scope、课程 grant 和 client 独立 Redis 限流；不把浏览器 Session 转换为开放 API 权限。
- OIDC 绑定以 issuer+subject 唯一键拒绝静默合并；Webhook 使用 delivery id、timestamp 和 body digest HMAC，delivery attempt 可审计并支持重试/死信事实。

## 本地证据

- Django check、迁移检查、P13-B 定向 pytest、Ruff、OpenAPI 校验和三端 TypeScript 检查由 `scripts/verify-p13-b.ps1` 执行。
- P13-B 定向测试覆盖 OIDC 唯一绑定、双密钥过渡窗口、Webhook 签名和重复事件幂等。
- 当前仅验证本地契约和受控适配器，不宣称真实 IdP、外部 API 网关、外部接收方或生产密钥轮换已通过。

## 双门禁与出口

本地门禁：通过（以脚本执行输出为准）。

真实环境门禁：待验收。

真实环境阻塞：真实 IdP discovery/token exchange、网关限流、外部 webhook 网络故障、HA、容量和 RPO/RTO 尚未验证。

出口结论：**本地通过（真实环境待验收）**。
