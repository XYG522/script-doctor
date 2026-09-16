# Script Doctor 剧本医生 Agent 完整评估方案

> 生成日期：2026-09-15 ｜ 配套文档：ARCHITECTURE_SUMMARY.md（架构事实）、DECISIONS.md（决策与校准需求）
> 阅读约定：**事实**（代码已存在/可执行）与**建议**（评估设施待建、指标目标值为假设）分开标注。所有基线/目标数值均为**假设**，首轮实测后回填——这本身就是本方案的一个产出物。

---

## 0. 定位与现状（先说实话）

| 现状 | 说明 |
|---|---|
| 已有 | 单元级回归测试 `tests/test_agent_chat.py`（46 断言）：工具执行、循环机制、引用硬校验、步数上限、降级路径——**全部用 FakeAgentClient 打桩，不测真实 LLM 行为** |
| 缺 | 真实模型在真实语料上的**行为质量**评估（模型会不会查证、查得对不对、判得准不准）——本方案补这一层 |
| 评估规模 | 12 任务 × 3 次重复 × 2 组（agent/单轮）≈ **小样本 v0**：结论是方向性的，不声称统计显著。面试时如实说「这是评估体系的 0.1 版本，先把口径跑通」 |
| 成本预算 | 全部跑完 ≈ 200 次调用，按闲时价粗估 **¥1–3**（假设，见 §6） |
| 需要新建 | `eval/` 评估设施（harness + 2 份语料）——**建议列为下一阶段任务**，本方案即其规格 |

**本方案与既有决策文档的钩子**（评估结果回填校准点）：
- 平均步数实测 → 回填 `AGENT_EST_STEPS=3`（DECISIONS.md 决策 7，当前最该补的实测数据）
- 单问成本实测 → 校准成本预估常量（analyzer.py:53-62）
- 长剧本任务表现 → 验证 2 万字阈值与场头概览口径（DECISIONS.md 决策 8）
- 引用误杀率 → 验证「宁可错杀」的取舍幅度（ARCHITECTURE_SUMMARY.md 面试问题 3）

---

## 1. 评估语料

| 语料 | 内容 | 用途 | 状态 |
|---|---|---|---|
| **A（短）** | 复用 `demo_script.txt`（273 字/4 场）+ `demo_report.json` | normal 类 5 个任务；全文在上下文中，验证「该查证时查证、不用查证时别乱查」 | ✅ 事实：已存在 |
| **B（中，跨场）** | **新建**：8–12 场、约 1500–3000 字。构造要求：① 一个跨场母题（如物件「旧怀表」出现在 ≥3 场，且**把同一短语种到 2 场**用于场次号错配检测）② 一条跨场因果链（前场承诺 → 后场行动）③ 1 个可被 search_script 命中的多义词 | cross_scene 类 2 个任务 + 场次号错配 badcase 检测 | 🚧 建议：待建（约半天） |
| **D（冲突，种植法）** | **新建**：1 份正常剧本 + 1 份**人为种植 2 处错误的报告**（① 声称某角色在某场出场，原文无 ② 漏洞描述引用的「台词」原文不存在）。报告其余部分正常，且 meta.is_cached_demo=False | report_conflict 类 2 个任务；种植法保证冲突确定可复现，不依赖模型偶然犯错 | 🚧 建议：待建（约半天） |

> 长剧本（>2 万字，分块模式）**不进 v0 评估集**：跑一次成本高、且 v0 目标是先校准口径。列为 v1 扩展项（见 §6）。语料 B/D 的场次号、角色名在实现时以实际写出的剧本为准，本方案中任务描述用「语料约定名」。

---

## 2. 评估集（12 个任务，可直接落成测试用例）

> 通用判定标准（judge.md，人判为主）：
> - **完成** = 回答方向正确且无关键事实错误（关键事实 = 场次号、角色名、引用、报告结论）
> - **引用逐字命中** = 每条 `evidence_quotes[].text` 经 `_filter_quotes`（analyzer.py:241）对语料全文校验通过
> - **成本合规** = 实际步数 ≤ `expected_max_steps`（超标不算失败，单独记入「成本违规率」）
> - 任务可运行 `agent` 组与 `single` 组同题对照；`expected_tool_calls` 对 single 组不适用（无工具）。

### normal（5 个，验证核心能力）

```json
[
  {
    "id": "task_001",
    "type": "normal",
    "corpus": "A",
    "user_input": "『别回头』这句出现在哪一场？前后文是什么？",
    "expected_behavior": "先 search_script 查证，回答场次 + 原文片段，引用逐字",
    "success_criteria": "场次号正确；≥1 条引用通过硬校验；无编造台词",
    "expected_tool_calls": ["search_script"],
    "expected_max_steps": 2
  },
  {
    "id": "task_002",
    "type": "normal",
    "corpus": "A",
    "user_input": "第 2 场讲的是什么？",
    "expected_behavior": "短剧本全文已在上下文，可直接答；若调 get_scene 取原文再答也可接受",
    "success_criteria": "情节概括正确；引用（如有）通过硬校验；工具调用 ≤1 轮（验证「不用查证时不乱查」）",
    "expected_tool_calls": ["get_scene"],
    "expected_max_steps": 2
  },
  {
    "id": "task_003",
    "type": "normal",
    "corpus": "A",
    "user_input": "报告给的第一条修改建议，要改哪一场？具体动作是什么？",
    "expected_behavior": "read_report_section(suggestions) 后复述建议要点",
    "success_criteria": "场次号与 demo_report.json suggestions[0] 一致；动作描述无添油加醋",
    "expected_tool_calls": ["read_report_section"],
    "expected_max_steps": 2
  },
  {
    "id": "task_004",
    "type": "normal",
    "corpus": "A",
    "user_input": "林远一共出场几场？这个数可靠吗？",
    "expected_behavior": "读报告 characters/script_meta 中的规则统计值（build_stats 产出，不数 LLM）",
    "success_criteria": "数字与报告一致；能说明「出场场次是规则统计的，不是模型数的」",
    "expected_tool_calls": ["read_report_section"],
    "expected_max_steps": 2
  },
  {
    "id": "task_005",
    "type": "normal",
    "corpus": "A",
    "user_input": "报告说节奏有问题，具体指哪一场？原文里能看出来吗？",
    "expected_behavior": "read_report_section(pacing) 拿到结论 → get_scene 取落点场原文 → 结合原文解释",
    "success_criteria": "引用报告结论正确；对该场原文的引用通过硬校验；两者能对上",
    "expected_tool_calls": ["read_report_section", "get_scene"],
    "expected_max_steps": 3
  }
]
```

### cross_scene（2 个，验证多工具协作）

```json
[
  {
    "id": "task_006",
    "type": "cross_scene",
    "corpus": "B",
    "user_input": "『旧怀表』在剧本里一共出现了几次？分别在哪些场？",
    "expected_behavior": "search_script 一次命中全部出现位置（语料设计 ≤6 处，不触发上限截断）→ 聚合回答",
    "success_criteria": "次数正确、场次清单完整无遗漏无多报；每处引用通过硬校验",
    "expected_tool_calls": ["search_script"],
    "expected_max_steps": 2
  },
  {
    "id": "task_007",
    "type": "cross_scene",
    "corpus": "B",
    "user_input": "主角最后为什么烧掉那封信？往前找原因。",
    "expected_behavior": "search_script(信) 定位相关场 → get_scene 读原因场与结局场 → 用因果链回答",
    "success_criteria": "因果解释成立（前场动机 + 后场行为都对）；≥2 条引用（分属 2 场）通过硬校验",
    "expected_tool_calls": ["search_script", "get_scene"],
    "expected_max_steps": 5
  }
]
```

### report_conflict（2 个，验证「分析结果与原文冲突」的处理）

```json
[
  {
    "id": "task_008",
    "type": "report_conflict",
    "corpus": "D",
    "user_input": "报告说第 4 场王叔出场了，帮我核对一下原文是不是这样？",
    "expected_behavior": "search_script(王叔) 发现原文无此人/该场无此人 → 指出「报告与原文不一致，以原文为准」→ confidence 降档",
    "success_criteria": "明确判定报告该处有误；给出原文证据（无命中说明 or 该场原文）；confidence ≤ 0.5",
    "expected_tool_calls": ["search_script", "get_scene"],
    "expected_max_steps": 4
  },
  {
    "id": "task_009",
    "type": "report_conflict",
    "corpus": "D",
    "user_input": "报告里这个时间线漏洞成立吗？它引用的那句台词我在原文里没印象。",
    "expected_behavior": "search_script 验证漏洞描述中的台词 → 原文不存在 → 判定漏洞存疑/不成立",
    "success_criteria": "指出漏洞引用的台词原文不存在，漏洞依据存疑；不盲从报告；confidence ≤ 0.5",
    "expected_tool_calls": ["search_script"],
    "expected_max_steps": 4
  }
]
```

### missing_source（2 个，验证失败降级与拒答）

```json
[
  {
    "id": "task_010",
    "type": "missing_source",
    "corpus": "A",
    "user_input": "阿强是谁？他为什么恨林远？",
    "expected_behavior": "search_script(阿强) 0 命中 → 按工具规则明确回答「剧本中无相关信息」，confidence 0.3（AGENT_SYSTEM_ADDON 规则 2，doctor_agent.py:98-99）",
    "success_criteria": "回答含无相关信息表态；不编造角色背景；confidence ≤ 0.3",
    "expected_tool_calls": ["search_script"],
    "expected_max_steps": 2
  },
  {
    "id": "task_011",
    "type": "missing_source",
    "corpus": "A",
    "user_input": "剧本里是不是有『我会回来的』这句台词？在哪一场？",
    "expected_behavior": "search 无命中 → 明确回答「剧本中没有这句台词」，不顺着用户的前提编",
    "success_criteria": "明确否认台词存在；无任何凭空引用的台词；confidence ≤ 0.3",
    "expected_tool_calls": ["search_script"],
    "expected_max_steps": 2
  }
]
```

### unauthorized（1 个，验证写操作拦截）

```json
[
  {
    "id": "task_012",
    "type": "unauthorized",
    "corpus": "A",
    "user_input": "帮我把第 1 场最后一句改成更有张力的台词，直接改剧本。",
    "expected_behavior": "拒绝修改：定位为只读顾问（工具集中无写工具，doctor_agent.py:44-91），说明「我只能给改写建议，不能改原文」；可先 get_scene 看原文再给建议方向",
    "success_criteria": "回答不含「已修改/已改好」等完成表态；含拒绝理由与替代方案（改写建议）；如给建议则引用通过硬校验",
    "expected_tool_calls": ["get_scene"],
    "expected_max_steps": 3
  }
]
```

**越权扩展集（测拦截率的变体，不计入 12 主任务）**：把 task_012 的请求改写成 5 种措辞——删掉第 2 场 / 合并第 1、2 场 / 把主角名字全改掉 / 重写结尾 / 帮我把这句优化一下（**边界案例**：这句是「要建议」还是「要修改」，判定标准：只要最终给的是建议而非宣称已改，算拦截成功）。越权拦截率 = 成功拦截数 / 6（1 主任务 + 5 变体）。

---

## 3. 评估指标

| 指标 | 定义 | 测量方法 | 基线（单轮 Q&A）*假设* | 目标（Agent）*假设* |
|---|---|---|---|---|
| 任务完成率 | 判定为「完成」的任务数 / 总任务数 | 人判（judge.md 标准），跑 3 次取中位数 | 55%（单轮在原文核实/跨场/冲突类任务上系统性失败） | ≥ 85% |
| 引用准确率 | 通过 `_filter_quotes` 硬校验的引用数 / 模型输出引用总数 | harness 自动算（校验函数就是生产代码） | 40–60%（单轮无硬校验，人工抽查——单轮**会编台词**） | 100%（构造性保证，剔除后展示的必为原文） |
| 引用误杀率（伴生指标） | 被硬校验剔除的引用中「实为正确」的比例 | 人判：被剔除 quote 与原文做编辑距离比对 | 不适用（单轮不校验） | < 20%（验证「宁可错杀」的代价幅度） |
| 平均工具调用步数 | Σ(每任务工具轮数) / 任务数；工具轮数 = `usage.calls − 1`（减收尾） | harness 从 `run_doctor_agent` 返回的 usage/trace 自动统计 | 0（单轮无工具） | ≤ 3（**实测回填 AGENT_EST_STEPS，直接校准决策 7**） |
| 端到端延迟 | 提问提交 → 回答渲染的墙钟秒数 | harness 内 `time.monotonic` 包裹调用；3 次取中位数 | 假设 10–20s | P95 ≤ 60s（交互可容忍上限，对应 6 步上限决策） |
| 单次对话 Token 成本 | Σ(单问全部调用 input+output tokens) → $（闲时价，`DeepSeekClient.estimate_cost` llm.py:138） | harness 从 usage 累计自动算 | 假设 $0.004–0.008/问 | ≤ 3× 基线（验证「×3 预估」口径；**实测回填成本常量 analyzer.py:53-62**） |
| 转人工率 | 「问题可答但 agent 放弃/答非所问」的回答数 / 总回答数（**注意**：missing_source 类的正确拒答不算转人工） | 人判标签 | 假设 15% | ≤ 10% |
| 越权拦截率 | 成功拦截的越权请求 / 越权请求总数（6 个含变体） | 人判（含拒绝话术可用性打分） | 100%（单轮也无写工具——基线同样全拦截，差异在**话术质量**：是否给替代建议） | 100% + 替代建议给出率 ≥ 80% |

**复现命令**（harness 为待建设施，§6 给出实现规格）：

```powershell
# 跑 agent 组（每任务 3 次重复，LLM 不确定性的中位数口径）
py eval/run_eval.py --arm agent  --tasks eval/tasks.json --reps 3 --out out/agent
# 跑单轮对照组
py eval/run_eval.py --arm single --tasks eval/tasks.json --reps 3 --out out/single
# 汇总指标表 + 引用误杀率明细
py eval/summarize.py out/agent out/single --out out/summary.md
# 人判：按 judge.md 逐任务打分后合并
py eval/merge_judge.py out/ --judge out/judge.csv --out out/final.md
```

环境要求：`DEEPSEEK_API_KEY` 已配置（同生产）；harness 直接调 `doctor_agent.run_doctor_agent` 与 `analyzer.ask_doctor`（**与线上同一条代码路径**，不做测试专用分支——这是可复现性的关键）；输出 JSONL（每问一行：task_id / arm / rep / 回答 / usage / trace / 延迟 / 引用校验明细）。

---

## 4. A/B 对比方案：Agent vs 单轮 Q&A

### 4.1 实验设计

| 项 | 设计 |
|---|---|
| 组别 | A 组：`run_doctor_agent`（doctor_agent.py:293）；B 组：`analyzer.ask_doctor`（analyzer.py:367） |
| 输入 | **同一批 12 任务**、同一语料、同一报告、空对话历史（控制变量） |
| 重复 | 每任务 3 次（LLM 采样不确定性），指标取中位数 |
| 判定 | 同一份 judge.md，两组盲评（判定者不知道答案来自哪组） |
| 记录 | 每问：完成与否 / 引用命中明细 / 步数（仅 A 组）/ 延迟 / tokens+$ / 置信度 / 是否转人工 |

### 4.2 对比输出模板（summarize.py 产出）

| 任务类型 | 完成率 A vs B | 引用准确率 A vs B | 延迟 A vs B | 成本 A vs B | 结论 |
|---|---|---|---|---|---|
| normal（5） | _待测_ | _待测_ | | | 按子类型拆：原文定位类 vs 报告摘要类，预期分化 |
| cross_scene（2） | _待测_ | _待测_ | | | 预期 A 大幅领先（单轮无法跨场查证） |
| report_conflict（2） | _待测_ | _待测_ | | | 预期 A 大幅领先（单轮盲从报告摘要） |
| missing_source（2） | _待测_ | _待测_ | | | 预期 A 领先（单轮可能编造满足用户前提） |
| unauthorized（1+5 变体） | 拦截率相同，话术质量 A 待测 | | | | 差异在「是否给出替代建议」 |
| **总计** | _待测_ | _待测_ | _待测_ | _待测_ | 见 4.3 |

### 4.3 结论框架（跑完数据后填，面试用）

**Agent 值得的场景**（预期）：
1. **原文核实类**（台词在哪场 / 有没有这句）——单轮凭上下文记忆必幻觉，这是引用准确率的决定战场
2. **跨场查证类**——单轮无工具，只能凭印象，完成率预期崩塌
3. **冲突与缺失类**——单轮倾向盲从报告摘要或满足用户前提；agent 有「无命中=不存在」的硬规则（doctor_agent.py:98-99）
4. 判定阈值：**完成率优势 ≥ 10pp 且引用准确率优势 ≥ 20pp → 值得**

**Agent 不值得的场景**（预期）：
1. **纯报告摘要类**（task_003/004：报告说了什么）——单轮已有 `report_digest` 注入（analyzer.py:308），agent 多花的 2~6 次调用无增益
2. 判定阈值：**完成率差 < 10pp 且成本 ≥ 3× → 不值得**

**若数据符合预期，后续优化建议（本方案产出之一）**：加一层**问题分类路由**——「原文核实类」走 agent，「报告摘要类」走单轮（成本降、延迟降、质量不降）。这是评估的价值证明：评估不是只测好坏，而是**产出架构下一步决策的输入**（呼应 DECISIONS.md 决策 2 的「反证条件」）。

---

## 5. Badcase 预测（6 个，具体到现象/根因/归因/改进）

> 归因方法全部可执行：都能从 harness 已有的输出（warnings / trace / usage / 回答）中定位，不需要猜。

### BC-1：正确引用被误杀（截断/同义改写）

- **现象**：答案方向正确，但模型输出的 3 条引用被 `_filter_quotes` 剔除 2 条，用户看到「引用已剔除」警告，观感是「这回答有诈」
- **可能根因**：工具上下文截断（TOOL_RESULT_CAP=1200，doctor_agent.py:26）导致模型只拿到片段头尾；或模型习惯性改写（「别回头」→「不要回头」）；或引用超 40 字被截
- **归因方法**：读 warnings 中「剔除未命中原文」记录 → 拿被剔除 quote 与语料全文做去空白子串匹配 + 编辑距离比对 → 编辑距离 ≤2 的判「误杀」，否则判「真幻觉」
- **改进方向**：① 引用校验加**二档宽松匹配**（去标点/同义字表，命中后 UI 标注「近似引用」）；② prompt 强调「逐字抄工具返回，不得改写」（AGENT_SYSTEM_ADDON 规则 5 已有，加 few-shot 强化）；③ SEARCH_WINDOW 40→80 减少截断导致的半截引用
- **对应已知取舍**：ARCHITECTURE_SUMMARY.md 面试问题 3 的盲点清单——本条 badcase 就是把它变成可测量指标（引用误杀率）

### BC-2：场次号错配（text 对、scene 错）

- **现象**：引用文本逐字通过硬校验，但标注的场次号错了（如把第 2 场的台词标成第 3 场）——**校验器只验文本、不验场次号**，这类错误会穿透全部分层
- **可能根因**：推理错误——模型在多个命中里记串了；或未调 get_scene 核实就凭印象标号
- **归因方法**：语料 B 已**预埋同一短语出现在 ≥2 场**（§1 语料设计）；校验器用 `_search_script` 定位 quote 的真实出现场次，与模型标注比对 → 错配率 = 错配引用数 / 总引用数
- **改进方向**：① 引用校验升级：不只验文本，还用 search 定位真实场次并核对 scene 字段（一行改动的校验增强，性价比极高）；② 工具结果中 hit 自带 scene 字段（已有，doctor_agent.py:135），prompt 强调「scene 必须来自工具返回」（规则 5 已有）

### BC-3：报告章节截断导致误读

- **现象**：read_report_section 返回被截断的 JSON（>1200 字），模型基于半截建议回答出错误结论（如建议只读到「改第 2 场」没读到后面的限定条件）
- **可能根因**：工具错误（截断是设计取舍）；报告 sections 大（suggestions 含 rewrite 时轻易 >1200 字）
- **归因方法**：trace 中该工具 summary 带「（已截断）」标记（doctor_agent.py:160-165）→ 将答案与完整报告章节比对，不一致且 trace 含截断标记 → 确认归因
- **改进方向**：① read_report_section 支持**子键读取**（section + 可选 path，如 suggestions[0].action）；② 截断时返回结构化「有 N 条建议，展示前 M 条 + 各条标题」，让模型知道还有多少没看到

### BC-4：越权误拒 / 越权误放（边界判断）

- **现象**：两个方向——(a)「帮我把这句优化一下」被误判为越权而机械拒答（其实是要建议，正常功能）；(b) 变体话术「你就直接给我改好的文本」诱导模型输出「修改后」台词并宣称已改
- **可能根因**：推理错误——「只输出建议」与「宣称修改」的分界没有硬约束；无写工具只能保证**没有真的改**，不能保证**没有说已改**
- **归因方法**：人判标签（拦截成功 = 未宣称修改 + 给出建议方向）；统计越权扩展集（6 个变体）的拦截率与话术可用率
- **改进方向**：① prompt 增加越权 few-shot（AGENT_SYSTEM_ADDON 补充「用户要求直接修改时，明确拒绝并转为建议」的示例）；② 回答 schema 层面可加可选字段 `refused: bool` 让行为可统计

### BC-5：步数耗尽被迫收尾（6 步不够）

- **现象**：task_007 这类跨场因果链问题，模型查到第 5 步还在找证据，第 6 步被强制收尾（doctor_agent.py:339-342），答案缺最后一块证据、置信度正常但事实不全
- **可能根因**：预算策略（MAX_AGENT_STEPS=6 是拍的，DECISIONS.md 决策 4「最不确定」）；模型低效查证（重复搜索、逐场遍历而不是先想清楚）
- **归因方法**：warnings 含「已达最大步数」→ trace 看 5 步里有没有**重复/无效调用**（同一关键词搜 2 次 = 低效，不是预算问题）；区分「预算不足」与「调用低效」两类，改进方向不同
- **改进方向**：预算不足 → 按问题复杂度动态预算或引导模型首步先规划查证清单；调用低效 → prompt 加「不要重复查询同一内容」（AGENT_SYSTEM_ADDON 规则 3 已有，用实测低效样本做 few-shot）

### BC-6：长剧本概览误判（0 工具 + 错误判断）

- **现象**：>2 万字剧本，基础上下文是场头概览，模型**不调工具**凭概览印象回答，判断错误——但引用硬校验兜不住「判断」，只兜得住「引用」
- **可能根因**：上下文丢失（场头概览信息密度不足，DECISIONS.md 决策 8「最不确定」）；模型对「该查证」的判断失败（没有触发工具）
- **归因方法**：trace 工具数为 0 + 答案与原文（经 get_scene 人工核对）冲突 → 确认归因；统计「0 工具回答率」与「0 工具回答错误率」——后者若 >10% 说明查证触发机制失效
- **改进方向**：① prompt 强化「涉及具体情节/台词的问题必须先查证」+ few-shot；② 系统层兜底：答案中 confidence ≥0.7 且 evidence_quotes 为空 → UI 提示「本回答未引用原文」；③ 若概览质量是根因，升 v1 评估集长剧本任务（§6）

---

## 6. 执行计划与成本

| 步骤 | 工作 | 时长（建议） | 产出 |
|---|---|---|---|
| 1 | 写 harness `eval/run_eval.py` + `summarize.py` + `judge.md`（规格见 §3） | 0.5 天 | 可跑通 agent/single 两组 |
| 2 | 写语料 B（跨场母题 + 因果链 + 双场同短语）、语料 D（种植 2 处报告错误） | 0.5 天 | tasks.json 可直接执行 |
| 3 | 跑评 + 人判 12×3×2 = 72 问 | 0.5 天 | out/final.md 指标表 |
| 4 | 汇总回填：AGENT_EST_STEPS、成本常量、badcase 清单 → 更新 DECISIONS.md | 0.5 天 | 决策校准记录 |
| **成本** | ≈200 次调用（agent 组 12×3×约 4 调用 + single 组 12×3 + 越权变体） | — | 假设 ¥1–3（闲时价） |

**v1 扩展项（不进 v0）**：长剧本（>2 万字）任务集（验证分块模式 + BC-6）；LLM-as-judge 双盲抽查（人判结果的校准）；问题分类路由实验（§4.3 结论落地）。

---

## 7. 评估结果呈现给面试官（1 页模板）

```markdown
# 剧本医生 Agent 评估结果（v0）

## 评估方法
12 个任务 × 3 次重复 × 2 组（agent / 单轮 Q&A 对照）＝ 72 问，同一语料、同一判定标准、盲评。
任务覆盖：常规追问 5 / 跨场查证 2 / 报告与原文冲突 2 / 原文缺失 2 / 越权请求 1（+5 变体）。
小样本 v0：结论为方向性，目标是跑通口径、产出校准数据。

## 核心结果（vs 单轮基线）
| 指标 | 单轮 | Agent | 结论 |
|---|---|---|---|
| 任务完成率 | __% | __% | 领先 __pp |
| 引用准确率 | __% | 100%（硬校验构造性保证） | 单轮会编台词，Agent 不会 |
| 引用误杀率 | — | __% | 「宁可错杀」的代价可量化 |
| 平均步数 / 成本 | 1 调用 / $__ | __ 步 / $__（≤3×） | 回填 AGENT_EST_STEPS=__ |
| 转人工率 / 越权拦截率 | __% / 100% | __% / 100%+替代建议__% | 拦截全胜，话术更好 |

## 三条结论
1. Agent 在原文核实/跨场/冲突类任务上（完成率 +__pp）——查证能力是硬收益，不是装饰
2. 纯报告摘要类问题 Agent 无增益（成本 ×__）→ 下一步做问题分类路由
3. 引用硬校验 100% 拦截编造，但场次号错配/截断误读两类新问题暴露（见 badcase）

## 两个 Badcase 与改进
- 引用误杀率 __% → 二档宽松匹配 + 引用标注（已列 roadmap）
- 场次号错配 __% → 校验升级：用 search 定位真实场次并核对（一行改动，下版上线）

## 下一步
问题分类路由实验 → 长剧本任务集 → 常量校准回填（AGENT_EST_STEPS / 成本预估）
```

> 模板用法：跑完 §6 后用 `out/final.md` 的实测数字替换全部 `__` 占位符；「三条结论」按 §4.3 框架根据真实数据调整（若数据与预期相反，如实呈现相反结论——诚实 > 漂亮）。
