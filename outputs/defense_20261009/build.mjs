import fs from "node:fs/promises";
import { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType, AlignmentType, ShadingType, BorderStyle, PageBreak } from "docx";

const out = "D:/all_of_project/edu-agent-platform/outputs/defense_20261009/项目答辩材料与功能全貌说明.docx";
const navy = "1F4E78", blue = "D9EAF7", light = "F5F8FA", orange = "FCE4D6";
const border = { style: BorderStyle.SINGLE, size: 4, color: "D9E1F2" };
const borders = { top:border, bottom:border, left:border, right:border, insideHorizontal:border, insideVertical:border };
function p(text="", opts={}) { return new Paragraph({ spacing:{after: opts.after ?? 120, line: opts.line ?? 280}, alignment: opts.align, children:[new TextRun({text, bold:opts.bold, color:opts.color, size:opts.size ?? 22, font:"Microsoft YaHei"})]}); }
function heading(text, level=HeadingLevel.HEADING_1) { return new Paragraph({ heading:level, spacing:{before:240, after:120}, children:[new TextRun({text, bold:true, color:navy, font:"Microsoft YaHei"})]}); }
function bullets(items) { return items.map(x=>new Paragraph({spacing:{after:80,line:260}, indent:{left:360,hanging:180}, children:[new TextRun({text:"• "+x,font:"Microsoft YaHei",size:21})]})); }
function table(headers, rows, widths){ const all=[headers,...rows]; return new Table({width:{size:100,type:WidthType.PERCENTAGE}, borders, rows:all.map((row,ri)=>new TableRow({children:row.map((cell,ci)=>new TableCell({width:{size:widths?.[ci]??100/row.length,type:WidthType.PERCENTAGE}, shading:ri===0?{fill:navy,type:ShadingType.CLEAR}:ci===0?{fill:light,type:ShadingType.CLEAR}:undefined, children:[new Paragraph({spacing:{after:60,line:240},children:[new TextRun({text:String(cell),bold:ri===0||ci===0,color:ri===0?"FFFFFF":ci===0?navy:"000000",size:19,font:"Microsoft YaHei"})]})]}))}))}); }

const architectureSections = [
 heading("七 项目架构与模块拆分"),
 p("本项目采用‘三端前端 + 统一后端 + 领域模块 + 异步运行时支撑’的整体架构。架构重点不是把代码简单堆在一起，而是让用户体验、业务规则、运行环境和平台治理彼此解耦，同时通过权限、状态机、审计和事件保持一致性。"),
 heading("7.1 总体分层",HeadingLevel.HEADING_2),
 table(["层次","主要组成","职责边界"],[
  ["表现层","user-web、teacher-web、admin-web，以及共享 UI 组件","按角色提供页面、表单、状态展示和交互；不直接决定最终权限和业务状态。"],
  ["接口层","Django API、统一路由、序列化、错误信封、Session/CSRF","把 HTTP 请求转换为业务用例，完成输入校验、身份上下文和响应规范。"],
  ["领域服务层","accounts、courses、experiments、workspaces、reports、reviews、agents 等服务","承载业务规则、状态跃迁、事务、幂等、对象权限和审计，是系统的核心。"],
  ["基础设施层","数据库、缓存、异步任务、对象存储、日志、事件流和运行时适配器","提供持久化、异步执行、文件保存、实时通知和外部环境连接，不反向决定业务事实。"],
  ["治理与观测层","governance、analytics、notifications、integrations、审计和运维看板","提供配额、风险、成本、通知、开放接口、日志和运维能力，辅助但不绕过核心业务规则。"]
 ],[16,34,50]),
 heading("7.2 三端前端拆分",HeadingLevel.HEADING_2),
 ...bullets(["用户端聚焦‘我要学习和完成实验’，主要页面包括课程目录、我的课程、我的实验、工作区、通知与个人资料。","教师端聚焦‘我要组织课程和审核成果’，主要围绕我的课程、实验发布、任务/成果查看、报告审核和课程 Agent。","管理端聚焦‘我要治理平台’，覆盖用户资格、课程监管、实验异常、实例回收、补偿、运行时、镜像、配额、安全和 Agent 策略。","三个前端共享 UI 和 API client，但不共享角色权限；前端只负责展示和发起操作，最终授权由后端重新判断。"]),
 heading("八 领域模块拆分与协作",HeadingLevel.HEADING_1),
 table(["模块","负责什么","不负责什么","与其他模块的关系"],[
  ["accounts","用户、登录、门户身份、教师/管理员资格、个人资料","不直接创建课程实验或改变学生任务","为所有模块提供 actor、portal 和资格上下文。"],
  ["courses","课程、章节、资料、任职、选课、容量和课程 Agent 入口","不直接创建运行实例或替代审核","experiments 读取课程和选课事实；reports/reviews 使用课程 scope。"],
  ["governance","资源目录、配额、策略、运行时规格、安全策略","不直接替换业务状态机","provisioning/workspaces 在启动和运行时操作前读取策略。"],
  ["labtemplates","实验模板、版本、Rubric、自动检查和预检","不直接给某个学生生成任务","experiments 在发布时引用已通过预检的模板版本。"],
  ["experiments","实验发布、受众、先修、个人任务和任务状态机","不负责具体容器/虚拟机实现","调用 provisioning 启动任务，向 workspaces/reports 提供任务归属。"],
  ["provisioning","异步装载、重试、补偿、实例和运行阶段事件","不在运行时层决定课程权限","根据 experiments 的任务状态和 governance 策略执行装载。"],
  ["workspaces","工作区票据、实时事件、自动保存、检查点和操作回放","不替教师提交报告或修改审核结果","绑定 experiments 的任务、实例和权限，向 reports 提供过程证据。"],
  ["reports / reviews / archives","报告成果、附件、扫描、教师审核、归档导出和回收","不绕过任务归属和课程授权","reports 关联 task/workspace，reviews 依据课程授权，archives 固化结果。"],
  ["agents","知识源、检索引用、提示词/模型配置、工具审批和评测","不直接改变任务、审核、配额或学生权益","由 courses/workspaces/reports 提供上下文，受 governance 和审计约束。"],
  ["analytics / notifications / integrations","分析、风险/质量/成本投影、通知、OIDC、Webhook 和开放 API","不自动替教师作出扣分、退课或延期决定","订阅业务事件和事实，向角色提供辅助信息。"]
 ],[18,27,26,29]),
 heading("8.1 模块边界的答辩说法",HeadingLevel.HEADING_2),
 ...bullets(["读操作通过 selector 按 actor、portal、course 和对象关系裁剪数据；写操作通过 service 执行业务规则、事务、状态跃迁和审计。","View、Serializer 和异步 task 不直接修改核心状态，避免页面或后台任务绕过权限和状态机。","外部 I/O 不放在数据库事务中；事务提交后再通过异步任务访问 Docker、对象存储、模型服务或 Webhook。","模块之间优先通过明确的服务、事件和事实关系协作，不通过跨模块直接拼接隐含规则。"]),
 heading("九 关键数据流与状态流",HeadingLevel.HEADING_1),
 table(["数据流","经过的模块","需要保证的事实"],[
  ["教师发布实验","courses → labtemplates → experiments → notifications/analytics","模板版本已预检；课程有发布权限；受众、先修、时间窗和发布事实可追溯。"],
  ["学生启动实验","accounts/courses → experiments → governance → provisioning → workspaces","学生有选课和任务归属；配额可用；状态按顺序跃迁；失败可重试/补偿。"],
  ["学生保存和提交","workspaces → reports → reviews","保存绑定工作区版本和任务；报告绑定任务；提交后教师只能访问授权范围。"],
  ["Agent 辅助","courses/workspaces/reports → agents → audit/feedback","回答基于授权知识源；工具按策略审批；输出不直接改变业务状态。"],
  ["平台运维","governance/analytics/notifications/integrations → admin-web","风险、成本、异常和日志用于人工决策；不绕过业务服务自动修改学生权益。"]
 ],[23,35,42]),
 heading("9.1 为什么采用状态机",HeadingLevel.HEADING_2),
 p("实验任务不是一个简单的‘完成/未完成’字段，而是经历发布、等待、装载、运行、保存、提交、审核、归档、失败和回收等阶段。状态机把允许动作、前置条件、失败原因、终态和审计事件固定下来，能够阻止非法跃迁，也方便重试、补偿和问题定位。"),
 heading("9.2 为什么需要事件和审计",HeadingLevel.HEADING_2),
 p("业务表回答‘现在是什么状态’，事件和审计回答‘为什么变成这个状态、谁在什么时候做了什么’。两者结合后，既能支持页面实时更新，也能支持故障排查、教师复核、管理员监管和答辩举证。")
];
const children=[];
children.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:80},children:[new TextRun({text:"项目答辩材料与功能全貌说明",bold:true,size:36,color:navy,font:"Microsoft YaHei"})]}));
children.push(new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:260},children:[new TextRun({text:"教学云实验平台 | 项目经理与开发人员通用答辩稿",size:22,color:"666666",font:"Microsoft YaHei"})]}));
children.push(p("本文档用于项目答辩准备，基于当前代码仓库、项目架构文档以及项目经理/开发人员评审表整理。答辩时应以实际可演示、可核验的功能为准；对于生产环境、真实 Docker Swarm/高可用等尚未完成的部分，应明确表述为后续部署与验收范围。",{after:220}));
children.push(heading("一 项目一句话介绍"));
children.push(p("本项目是一个面向教学实验场景的教学云实验平台，为学生、教师和平台管理员提供从课程发布、实验任务分发、个人实验工作区、报告提交、教师审核，到平台治理、运行时管理和智能 Agent 辅助的完整闭环。"));
children.push(p("它解决的核心问题是：将传统分散的课程资料、实验环境、任务进度、实验成果和教师审核统一到一个受权限控制、可追踪、可审计的平台中。"));
children.push(heading("二 项目全貌"));
children.push(table(["层次","内容","答辩描述"],[
 ["用户层","学生/实验参与者","浏览课程、申请选课、查看资料、领取个人实验任务、进入工作区完成实验、保存检查点、提交报告、获得 Agent 辅助。"],
 ["教学层","教师/课程负责人","创建和维护课程，管理章节与实验，发布任务，查看学生授权范围内的过程与成果，进行报告审核和课程 Agent 配置。"],
 ["治理层","平台管理员","管理用户与资格、课程监管、异常实验、实例回收、补偿任务、运行时、镜像、资源规格、配额、安全策略、报告扫描、审核监管和 Agent 策略。"],
 ["业务层","课程—实验—任务—工作区—报告—审核","将教学活动拆成可追踪的业务对象，并通过状态机、权限、审计和异步任务保证过程可控。"],
 ["技术层","三端前端 + Django 后端 + 数据与运行时服务","用户端、教师端、管理端通过统一 API 访问后端；运行时与工作区通过异步作业、事件流和短期票据连接。"]
],[16,27,57]));
children.push(heading("三 角色与功能地图"));
children.push(table(["角色","主要入口","核心功能","答辩重点"],[
 ["学生/用户","用户端","个人资料、课程目录、课程详情、课程学习、我的课程、实验工作台、我的实验、通知与建议","证明学生可以从课程进入实验，并围绕个人任务完成完整实验闭环。"],
 ["教师","教师端","我的课程、课程内容、实验发布、任务与成果查看、报告审核、课程 Agent 与评测","证明教师可以组织教学、控制实验发布、查看授权范围内证据并完成审核。"],
 ["平台管理员","管理端","用户/教师/管理员资格、身份审核、课程监管、实验异常、实例回收、补偿、运行时、镜像、配额、安全、运维与 Agent 策略","证明平台具备治理能力，而不是只有前台页面。"]
],[16,22,38,24]));
children.push(heading("四 核心业务闭环"));
children.push(p("建议答辩按照一条主线演示，不要按文件目录逐页介绍。主线是：教师建设课程 → 发布实验 → 学生选课 → 系统生成个人任务 → 启动并进入实验工作区 → 保存与提交成果 → 教师审核 → 平台归档和运维治理。"));
children.push(table(["阶段","业务动作","可展示材料","关键价值"],[
 ["1 课程建设","教师创建课程、章节、资料和实验模板","课程列表、课程详情、章节/资料、模板版本","教学内容结构化、可复用。"],
 ["2 实验发布","教师设置受众、先修条件、时间窗和发布策略","发布配置、先修条件、发布记录","每名学生获得正确归属的个人任务。"],
 ["3 任务生成","系统根据选课、受众和先修计算任务与阻塞原因","个人任务列表、任务状态、有效时间窗","避免任务错发、漏发和越权访问。"],
 ["4 实验执行","学生启动任务，进入个人工作区，使用手册、IDE、终端、预览和 Agent","工作区、实时状态、自动保存、检查点、操作时间线","形成可恢复、可追踪的实验过程。"],
 ["5 成果提交","学生提交报告、附件和实验成果","报告编辑/提交、附件、扫描结果","成果与过程证据关联。"],
 ["6 教师审核","教师查看授权范围内成果并给出审核决定","审核页面、意见、状态流转、审计记录","审核过程规范、可追溯。"],
 ["7 治理运维","管理员查看实例、异常、配额、日志、运行时和 Agent 策略","管理端看板、异常处理、回收/补偿","保障平台安全、稳定和可运营。"]
],[13,28,31,28]));
children.push(heading("五 功能与技术说明"));
children.push(heading("5.1 三端门户与身份权限",HeadingLevel.HEADING_2));
children.push(...bullets(["平台提供用户端、教师端和管理端三个独立门户；登录后的站点身份与后端会话绑定。","权限不是只在前端隐藏按钮，而是由门户准入、角色资格、课程关系、资源归属和当前状态共同决定。","教师和管理员不能通过修改前端参数越权查看学生数据；后端按 actor、portal、course 和对象关系裁剪数据。","项目中采用 Session/CSRF、可信门户上下文、对象级权限、审计和统一错误返回，便于安全演示。"]));
children.push(heading("5.2 课程与教学内容",HeadingLevel.HEADING_2));
children.push(...bullets(["教师可以维护课程、章节、资料、实验模板、版本和课程 Agent。","学生从课程目录查看已发布课程、课程说明、任课教师、选课方式和容量状态。","课程内容、实验模板和发布记录分离，便于版本化管理与后续复用。"]));
children.push(heading("5.3 实验发布与个人任务",HeadingLevel.HEADING_2));
children.push(...bullets(["实验发布支持受众、先修条件、时间窗、延期/补交和个人任务生成。","任务有明确状态机，非法状态跃迁、终态重启和越权推进会被拒绝。","学生看到的是属于本人的有效任务和时间窗，教师/管理员按授权范围查看过程投影。"]));
children.push(heading("5.4 工作区与运行时",HeadingLevel.HEADING_2));
children.push(...bullets(["学生进入个人实验工作区，使用手册、IDE、终端和预览完成实验。","工作区支持短期票据、实时事件、断线后的轮询降级、自动保存、命名检查点和操作回放。","任务启动采用异步装载流程，包含阶段、状态、重试、取消、错误码和补偿，当前本地链路以 FakeRuntime 验证编排；真实 Docker Swarm/VM 适配属于后续 P14 生产候选验收范围。"]));
children.push(heading("5.5 报告、审核与归档",HeadingLevel.HEADING_2));
children.push(...bullets(["学生可以提交报告、附件和实验成果，并保留版本、提交时间及关联任务。","教师在授权范围内查看报告和过程证据，进行通过、退回或补充意见等审核动作。","平台支持报告扫描、归档、导出、回收和审核监管，便于形成完整证据链。"]));
children.push(heading("5.6 受控 Agent 智能助手",HeadingLevel.HEADING_2));
children.push(...bullets(["课程 Agent 支持有引用的课程问答、苏格拉底式提示、调试辅助、报告辅导和工作区协助等模式。","知识源、提示词、模型路由、工具策略、预算和评测结果均版本化管理。","Agent 输出不会直接改变任务状态、审核决定、配额、网络策略或学生权益；高风险工具需要逐次审批并留下审计。","答辩时重点展示‘有引用、可解释、受权限控制、不会替代教师决策’。"]));
children.push(heading("六 技术架构表述"));
children.push(table(["部分","当前实现/设计","答辩表达"],[
 ["前端","React/TypeScript，用户端、教师端、管理端独立应用，共享 UI 与 API client","三端按角色隔离，既有统一体验，也有不同权限视图。"],
 ["后端","Django 单一规范项目，按 accounts、courses、experiments、workspaces、reports、reviews、agents、governance、analytics 等领域拆分","业务规则集中在服务层，读取走 selector，写入走 service，避免页面直接修改业务状态。"],
 ["数据与一致性","MySQL 等业务事实、Redis/异步任务、MongoDB 日志、MinIO/对象存储等运行支撑","业务状态、事件、审计、Outbox 和异步作业形成可追踪链路。"],
 ["实时与异步","SSE/事件流、异步作业、任务状态轮询降级、短期工作区票据","即使实时通道断开，任务状态仍可通过轮询恢复；异步失败支持重试与补偿。"],
 ["部署","本地 Docker Compose；P14 规划真实 Docker Swarm/可选 VM、HA、恢复和性能验收","答辩必须区分本地已验证与生产候选环境待验收，避免把规划内容表述成已完成。"]
],[16,43,41]));
children.push(...architectureSections);
children.push(heading("十 现场演示脚本"));
children.push(p("建议控制在 8—12 分钟，优先演示一条完整主链路；每一步都回答‘谁在什么页面做了什么，系统产生了什么可追踪结果’。"));
children.push(table(["时间","演示动作","讲解要点","证据截图/材料"],[
 ["0:00–0:40","项目总览","说明平台服务对象、核心痛点和完整闭环。","架构图/功能地图"],
 ["0:40–2:00","教师端进入课程","展示课程、章节、资料、实验模板及发布入口。","教师端课程页、发布页"],
 ["2:00–3:10","发布实验","展示先修、受众、时间窗和发布结果。","发布配置、发布记录"],
 ["3:10–4:10","用户端查看课程和我的实验","展示选课状态、个人任务、任务状态和有效时间窗。","课程目录、任务列表"],
 ["4:10–6:20","启动实验工作区","展示装载阶段、工作区、手册/IDE/终端/预览、自动保存和检查点。","工作区录屏、事件状态、保存记录"],
 ["6:20–7:20","报告提交与审核","展示报告、附件、提交和教师审核闭环。","报告页、审核记录"],
 ["7:20–8:30","Agent 与治理","展示带引用问答、工具审批或管理端异常/配额/运行时页面。","引用、审批、审计、运维看板"],
 ["8:30–10:00","总结与边界","总结个人贡献、质量证据、当前限制和下一步。","测试记录、仓库、项目文档"]
],[14,29,37,20]));
children.push(heading("十一 项目经理答辩重点"));
children.push(table(["评审方向","应准备的答辩材料","回答重点"],[
 ["进度与分工","项目计划、迭代看板、里程碑、成员分工、调整记录","如何拆分工作、如何识别延期、如何纠偏。"],
 ["需求管理","需求清单、需求—功能映射、验收标准、变更记录","如何把平台目标拆成可执行、可验收任务。"],
 ["过程管理","站会/计划会/回顾会纪要、行动项、决策日志","会议如何产生决策和闭环，而不是只签到。"],
 ["质量与仓库","分支策略、提交记录、README、测试结果、架构图","如何保证多人协作下的可维护性和质量。"],
 ["沟通协调","风险清单、问题闭环、跨模块协调记录","遇到依赖冲突或需求变化如何推动解决。"],
 ["现场汇报","答辩 PPT、数据看板、演示脚本、预演记录","用数据讲目标、进度、风险、结果，不回避边界。"]
],[22,43,35]));
children.push(heading("十二 开发人员答辩重点"));
children.push(table(["评审方向","应准备的答辩材料","回答重点"],[
 ["任务完成","个人任务卡、提交记录、演示视频、测试与缺陷关闭记录","我负责什么、完成到什么程度、如何证明可运行。"],
 ["需求理解","需求澄清、接口说明、需求—实现—测试对应关系","关键业务规则和边界条件是什么。"],
 ["技术设计","方案文档、流程图/时序图、设计评审记录","为什么这样设计，如何考虑扩展、异常和安全。"],
 ["代码质量","代表性代码、静态检查、Review 记录、重构对比","命名、结构、测试和可读性如何保证。"],
 ["AI 使用","AI 对话摘要、人工审核点、测试结果、关键代码解释","AI 做了什么、人做了什么、如何验证没有盲目复制。"],
 ["协作成长","联调记录、Code Review、复杂问题复盘、前后对比","如何主动同步、承担难题并证明成长。"]
],[22,43,35]));
children.push(heading("十三 常见答辩问题与参考回答"));
children.push(table(["问题","参考回答"],[
 ["项目最核心的创新或价值是什么？","核心价值不是单一页面，而是把课程、实验任务、工作区、报告审核和平台治理串成可追踪闭环，并将权限、审计、异步作业和 Agent 控制纳入同一平台。"],
 ["为什么要做三个端？","学生、教师和平台管理员的目标和权限不同。分端可以降低误操作和越权风险，同时让每个角色看到与其职责匹配的工作流。"],
 ["如何保证学生不能看到别人的实验？","后端每次读取和写入都重新检查门户、身份、课程关系、任务归属、实例状态和有效时间窗；前端隐藏不是最终安全边界。"],
 ["实验启动失败怎么办？","启动是异步装载流程，记录阶段、错误码、trace、重试和补偿；实时事件不可用时仍可轮询任务状态，避免页面状态与业务事实脱节。"],
 ["Agent 会不会替学生完成实验或改变成绩？","Agent 只提供受控辅助，回答尽量带课程知识引用；高风险工具需审批，Agent 不能直接改变任务状态、审核结果、配额或学生权益。"],
 ["目前是否已经完成生产部署？","当前仓库已具备本地 Compose 和业务链路验证；真实 Docker Swarm/VM、高可用、恢复、性能和全链路生产候选验收属于 P14 部署窗口，答辩时会明确区分。"],
 ["如何证明不是只做了页面？","通过后端 API、领域服务、状态机、权限测试、异步作业、审计/事件记录、前端 E2E 和可复现的本地验证脚本共同证明。"]
],[30,70]));
children.push(heading("十四 答辩前材料清单"));
children.push(...bullets(["1. 一页项目总览图：角色、三端、核心对象和业务闭环。","2. 一页功能地图：课程、实验发布、个人任务、工作区、报告审核、Agent、治理。","3. 一套主链路录屏：教师发布 → 学生任务 → 工作区 → 提交 → 审核。","4. 一套项目经理证据：计划、分工、需求拆解、会议纪要、风险与决策、仓库规范。","5. 一套开发人员证据：个人任务、提交记录、设计说明、测试报告、Code Review、AI 使用说明。","6. 一套质量与安全证据：权限测试、状态机测试、异常重试、审计记录、P13 本地验证结果。","7. 一页边界说明：本地已验证内容、FakeRuntime 范围、真实 Swarm/HA/性能待验收内容。","8. 备用材料：API 文档、数据库/架构图、关键代码、问题复盘和下一阶段计划。"]));
children.push(heading("十五 结尾陈述"));
children.push(p("本项目的完整性体现在三个方面：第一，围绕教学实验建立了从课程到审核的完整业务闭环；第二，围绕多人协作建立了权限、状态机、审计、异步任务和异常补偿机制；第三，围绕智能化建立了有引用、可评测、可审批、可追踪的 Agent 能力。答辩时我们将用一条真实可复现的主链路展示系统效果，同时明确当前本地验证范围和后续生产环境验收边界。"));

const doc = new Document({sections:[{properties:{page:{margin:{top:720,right:720,bottom:720,left:720}}},children}]});
await fs.writeFile(out, await Packer.toBuffer(doc));
console.log(out);
