"""Chinese content pools used to make the demo dataset read like a real school."""

from __future__ import annotations

from typing import Final

SURNAME_POOL: Final[str] = "张王李陈刘杨黄赵周吴郑孙马朱胡"
GIVEN_NAME_POOL: Final[str] = "雨轩晨曦浩然思远静怡博文佳琪启铭沐宸"


COURSE_DEFS: Final[list[dict[str, str]]] = [
    {
        "title": "数据结构与算法基础",
        "summary": "线性表、树、图与常用算法的容器化实验课。",
        "description": (
            "本课程通过容器化工作台完成数据结构与算法的动手实验，"
            "每个实验包含代码骨架、自动化测试与提交评阅。"
        ),
    },
    {
        "title": "操作系统与容器实践",
        "summary": "进程、内存、文件系统的容器实验与故障复现。",
        "description": "以容器实验为载体理解操作系统内核机制，实验强调可复现性与容错。",
    },
    {
        "title": "计算机网络协议分析",
        "summary": "TCP/IP 协议栈的抓包与网络编程实验。",
        "description": "围绕协议分层、拥塞控制和网络安全展开实验，报告需附抓包结论。",
    },
    {
        "title": "数据库系统原理",
        "summary": "SQL、事务隔离级别与索引优化的沙箱实验。",
        "description": "在隔离容器中对 MySQL 实例执行查询计划与事务实验。",
    },
    {
        "title": "Web 全栈开发入门",
        "summary": "从前端页面到 REST API 的全栈实作。",
        "description": "实验以个人站点为主线，覆盖前端框架、API 设计与部署脚本。",
    },
    {
        "title": "机器学习基础实践",
        "summary": "特征工程、回归与分类的最小可复现实验。",
        "description": "使用小型数据集完成端到端建模实验，并撰写实验报告。",
    },
    {
        "title": "Python 程序设计进阶",
        "summary": "函数式、迭代器与工程化模块设计练习。",
        "description": "通过迭代的小型算法实验巩固 Python 语言特性。",
    },
    {
        "title": "软件工程过程演练",
        "summary": "版本控制、评审与持续集成的协同实验。",
        "description": "以小组流程演练需求、提交与评阅闭环，任务包含协作规范检查。",
    },
    {
        "title": "编译原理与语言处理",
        "summary": "词法分析、语法树和中间代码生成实验。",
        "description": "从简单语言处理器入手，完成词法、语法和代码生成的分阶段实验。",
    },
    {
        "title": "信息安全攻防基础",
        "summary": "认证、加密和常见漏洞的隔离环境演练。",
        "description": "在安全沙箱中复现典型攻击并完成修复验证，强调合规实验边界。",
    },
    {
        "title": "数据可视化实践",
        "summary": "数据清洗、图表设计与交互式分析任务。",
        "description": "使用真实感小型数据集完成清洗、可视化和分析报告，关注可读性与复现性。",
    },
    {
        "title": "分布式系统入门",
        "summary": "服务发现、容错和一致性机制的模拟实验。",
        "description": "通过多节点实验理解分布式系统的通信、故障和恢复过程。",
    },
    {
        "title": "移动应用开发实践",
        "summary": "移动界面、网络请求与本地存储综合实验。",
        "description": "以跨平台移动应用为主线，完成页面交互、数据访问和发布检查。",
    },
    {
        "title": "人工智能伦理与治理",
        "summary": "模型风险、数据治理和可解释性案例分析。",
        "description": "结合实验案例分析模型偏差、隐私保护和上线治理要求，形成审查记录。",
    },
    {
        "title": "嵌入式系统设计",
        "summary": "传感器采集、实时任务和设备通信实验。",
        "description": "在模拟开发板环境中完成设备驱动、实时调度和通信协议练习。",
    },
    {
        "title": "云计算平台实践",
        "summary": "容器编排、服务部署与资源监控实验。",
        "description": "从镜像构建到服务编排完成云平台实践，记录资源和故障指标。",
    },
]

CHAPTER_TITLES: Final[list[str]] = [
    "环境准备与平台导览",
    "核心概念精讲",
    "动手实验一：基础练习",
    "动手实验二：进阶任务",
    "阶段复盘与常见问题",
]

MATERIAL_TITLES: Final[list[str]] = [
    "讲义：本周知识卡片",
    "实验指导书",
    "常见踩坑清单",
    "参考资料索引",
]

MATERIAL_BODY: Final[str] = (
    "本讲义梳理本次实验的目标、前置知识与评分要点。\n\n"
    "1. 阅读任务说明，确认提交物与作业窗口；\n"
    "2. 在容器工作台完成代码编辑并保存快照；\n"
    "3. 运行自动检查并核对结果；\n"
    "4. 撰写实验报告，说明实验步骤、数据处理与结论。\n\n"
    "如遇环境异常，先在工作台保存快照，再联系教师处理。"
)

LINK_MATERIALS: Final[list[tuple[str, str]]] = [
    ("课程参考资料（外部链接）", "https://developer.mozilla.org/zh-CN/"),
    ("Python 官方文档（外部链接）", "https://docs.python.org/"),
]

ANNOUNCEMENTS: Final[list[dict[str, object]]] = [
    {
        "title": "欢迎选修本课程（演示环境）",
        "body": "本课程为本地演示数据，实验任务在容器工作台完成，评阅会综合自动检查与人工评分。",
        "pinned": True,
    },
    {
        "title": "期中实验安排更新",
        "body": "期中实验的提交窗口已公布，请留意任务列表中的截止时间并在工作台及时保存快照。",
        "pinned": False,
    },
]

CALENDAR_EVENTS: Final[list[tuple[str, str]]] = [
    ("实验辅导答疑", "线上集中答疑，携带实验思路与问题清单。"),
    ("阶段成果分享", "展示典型实验方案与常见错误分析。"),
]

QUESTION_SAMPLES: Final[list[tuple[str, str]]] = [
    ("自动检查通过但报告没有分数，是为什么？", "自动检查通过后还需要等待教师完成人工评阅。"),
    ("工作台快照保存失败怎么办？", "先确认网络与权限，再重新保存；若持续失败请联系教师。"),
]

ASSISTANT_MESSAGES: Final[list[str]] = [
    "本实验的自动检查规则由教师配置，一次提交会运行一次规则。",
    "报告应包含实验步骤、数据处理、结果与结论四部分。",
    "可以通过保存快照记录关键节点的文件状态，便于回溯。",
    "实验窗口截止前请确认已提交报告版本。",
]

AGENT_QUESTIONS: Final[list[str]] = [
    "请帮我梳理本次实验的核心步骤。",
    "自动检查失败通常有哪些原因？",
    "报告里应该强调哪些内容？",
]

STUDENT_QUESTIONS: Final[list[str]] = [
    "自动检查会使用工作台最新快照吗？",
    "提交后可以撤回重新编辑报告吗？",
    "评阅给出的分数如何计算总分？",
]

REPORT_BODIES: Final[list[str]] = [
    (
        "# 实验报告\n\n"
        "## 实验步骤\n\n"
        "1. 依照指导书完成环境准备；\n2. 在工作台编辑代码并保存快照；\n3. 运行自动检查。\n\n"
        "## 数据处理\n\n整理了运行输出并核对用例结果，未出现异常资源占用。\n\n"
        "## 结论\n\n实验目标达成，自动检查通过，结论与指导书预期一致。"
    ),
    (
        "# {task}实验记录\n\n"
        "## 过程\n\n按章节内容逐节完成练习，关键文件已保存工作区快照。\n\n"
        "## 遇到的问题\n\n第一次运行超时，调整实现后通过。\n\n"
        "## 小结\n\n完成全部目标用例，输出与预期一致。"
    ),
]

RESUBMIT_BODY: Final[str] = (
    "# 实验报告（修订版）\n\n"
    "## 修订说明\n\n根据评阅意见补充数据处理细节，重新核对自动检查输出。\n\n"
    "## 结论\n\n实验结论保持，报告已补齐分析内容。"
)

REVIEW_FEEDBACK_APPROVE: Final[str] = (
    "自动检查与人工评阅均通过，报告结构完整，数据处理清晰。"
)

REVIEW_FEEDBACK_REJECT: Final[str] = (
    "报告缺少数据处理与结论部分，请补充后重新提交。"
)

REVIEW_ANNOTATION: Final[str] = "建议补充运行截图或关键输出说明。"

EXTENSION_REASONS: Final[list[str]] = [
    "设备暂停使用，申请顺延实验窗口。",
    "参与学科竞赛冲突，申请延长两天提交。",
]

AI_PROMPTS_HINT: Final[str] = "课程助手仅依据已索引的课程资料回答，不接触未过的资料。"

GRADINGS: Final[list[tuple[str, str, int]]] = [
    ("功能正确性", "检查实验结果与自动检查输出。", 60),
    ("报告质量", "检查报告完整性、可复现性与表达。", 30),
    ("过程规范", "检查工作台操作与提交规范。", 10),
]
