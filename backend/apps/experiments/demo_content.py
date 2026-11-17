# ruff: noqa: E501
"""Content for the 数据结构与算法（Python） demo course.

Chapter topics follow the open-source book Hello 算法 (hello-algo.com); the
prose here is written for this demo and is not copied from the book.
"""

COURSE = {
    "code": "ALGO-PY-2026F",
    "title": "数据结构与算法（Python）",
    "summary": "以 Python 为主线，系统学习复杂度分析、线性结构、树与图、查找排序以及分治、回溯、动态规划与贪心。",
    "description": (
        "本课程面向已经掌握 Python 基础语法的一年级学生。课程以“先建立直觉，再推导复杂度，最后落到代码”"
        "的顺序组织：每个章节先给出真实问题与图示，再讨论数据结构的选择依据，最后完成可运行的 Python 实现。"
        "课程包含 12 个章节、3 次编程实验与 1 次综合报告，实验在本地容器中真实编译运行并依据隐藏用例评分。"
    ),
    "term": ("2026-2027-1", "2026-2027 学年秋季学期"),
}

CHAPTERS = [
    {
        "title": "第 1 章 算法与复杂度分析",
        "summary": "理解算法的定义与评价方式，掌握大 O 记号、时间与空间复杂度的估算方法。",
        "content": """
## 本章导读

算法是解决特定问题的一系列明确指令。同一个问题往往有多种解法：从 1 加到 n，可以写循环，也可以用求和公式。
评价解法优劣不能只看代码长短，而要看随着输入规模增大，运行时间与额外空间如何增长。

## 学习目标

- 能说清“正确性、可读性、时间复杂度、空间复杂度”四项评价标准。
- 能对单层循环、双层循环、递归函数写出大 O 复杂度。
- 能区分最好、最坏与平均情况，并知道常见增长阶的排序。

## 核心概念

- **时间复杂度**：基本操作执行次数随输入规模 n 的增长趋势，记作 O(f(n))。
- **空间复杂度**：除输入外额外占用的存储随 n 的增长趋势。
- **渐近上界**：忽略常数与低阶项，只保留增长最快的一项。

## 常见增长阶

| 阶 | 名称 | 典型场景 |
| --- | --- | --- |
| O(1) | 常数阶 | 数组按下标访问、哈希表平均查找 |
| O(log n) | 对数阶 | 二分查找、平衡树查找 |
| O(n) | 线性阶 | 一次遍历、链表遍历 |
| O(n log n) | 线性对数阶 | 归并排序、堆排序 |
| O(n²) | 平方阶 | 双重循环、冒泡排序 |

## 易错点

1. 嵌套循环不一定就是 O(n²)，要看内层循环的边界是否依赖外层变量。
2. 递归的复杂度要同时考虑调用次数与单次调用的工作量。
3. 空间复杂度统计的是额外空间，输入本身通常不计入。
""",
        "hello_chapter": "chapter_complexity_analysis",
        "material": "复杂度分析是后续所有章节的共同语言。阅读本章时，建议把每段示例代码的基本操作次数写在纸上，再与运行结果对照。",
    },
    {
        "title": "第 2 章 数组与链表",
        "summary": "对比连续存储与链式存储的访问、插入、删除代价，理解 Python list 的底层取舍。",
        "content": """
## 本章导读

数组把元素放在一段连续内存中，因此可以 O(1) 随机访问；链表用指针把分散的节点串起来，因此插入删除只需改指针。
两者的差异不是“谁更高级”，而是“把代价放在读还是写”。

## 学习目标

- 能手写数组的插入、删除，并分析元素搬移次数。
- 能实现单链表、双向链表，完成头插、尾插、删除与反转。
- 能解释 Python list 的扩容策略对均摊复杂度的影响。

## 核心操作对比

| 操作 | 数组 | 链表 |
| --- | --- | --- |
| 按下标访问 | O(1) | O(n) |
| 头部插入 | O(n) | O(1) |
| 尾部插入 | O(1) 均摊 | O(1)（维护尾指针） |
| 中间插入/删除 | O(n) | O(n) 查找 + O(1) 改指针 |

## Python 中的数组

Python 的 `list` 是动态数组：容量不足时按一定比例扩容，并把旧元素复制到新空间。单次扩容是 O(n)，
但连续 n 次追加的总代价是 O(n)，因此尾插的**均摊复杂度**为 O(1)。

## 编程提示

- 遍历链表时先保存 `next`，再修改指针，避免断链。
- 删除节点要处理头节点这一边界。
- 数组删除后，后续元素必须前移，不能留下“空洞”。
""",
        "hello_chapter": "chapter_array_and_linkedlist",
        "material": "建议先用纸笔画出数组扩容与链表反转的指针变化，再写代码。指针题的错误大多来自顺序问题，而不是语法。",
    },
    {
        "title": "第 3 章 栈与队列",
        "summary": "掌握后进先出与先进先出两种受限线性结构，理解它们在表达式求值、括号匹配与 BFS 中的作用。",
        "content": """
## 本章导读

栈和队列都是“操作受限的线性表”。栈只允许在顶部进出，队列只允许在队尾进、队头出。
限制反而带来清晰的语义：栈适合处理“最近出现的、尚未配对”的对象，队列适合按到达顺序公平处理。

## 学习目标

- 用数组或链表实现栈、队列与双向队列。
- 用栈完成括号匹配、后缀表达式求值。
- 用队列完成二叉树的层序遍历与图的广度优先遍历。
- 说明循环队列如何解决数组队列的“假溢出”。

## 典型应用

- **栈**：函数调用栈、撤销操作、括号匹配、单调栈求下一个更大元素。
- **队列**：任务调度、消息缓冲、BFS、滑动窗口最大值（单调队列）。

## 复杂度

| 结构 | 入 | 出 | 查看 | 适用 |
| --- | --- | --- | --- | --- |
| 栈 | O(1) | O(1) | O(1) | 后进先出 |
| 队列 | O(1) | O(1) | O(1) | 先进先出 |
| 双向队列 | O(1) | O(1) | O(1) | 两端操作 |

## 易错点

- 出栈、出队前必须判空。
- 用 Python list 模拟队列时，`pop(0)` 是 O(n)，大规模数据应使用 `collections.deque`。
""",
        "hello_chapter": "chapter_stack_and_queue",
        "material": "括号匹配是栈的经典练习：遇到左括号入栈，遇到右括号检查栈顶是否配对。请补全三种括号混用的情形。",
    },
    {
        "title": "第 4 章 哈希表",
        "summary": "理解哈希函数、冲突处理与负载因子，能用哈希表把查找从 O(n) 降到平均 O(1)。",
        "content": """
## 本章导读

哈希表通过哈希函数把键映射到桶下标，从而绕过逐个比较。它的平均性能极好，但最坏情况会退化，
并且需要处理冲突、扩容与哈希攻击等问题。

## 学习目标

- 解释哈希函数、桶、冲突、负载因子的含义。
- 说出链地址法与开放寻址法的差异与适用场景。
- 用字典完成两数之和、去重、计数、分组等常见任务。
- 理解“用空间换时间”的边界。

## 冲突处理

- **链地址法**：每个桶挂一条链表（或红黑树），冲突元素追加其后。实现简单，删除方便。
- **开放寻址法**：冲突时按探测序列寻找下一个空位。缓存友好，但对负载因子敏感。

## 复杂度

| 操作 | 平均 | 最坏 |
| --- | --- | --- |
| 查找 | O(1) | O(n) |
| 插入 | O(1) | O(n) |
| 删除 | O(1) | O(n) |

## 工程要点

1. 负载因子过高会显著增加冲突，通常超过 0.75 就扩容。
2. 键必须可哈希且不可变；列表不能直接作为字典的键。
3. 哈希表不保证遍历顺序，不能依赖插入顺序做业务判断（除非使用有序容器）。
""",
        "hello_chapter": "chapter_hashing",
        "material": "“两数之和”是哈希表最典型的入门题：遍历时把已见过的值存入字典，把查找从 O(n²) 降到 O(n)。",
    },
    {
        "title": "第 5 章 二叉树与二叉搜索树",
        "summary": "掌握树的基本术语、四种遍历方式，以及二叉搜索树的查找、插入与删除规则。",
        "content": """
## 本章导读

树用层次关系组织数据。二叉树每个节点最多两个子节点，结构简单却足以表达表达式、文件目录、
组织架构与搜索索引。二叉搜索树进一步利用“左小右大”的次序，把查找变成一次有方向的下降。

## 学习目标

- 说清根、叶、深度、高度、度等术语。
- 写出前序、中序、后序、层序四种遍历。
- 在二叉搜索树中完成查找、插入、删除，并说明删除双子节点的处理。
- 理解退化成链表的风险与平衡树的必要性。

## 遍历方式

- **前序**：根 → 左 → 右，适合复制结构。
- **中序**：左 → 根 → 右，二叉搜索树的中序结果有序。
- **后序**：左 → 右 → 根，适合释放节点、计算子树结果。
- **层序**：借助队列逐层访问。

## 二叉搜索树

对任意节点，左子树所有值小于它，右子树所有值大于它。查找、插入平均 O(log n)；
若插入序列有序，树会退化为链表，复杂度变成 O(n)。

## 删除的三种情况

1. 叶子节点：直接删除。
2. 只有一个子节点：用子节点替代。
3. 有两个子节点：用中序后继（右子树最小值）替代，再删除后继。
""",
        "hello_chapter": "chapter_tree",
        "material": "画出一棵 7 个节点的二叉搜索树，分别写出前序、中序、后序与层序结果，再与代码输出对照。",
    },
    {
        "title": "第 6 章 堆与优先队列",
        "summary": "理解完全二叉树与堆序性质，能手写上浮、下沉，并用堆解决 Top-k 与优先级调度。",
        "content": """
## 本章导读

堆是一棵满足“父节点总是不大于（或不小于）子节点”的完全二叉树。它不保证整体有序，
却能以 O(1) 取到最值、以 O(log n) 插入与删除最值，因此成为优先队列的标准实现。

## 学习目标

- 用数组表示完全二叉树，写出父子下标关系。
- 实现大顶堆的插入（上浮）与删除堆顶（下沉）。
- 用 O(n) 的建堆方法初始化堆。
- 用大小为 k 的堆求 Top-k，并分析复杂度。

## 下标关系

对下标 i（从 0 开始）：父节点 `(i-1)//2`，左孩子 `2*i+1`，右孩子 `2*i+2`。

## 复杂度

| 操作 | 复杂度 |
| --- | --- |
| 查看堆顶 | O(1) |
| 插入 | O(log n) |
| 删除堆顶 | O(log n) |
| 建堆 | O(n) |

## Top-k 思路

求最大的 k 个数时维护一个大小为 k 的**小顶堆**：新元素大于堆顶才替换堆顶并下沉。
最终堆中就是最大的 k 个元素，时间复杂度 O(n log k)，空间 O(k)。
""",
        "hello_chapter": "chapter_heap",
        "material": "思考：求“第 k 大”与求“最大的 k 个”分别该用小顶堆还是大顶堆？把结论写下来再验证。",
    },
    {
        "title": "第 7 章 图与遍历",
        "summary": "掌握图的邻接矩阵与邻接表表示，理解 BFS、DFS 的访问顺序与适用问题。",
        "content": """
## 本章导读

图由顶点和边组成，可以表达社交网络、课程先修关系、道路与依赖。图的算法首先取决于表示方式：
邻接矩阵适合稠密图，邻接表适合稀疏图。

## 学习目标

- 区分有向/无向、带权/无权、连通/非连通图。
- 用邻接表和邻接矩阵存储图，并分析空间代价。
- 写出 BFS 与 DFS，说明 visited 集合的必要性。
- 用 BFS 求无权图最短路，用 DFS 判断连通分量与环。

## 两种表示

| 表示 | 空间 | 判断边 | 遍历邻居 |
| --- | --- | --- | --- |
| 邻接矩阵 | O(V²) | O(1) | O(V) |
| 邻接表 | O(V+E) | O(deg) | O(deg) |

## 遍历要点

- BFS 使用队列，按层扩展，第一次到达某点即为无权最短路。
- DFS 使用递归或显式栈，适合探索所有路径、拓扑排序与连通性判断。
- 访问标记必须在入队/入栈时设置，否则会重复入队。
""",
        "hello_chapter": "chapter_graph",
        "material": "给定 6 个顶点与 7 条边，分别写出邻接表、从 0 出发的 BFS 序列与 DFS 序列。",
    },
    {
        "title": "第 8 章 搜索与二分查找",
        "summary": "掌握二分查找的循环不变式、插入点与边界写法，理解哈希与二分各自的适用场景。",
        "content": """
## 本章导读

搜索是在数据集合中定位目标的过程。线性搜索简单但慢；二分查找利用有序性，把范围每次减半；
哈希表则用额外空间换取平均常数时间。选择哪一种，取决于数据是否有序、是否频繁更新。

## 学习目标

- 写出不会死循环的二分查找。
- 求目标值的插入点（第一个大于等于目标的位置）。
- 求左右边界（第一个等于、最后一个等于）。
- 说明二分查找对“有序 + 随机访问”的依赖。

## 模板

```python
lo, hi = 0, len(nums)          # 左闭右开
while lo < hi:
    mid = (lo + hi) // 2
    if nums[mid] < target:
        lo = mid + 1
    else:
        hi = mid
return lo                       # 第一个 >= target 的下标
```

## 复杂度与边界

- 时间 O(log n)，空间 O(1)。
- 循环结束条件、区间开闭、mid 取整方式必须配套，三者混用是死循环的主要来源。
- 二分查找要求随机访问；链表即使有序也无法高效二分。
""",
        "hello_chapter": "chapter_searching",
        "material": "把“查找目标”改成“查找插入点”，代码只差一个判断，但边界含义完全不同。请用空数组、单元素、目标在两端各验证一次。",
    },
    {
        "title": "第 9 章 排序算法",
        "summary": "比较插入、冒泡、选择、归并、快速与堆排序的时间、空间与稳定性，能按场景选型。",
        "content": """
## 本章导读

排序是许多算法的前置步骤。没有一种排序在所有维度都最优：有的快但不稳定，有的稳定但需要额外空间，
有的最坏情况会退化。理解取舍比背代码更重要。

## 学习目标

- 说出比较排序的下界为什么是 O(n log n)。
- 手写插入排序、归并排序、快速排序。
- 判断排序算法的稳定性与额外空间。
- 根据数据规模、有序程度、内存限制选择算法。

## 对比

| 算法 | 平均 | 最坏 | 空间 | 稳定 |
| --- | --- | --- | --- | --- |
| 插入排序 | O(n²) | O(n²) | O(1) | 是 |
| 归并排序 | O(n log n) | O(n log n) | O(n) | 是 |
| 快速排序 | O(n log n) | O(n²) | O(log n) | 否 |
| 堆排序 | O(n log n) | O(n log n) | O(1) | 否 |

## 工程建议

- 小数组用插入排序，大数组用归并或快排。
- 快排要随机化基准或三数取中，避免有序输入退化。
- Python 内置 `sorted` 使用 Timsort，对部分有序数据接近线性。
""",
        "hello_chapter": "chapter_sorting",
        "material": "用同一组含重复元素的数组分别跑归并与快排，记录比较次数与结果稳定性，再解释差异。",
    },
    {
        "title": "第 10 章 分治与回溯",
        "summary": "掌握“分解—解决—合并”的分治框架与“选择—探索—撤销”的回溯框架。",
        "content": """
## 本章导读

分治把大问题拆成相互独立的子问题，回溯则在一棵决策树上做深度优先搜索，并在失败时撤销选择。
两者都依赖递归，但分治的子问题不重叠，回溯的关键是状态恢复与剪枝。

## 学习目标

- 用分治完成归并排序、快速幂、汉诺塔。
- 用回溯完成全排列、子集、组合总和与 N 皇后。
- 说清递归出口、选择列表、路径与剪枝条件。
- 分析回溯的时间复杂度上界。

## 回溯模板

```python
def backtrack(path, choices):
    if 满足结束条件:
        result.append(path[:])
        return
    for choice in choices:
        if 不合法: continue
        path.append(choice)      # 做选择
        backtrack(path, 剩余选择) # 递归
        path.pop()               # 撤销选择
```

## 分治与回溯的区别

| 维度 | 分治 | 回溯 |
| --- | --- | --- |
| 子问题 | 相互独立、可合并 | 共享路径、需要撤销 |
| 搜索空间 | 通常更小 | 指数级，依赖剪枝 |
| 典型题 | 归并排序、汉诺塔 | 全排列、N 皇后 |
""",
        "hello_chapter": "chapter_divide_and_conquer",
        "material": "先画出 N=4 的全排列决策树，标出每一层的选择与撤销，再写代码，能显著减少调试时间。",
    },
    {
        "title": "第 11 章 动态规划",
        "summary": "从重叠子问题与最优子结构出发，掌握状态定义、转移方程、初始化与遍历顺序。",
        "content": """
## 本章导读

动态规划适合“子问题重叠 + 最优子结构”的问题。它把递归中的重复计算记录下来，
用一张表按顺序推出答案。难点通常不在写循环，而在定义出无后效性的状态。

## 学习目标

- 判断一个问题是否适合动态规划。
- 写出 0-1 背包、完全背包、最长公共子序列、编辑距离的状态与转移。
- 区分自顶向下记忆化与自底向上递推。
- 用滚动数组压缩空间。

## 解题四步

1. **定义状态**：`dp[i][j]` 表示什么，必须能覆盖全部决策。
2. **写转移**：当前状态由哪些更小的状态得到。
3. **初始化**：边界状态的含义与取值。
4. **确定顺序**：保证用到的状态已经算好。

## 0-1 背包

`dp[j] = max(dp[j], dp[j-w] + v)`，j 必须**从大到小**遍历，保证每件物品只用一次。
完全背包则从小到大遍历，允许重复选取。

## 常见误区

- 状态定义遗漏维度，导致无法区分“选过”与“没选过”。
- 遍历顺序与状态依赖方向相反。
- 把“恰好装满”和“至多容量”的初始化混为一谈。
""",
        "hello_chapter": "chapter_dynamic_programming",
        "material": "同一道 0-1 背包，先用二维表写清楚，再压缩成一维。压缩后 j 的遍历方向为什么必须反过来？",
    },
    {
        "title": "第 12 章 贪心算法",
        "summary": "理解贪心选择性质与最优子结构，能用交换论证判断贪心是否成立。",
        "content": """
## 本章导读

贪心在每一步选择当前看起来最好的方案，不回退。它实现简单、效率高，但只在满足贪心选择性质时正确。
因此学习贪心的重点不是背题，而是学会证明或反证“局部最优能否推出全局最优”。

## 学习目标

- 说出贪心与动态规划的联系与区别。
- 用贪心解决分数背包、区间调度、跳跃游戏、最大切分乘积。
- 用交换论证或反例判断贪心策略是否正确。
- 知道需要排序的贪心题应按什么关键字排序。

## 典型问题

- **分数背包**：按单位价值从高到低装入，可分割。
- **区间调度**：按结束时间升序选择，给后续留出最多空间。
- **跳跃游戏**：维护当前能到达的最远位置。

## 贪心 vs 动态规划

| 维度 | 贪心 | 动态规划 |
| --- | --- | --- |
| 决策 | 每步只选一个，不回退 | 枚举并比较多个子问题 |
| 正确性 | 需要证明 | 依赖状态转移 |
| 复杂度 | 通常 O(n log n) | 通常 O(n²) 或更高 |

## 提醒

0-1 背包不能贪心：按单位价值排序会得到错误答案。遇到“不可分割 + 容量约束”时优先考虑动态规划。
""",
        "hello_chapter": "chapter_greedy",
        "material": "为区间调度构造一个反例：如果按开始时间最早选择，为什么可能错过更优解？",
    },
]

ANNOUNCEMENTS = [
    {
        "title": "课程导学与实验环境说明",
        "body": (
            "欢迎选修数据结构与算法（Python）。课程实验在浏览器内完成，代码在隔离容器中编译运行，"
            "请先在“我的课程”中确认已加入课程，再进入实验列表。实验支持多次保存，正式提交后以最后一次有效提交为准。"
        ),
        "pinned": True,
    },
    {
        "title": "第一次编程实验已发布",
        "body": "实验一（线性结构基础）为选择题，截止前可反复修改；实验二包含编程题与实验报告，请预留充足时间。",
        "pinned": False,
    },
]

CALENDAR_EVENTS = [
    ("第一次习题课：复杂度与线性结构", "讲解大 O 估算、数组与链表的取舍，并现场演示实验一。", -7, 2),
    ("实验二答疑", "针对二叉树遍历与二分查找边界进行集中答疑。", 3, 2),
    ("期中复习", "覆盖第 1—8 章，重点为树、堆与图。", 14, 2),
]

QA = [
    (
        "为什么 Python 的 list 尾部追加是 O(1)，而头部插入是 O(n)？",
        "列表底层是连续内存。尾部追加只在容量不足时扩容，均摊 O(1)；头部插入需要把后面所有元素整体后移一位，因此是 O(n)。",
    ),
    (
        "二叉搜索树和哈希表都能查找，什么时候选哪一个？",
        "需要范围查询、有序遍历或前驱后继时选二叉搜索树；只做等值查找且追求平均常数时间时选哈希表。",
    ),
    (
        "动态规划的一维滚动数组为什么有时要倒序遍历？",
        "0-1 背包中每个物品只能用一次，倒序保证 `dp[j-w]` 仍是上一轮的状态；正序会让同一物品被重复使用。",
    ),
]

STUDENTS = [
    ("stu2026001", "王远浩"),
    ("stu2026002", "李思远"),
    ("stu2026003", "陈雨桐"),
    ("stu2026004", "赵子涵"),
    ("stu2026005", "周佳宁"),
    ("stu2026006", "吴嘉懿"),
    ("stu2026007", "徐若曦"),
    ("stu2026008", "孙一鸣"),
    ("stu2026009", "马晓彤"),
    ("stu2026010", "朱天佑"),
    ("stu2026011", "胡明轩"),
    ("stu2026012", "郭芷晴"),
]

CHOICE = "SINGLE_CHOICE"
MULTI = "MULTIPLE_CHOICE"
PROGRAMMING = "PROGRAMMING"


def _opt(identifier: str, text: str) -> dict:
    return {"id": identifier, "text": text}


PROGRAMMING_TASKS = {
    "two_sum": {
        "title": "两数之和",
        "description": "给定一个整数数组和目标值，返回和为目标值的两个元素下标（下标从 0 开始，i < j）。若不存在，输出 -1。",
        "instructions": "第一行输入 n，第二行输入 n 个整数，第三行输入目标值。输出两个下标，以空格分隔。",
        "samples": [{"input": "4\n2 7 11 15\n9\n", "output": "0 1\n"}],
        "tests": [
            {"id": "basic", "cases": [
                {"input": "4\n2 7 11 15\n9\n", "output": "0 1\n"},
                {"input": "3\n3 2 4\n6\n", "output": "1 2\n"},
            ], "score": "6"},
            {"id": "edge", "cases": [
                {"input": "2\n3 3\n6\n", "output": "0 1\n"},
                {"input": "3\n1 2 3\n7\n", "output": "-1\n"},
            ], "score": "4"},
        ],
        "reference": "n = int(input())\nnums = list(map(int, input().split()))\ntarget = int(input())\nseen = {}\nfor i, value in enumerate(nums):\n    if target - value in seen:\n        print(seen[target - value], i)\n        break\n    seen[value] = i\nelse:\n    print(-1)\n",
        "starter": "n = int(input())\nnums = list(map(int, input().split()))\ntarget = int(input())\n# TODO: 使用哈希表在 O(n) 内找到答案\n",
    },
    "valid_parentheses": {
        "title": "有效括号",
        "description": "给定只包含 ()[]{} 的字符串，判断括号是否按正确顺序闭合。",
        "instructions": "输入一行字符串，输出 true 或 false。",
        "samples": [{"input": "()[]{}\n", "output": "true\n"}],
        "tests": [
            {"id": "basic", "cases": [
                {"input": "()[]{}\n", "output": "true\n"},
                {"input": "([)]\n", "output": "false\n"},
            ], "score": "6"},
            {"id": "edge", "cases": [
                {"input": "{[]}\n", "output": "true\n"},
                {"input": "(\n", "output": "false\n"},
                {"input": "\n", "output": "true\n"},
            ], "score": "4"},
        ],
        "reference": "s = input()\npairs = {')': '(', ']': '[', '}': '{'}\nstack = []\nfor ch in s:\n    if ch in '([{':\n        stack.append(ch)\n    elif ch in pairs:\n        if not stack or stack.pop() != pairs[ch]:\n            print('false')\n            break\nelse:\n    print('true' if not stack else 'false')\n",
        "starter": "s = input()\n# TODO: 用栈匹配括号\n",
    },
    "tree_depth": {
        "title": "二叉树的最大深度",
        "description": "给定按层序排列的二叉树（null 表示空节点），求树的最大深度。",
        "instructions": "第一行输入节点数 n，第二行输入 n 个 token（整数或 null）。输出最大深度。",
        "samples": [{"input": "7\n3 9 20 null null 15 7\n", "output": "3\n"}],
        "tests": [
            {"id": "basic", "cases": [
                {"input": "7\n3 9 20 null null 15 7\n", "output": "3\n"},
                {"input": "3\n1 null 2\n", "output": "2\n"},
            ], "score": "6"},
            {"id": "edge", "cases": [
                {"input": "1\n1\n", "output": "1\n"},
                {"input": "0\n\n", "output": "0\n"},
            ], "score": "4"},
        ],
        "reference": "n = int(input())\ntokens = input().split() if n else []\nif not tokens or tokens[0] == 'null':\n    print(0)\nelse:\n    depth = 0\n    level = [0]\n    while level:\n        depth += 1\n        nxt = []\n        for i in level:\n            if 2 * i + 1 < n and tokens[2 * i + 1] != 'null':\n                nxt.append(2 * i + 1)\n            if 2 * i + 2 < n and tokens[2 * i + 2] != 'null':\n                nxt.append(2 * i + 2)\n        level = nxt\n    print(depth)\n",
        "starter": "n = int(input())\ntokens = input().split() if n else []\n# TODO: 计算层序数组表示下的最大深度\n",
    },
    "lower_bound": {
        "title": "二分查找插入点",
        "description": "在升序数组中查找第一个大于等于目标值的元素下标；若所有元素都小于目标，输出数组长度。",
        "instructions": "第一行输入 n，第二行输入 n 个升序整数，第三行输入目标值。输出插入点下标。",
        "samples": [{"input": "5\n1 3 5 7 9\n5\n", "output": "2\n"}],
        "tests": [
            {"id": "basic", "cases": [
                {"input": "5\n1 3 5 7 9\n5\n", "output": "2\n"},
                {"input": "5\n1 3 5 7 9\n6\n", "output": "3\n"},
            ], "score": "6"},
            {"id": "edge", "cases": [
                {"input": "5\n1 3 5 7 9\n0\n", "output": "0\n"},
                {"input": "5\n1 3 5 7 9\n10\n", "output": "5\n"},
                {"input": "0\n\n1\n", "output": "0\n"},
            ], "score": "4"},
        ],
        "reference": "n = int(input())\nnums = list(map(int, input().split()))\ntarget = int(input())\nlo, hi = 0, n\nwhile lo < hi:\n    mid = (lo + hi) // 2\n    if nums[mid] < target:\n        lo = mid + 1\n    else:\n        hi = mid\nprint(lo)\n",
        "starter": "n = int(input())\nnums = list(map(int, input().split()))\ntarget = int(input())\n# TODO: 二分查找第一个 >= target 的位置\n",
    },
    "merge_sort": {
        "title": "归并排序",
        "description": "给定整数数组，使用归并排序输出升序结果。",
        "instructions": "第一行输入 n，第二行输入 n 个整数。输出升序排列，以空格分隔。",
        "samples": [{"input": "5\n5 2 9 1 5\n", "output": "1 2 5 5 9\n"}],
        "tests": [
            {"id": "basic", "cases": [
                {"input": "5\n5 2 9 1 5\n", "output": "1 2 5 5 9\n"},
                {"input": "1\n42\n", "output": "42\n"},
            ], "score": "6"},
            {"id": "edge", "cases": [
                {"input": "6\n-1 0 -1 3 2 0\n", "output": "-1 -1 0 0 2 3\n"},
                {"input": "4\n9 8 7 6\n", "output": "6 7 8 9\n"},
            ], "score": "4"},
        ],
        "reference": "import sys\n\ndef merge_sort(a):\n    if len(a) <= 1:\n        return a\n    mid = len(a) // 2\n    left, right = merge_sort(a[:mid]), merge_sort(a[mid:])\n    out, i, j = [], 0, 0\n    while i < len(left) and j < len(right):\n        if left[i] <= right[j]:\n            out.append(left[i]); i += 1\n        else:\n            out.append(right[j]); j += 1\n    out.extend(left[i:]); out.extend(right[j:])\n    return out\n\ndata = sys.stdin.read().split()\nn = int(data[0])\nnums = list(map(int, data[1:1 + n]))\nprint(*merge_sort(nums))\n",
        "starter": "import sys\n\ndata = sys.stdin.read().split()\nn = int(data[0])\nnums = list(map(int, data[1:1 + n]))\n# TODO: 实现归并排序\nprint(*nums)\n",
    },
    "knapsack": {
        "title": "0-1 背包",
        "description": "给定 n 件物品的重量与价值，以及背包容量，求不超过容量时能获得的最大总价值。",
        "instructions": "第一行输入 n 和容量 capacity，接下来 n 行每行输入重量和价值。输出最大总价值。",
        "samples": [{"input": "3 4\n1 15\n3 20\n4 30\n", "output": "35\n"}],
        "tests": [
            {"id": "basic", "cases": [
                {"input": "3 4\n1 15\n3 20\n4 30\n", "output": "35\n"},
                {"input": "4 5\n2 3\n3 4\n4 5\n5 6\n", "output": "7\n"},
            ], "score": "6"},
            {"id": "edge", "cases": [
                {"input": "1 1\n2 100\n", "output": "0\n"},
                {"input": "2 3\n1 1\n2 3\n", "output": "4\n"},
            ], "score": "4"},
        ],
        "reference": "import sys\n\ntokens = list(map(int, sys.stdin.read().split()))\nn, capacity = tokens[0], tokens[1]\ndp = [0] * (capacity + 1)\nidx = 2\nfor _ in range(n):\n    weight, value = tokens[idx], tokens[idx + 1]\n    idx += 2\n    for cap in range(capacity, weight - 1, -1):\n        dp[cap] = max(dp[cap], dp[cap - weight] + value)\nprint(dp[capacity])\n",
        "starter": "import sys\n\ntokens = list(map(int, sys.stdin.read().split()))\nn, capacity = tokens[0], tokens[1]\n# TODO: 一维动态规划，注意容量倒序遍历\nprint(0)\n",
    },
}

EXPERIMENTS = [
    {
        "code": "EXP1",
        "name": "实验一：线性结构基础",
        "category": "线性结构",
        "description": "覆盖复杂度、数组与链表、栈与队列、哈希表的概念辨析，全部为客观题，适合作为第一次随堂实验。",
        "course_chapters": [0, 1, 2, 3],
        "report_required": False,
        "window_days": (-14, 1),
        "close_after_seed": True,
        "chapters": [
            {
                "title": "概念辨析",
                "description": "复杂度、存储结构与容器语义。",
                "objectives": ["估算常见代码的复杂度", "区分数组与链表的代价", "说明栈与哈希表的适用范围"],
                "tasks": [
                    {
                        "type": CHOICE,
                        "title": "双重循环的复杂度",
                        "description": "下面代码的时间复杂度是什么？\n\n```python\nfor i in range(n):\n    for j in range(i):\n        total += 1\n```",
                        "options": [("a", "O(n)"), ("b", "O(n log n)"), ("c", "O(n²)"), ("d", "O(2ⁿ)")],
                        "correct": ["c"],
                        "explanation": "总次数约为 n(n-1)/2，忽略常数与低阶项后为 O(n²)。",
                        "score": "5",
                    },
                    {
                        "type": CHOICE,
                        "title": "头部插入的代价",
                        "description": "在长度为 n 的数组头部插入一个元素，时间复杂度是？",
                        "options": [("a", "O(1)"), ("b", "O(log n)"), ("c", "O(n)"), ("d", "O(n²)")],
                        "correct": ["c"],
                        "explanation": "数组头部插入需要把原有 n 个元素整体后移一位。",
                        "score": "5",
                    },
                    {
                        "type": MULTI,
                        "title": "关于链表的正确说法",
                        "description": "选择所有正确的说法。",
                        "options": [
                            ("a", "单链表按下标访问是 O(n)"),
                            ("b", "已知前驱节点时，链表删除是 O(1)"),
                            ("c", "链表节点在内存中必须连续"),
                            ("d", "双向链表可以 O(1) 找到前驱"),
                        ],
                        "correct": ["a", "b", "d"],
                        "explanation": "链表节点通过指针连接，不要求连续存储。",
                        "score": "5",
                    },
                    {
                        "type": CHOICE,
                        "title": "不可能的出栈序列",
                        "description": "元素 1、2、3、4 依次入栈，允许在任意时刻出栈。下列哪个序列不可能是出栈序列？",
                        "options": [("a", "4 3 2 1"), ("b", "1 2 3 4"), ("c", "4 1 2 3"), ("d", "2 1 4 3")],
                        "correct": ["c"],
                        "explanation": "4 先出栈说明 1、2、3 仍在栈中，出栈顺序只能是 3、2、1。",
                        "score": "5",
                    },
                    {
                        "type": CHOICE,
                        "title": "哈希表的平均查找复杂度",
                        "description": "在负载因子受控且哈希函数均匀的前提下，哈希表查找的平均时间复杂度是？",
                        "options": [("a", "O(1)"), ("b", "O(log n)"), ("c", "O(n)"), ("d", "O(n log n)")],
                        "correct": ["a"],
                        "explanation": "平均情况下每个桶的元素个数为常数，因此查找为 O(1)；最坏情况仍可能退化到 O(n)。",
                        "score": "5",
                    },
                ],
            }
        ],
    },
    {
        "code": "EXP2",
        "name": "实验二：树、堆与查找",
        "category": "非线性结构",
        "description": "包含二叉树、堆、图与二分查找的客观题，以及两道真实运行判分的编程题，并提交实验报告。",
        "course_chapters": [4, 5, 6, 7],
        "report_required": True,
        "window_days": (-3, 10),
        "close_after_seed": False,
        "chapters": [
            {
                "title": "结构与性质",
                "description": "树、堆、图与查找的概念与复杂度。",
                "objectives": ["说明二叉树遍历方式", "理解堆序性质", "区分 BFS 与 DFS", "写出正确的二分边界"],
                "tasks": [
                    {
                        "type": CHOICE,
                        "title": "二叉搜索树的中序遍历",
                        "description": "对一棵二叉搜索树进行中序遍历，得到的序列具有什么性质？",
                        "options": [("a", "按层有序"), ("b", "升序排列"), ("c", "降序排列"), ("d", "无规律")],
                        "correct": ["b"],
                        "explanation": "中序为“左—根—右”，恰好按升序访问二叉搜索树。",
                        "score": "5",
                    },
                    {
                        "type": CHOICE,
                        "title": "数组表示完全二叉树",
                        "description": "用数组从下标 0 开始存储完全二叉树，下标 i 的左孩子下标是？",
                        "options": [("a", "i + 1"), ("b", "2i"), ("c", "2i + 1"), ("d", "2i + 2")],
                        "correct": ["c"],
                        "explanation": "父节点 i 的左孩子为 2i+1，右孩子为 2i+2。",
                        "score": "5",
                    },
                    {
                        "type": CHOICE,
                        "title": "层序遍历使用的容器",
                        "description": "实现二叉树的层序遍历应使用哪种数据结构？",
                        "options": [("a", "栈"), ("b", "队列"), ("c", "哈希表"), ("d", "堆")],
                        "correct": ["b"],
                        "explanation": "层序遍历按到达顺序访问节点，使用先进先出的队列。",
                        "score": "5",
                    },
                    {
                        "type": MULTI,
                        "title": "二分查找的前提",
                        "description": "下列哪些是二分查找能够高效工作的必要条件？",
                        "options": [
                            ("a", "数据有序"),
                            ("b", "支持随机访问"),
                            ("c", "数据全部唯一"),
                            ("d", "数据规模固定"),
                        ],
                        "correct": ["a", "b"],
                        "explanation": "有序性用于缩小范围，随机访问用于 O(1) 取到中点；元素是否唯一并不影响基本二分。",
                        "score": "5",
                    },
                ],
            },
            {
                "title": "编程实践",
                "description": "二叉树深度与二分插入点，代码在隔离容器中运行隐藏用例。",
                "objectives": ["用层序数组还原树结构", "写出不会死循环的二分"],
                "tasks": [
                    {"type": PROGRAMMING, "key": "tree_depth", "score": "10"},
                    {"type": PROGRAMMING, "key": "lower_bound", "score": "10"},
                ],
            },
        ],
    },
    {
        "code": "EXP3",
        "name": "实验三：排序、分治与动态规划",
        "category": "算法设计",
        "description": "覆盖排序、分治、回溯、动态规划与贪心的选型判断，并完成归并排序与 0-1 背包两道编程题。",
        "course_chapters": [8, 9, 10, 11],
        "report_required": False,
        "window_days": (2, 16),
        "close_after_seed": False,
        "chapters": [
            {
                "title": "算法选型",
                "description": "排序稳定性、分治与回溯、动态规划与贪心的边界。",
                "objectives": ["判断排序算法特性", "区分分治与回溯", "判断贪心是否适用"],
                "tasks": [
                    {
                        "type": CHOICE,
                        "title": "稳定的排序算法",
                        "description": "下列排序算法中，通常被认为是稳定排序的是？",
                        "options": [("a", "快速排序"), ("b", "堆排序"), ("c", "归并排序"), ("d", "选择排序")],
                        "correct": ["c"],
                        "explanation": "归并排序在合并时优先取左侧相等元素，因此稳定。",
                        "score": "5",
                    },
                    {
                        "type": CHOICE,
                        "title": "快速排序的最坏情况",
                        "description": "快速排序在最坏情况下的时间复杂度是？",
                        "options": [("a", "O(n)"), ("b", "O(n log n)"), ("c", "O(n²)"), ("d", "O(log n)")],
                        "correct": ["c"],
                        "explanation": "每次划分极不均衡时递归深度为 n，总代价 O(n²)。",
                        "score": "5",
                    },
                    {
                        "type": CHOICE,
                        "title": "0-1 背包的一维遍历方向",
                        "description": "使用一维数组求解 0-1 背包时，容量维度应当如何遍历？",
                        "options": [("a", "从小到大"), ("b", "从大到小"), ("c", "任意顺序"), ("d", "只能使用二维数组")],
                        "correct": ["b"],
                        "explanation": "倒序遍历保证 dp[j-w] 仍是上一轮状态，每件物品只使用一次。",
                        "score": "5",
                    },
                    {
                        "type": CHOICE,
                        "title": "适合贪心的问题",
                        "description": "下列问题中，通常可以直接使用贪心算法获得最优解的是？",
                        "options": [("a", "0-1 背包"), ("b", "分数背包"), ("c", "最长公共子序列"), ("d", "编辑距离")],
                        "correct": ["b"],
                        "explanation": "分数背包允许分割物品，按单位价值排序后贪心即可；0-1 背包不可分割，需要动态规划。",
                        "score": "5",
                    },
                ],
            },
            {
                "title": "编程实践",
                "description": "归并排序与 0-1 背包，覆盖分治与动态规划两类实现。",
                "objectives": ["实现稳定的归并排序", "写出一维背包的状态转移"],
                "tasks": [
                    {"type": PROGRAMMING, "key": "merge_sort", "score": "10"},
                    {"type": PROGRAMMING, "key": "knapsack", "score": "10"},
                ],
            },
        ],
    },
]

COURSE_SCHEDULES = [
    # weekday, start_period, end_period, classroom
    (3, 3, 4, "东二 305"),
    (5, 1, 2, "东二 305"),
]
