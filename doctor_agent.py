"""剧本医生 Agent（方案 A）：带工具的多轮查证循环 + 引用硬校验。

与 analyzer.ask_doctor（单轮）的区别：
- 模型可以按需调用 3 个只读工具（search_script / get_scene / read_report_section）查证后再回答
- 工具结果全部来自本地规则检索，不经过 LLM 生成，杜绝「编造工具返回」
- 引用逐字硬校验对象升级为剧本全文：工具可从全文取原文，长剧本不再局限于场头概览

流程（单问）：
用户提问 → 循环（≤ MAX_AGENT_STEPS 步，1 步 = 1 次 LLM 调用）：
    LLM 返回 tool_calls → 本地执行工具 → 结果回喂 → 再问
    LLM 返回正文 → 视为最终回答 → 解析 + schema 校验（失败修复重试 ≤2）→ 引用硬校验 → 返回
步数耗尽未收敛 → 追加收尾指令，用 json_object 强制出最终回答
循环内调用异常 → 返回 data=None，由调用方（app.py）降级到单轮 ask_doctor
"""
import json
import re

import jsonschema

import analyzer
from prompts import MODULE_SCHEMAS, MODULE_SYSTEM_ADDON, SYSTEM_BASE, USER_TEMPLATES

MAX_AGENT_STEPS = 6        # 单问最多 6 步；最后一步不执行工具，留给收尾
MAX_REPAIR_RETRIES = 2     # 最终回答修复重试（与 analyzer._run_module 同口径）
MAX_TOOLS_PER_TURN = 3     # 单步最多执行 3 个工具，防止单步调用爆炸
TOOL_RESULT_CAP = 1200     # 工具结果回喂截断（字符），控制输入成本
SEARCH_MAX_HITS = 6        # search_script 最多返回条数
SEARCH_WINDOW = 40         # 命中片段上下文窗口（±字符）
AGENT_EST_STEPS = 3        # 成本预估口径：单问平均步数（估算值，实际以账单为准）

# 工具 → UI 中文标签（app.py 中间步骤展示用）
TOOL_LABELS = {
    "search_script": "搜索原文",
    "get_scene": "读取场次",
    "read_report_section": "查看报告",
}

# 报告可查询章节白名单（read_report_section 参数枚举，防止任意键读取）
REPORT_SECTIONS = [
    "script_meta", "score", "logic", "suggestions", "hard_checks",
    "structure", "pacing", "emotion", "characters", "relationships", "commercial",
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_script",
            "description": "在剧本原文中搜索关键词，返回命中场次与片段。"
                           "用于核实某句台词/情节/人物是否存在于剧本及其所在场次。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "要搜索的词或短语"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scene",
            "description": "读取指定场次的完整原文。用于回答涉及具体场次细节的问题，"
                           "或为引用取逐字原文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene": {"type": "integer", "description": "场次号"},
                },
                "required": ["scene"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_report_section",
            "description": "读取体检报告的指定章节（评分/漏洞/建议/结构等），"
                           "用于结合报告结论回答问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "section": {"type": "string", "enum": REPORT_SECTIONS,
                                "description": "报告章节名"},
                },
                "required": ["section"],
            },
        },
    },
]

AGENT_SYSTEM_ADDON = (
    "你可以按需调用只读工具查证剧本原文与体检报告，再回答编剧的问题。\n"
    "【工具使用规则】\n"
    "1. 涉及具体台词、情节、场次的问题：先用 search_script / get_scene 查证原文；"
    "引用必须逐字抄自工具返回的原文，不查证就凭印象引用属于编造。\n"
    f"2. 每次最多调用 {MAX_TOOLS_PER_TURN} 个工具；工具返回中找不到的内容一律视为不存在，"
    "明确回答「剧本中无相关信息」，confidence 降为 0.3。\n"
    "3. 查证步数有限：只查必要信息，不要重复查询同一内容。\n"
    "4. 不再需要查证时，直接输出最终回答 json（answer + evidence_quotes + confidence），"
    "不要输出 json 以外的任何内容。\n"
    "5. evidence_quotes 的 scene 必须是工具返回中的真实场次号，"
    "text 必须逐字摘自工具返回的原文（≤40 字）。"
)

FORCE_SUFFIX = (
    "请直接输出最终回答 json（不要调用工具、不要输出 json 以外的任何内容）：\n"
    '{"answer":"回答正文","evidence_quotes":[{"scene":1,"text":"逐字引用 ≤40 字"}],"confidence":0.7}'
)


# ---------------------------------------------------------------------------
# 工具实现（本地规则检索，不调 LLM）
# ---------------------------------------------------------------------------

def _search_script(scenes, keyword) -> dict:
    """在剧本原文中搜索关键词。返回 {"found", "hits", "note"}。

    hits：[{"scene","title","excerpt"}]，每条带 ±SEARCH_WINDOW 字上下文，最多 SEARCH_MAX_HITS 条。
    """
    if not keyword or not keyword.strip():
        return {"found": 0, "hits": [], "note": "关键词为空"}
    kw = keyword.strip()
    hits = []
    for s in scenes:
        content = s["content"]
        pos = 0
        while True:
            i = content.find(kw, pos)
            if i < 0:
                break
            lo = max(0, i - SEARCH_WINDOW)
            hi = min(len(content), i + len(kw) + SEARCH_WINDOW)
            hits.append({"scene": s["n"], "title": s["title"], "excerpt": content[lo:hi]})
            pos = i + len(kw)
            if len(hits) >= SEARCH_MAX_HITS:
                break
        if len(hits) >= SEARCH_MAX_HITS:
            break
    if not hits:
        return {"found": 0, "hits": [], "note": "全文未找到该关键词"}
    note = f"命中 {len(hits)} 条" + ("（已达展示上限，可能还有更多）" if len(hits) >= SEARCH_MAX_HITS else "")
    return {"found": len(hits), "hits": hits, "note": note}


def _get_scene(scenes, n):
    """按场次号取场景（无则 None）。"""
    for s in scenes:
        if s["n"] == n:
            return s
    return None


def _read_report_section(report, section) -> dict:
    """读取报告指定章节，返回 {"found", ...}；章节为空/不存在时 found=False。"""
    if section not in report or report.get(section) in (None, {}, []):
        return {"found": False, "note": f"报告中没有「{section}」章节（可能本次未分析该模块）"}
    payload = json.dumps(report[section], ensure_ascii=False)
    truncated = len(payload) > TOOL_RESULT_CAP
    return {
        "found": True,
        "section": section,
        "data": payload[:TOOL_RESULT_CAP] + ("…（已截断）" if truncated else ""),
    }


def _execute_tool(tc, scenes, report) -> dict:
    """执行单个工具调用，返回回喂给模型的 dict。参数非法/未知工具 → 含 error 的结果。"""
    name, args_raw = tc.get("name"), tc.get("arguments") or "{}"
    try:
        args = json.loads(args_raw) if args_raw else {}
    except json.JSONDecodeError:
        return {"ok": False, "error": f"工具参数不是合法 JSON：{args_raw[:80]}"}
    if name == "search_script":
        return _search_script(scenes, str(args.get("keyword", "")))
    if name == "get_scene":
        n = args.get("scene")
        s = _get_scene(scenes, n)
        if s is None:
            return {"ok": False, "error": f"场次 {n} 不存在（剧本共 {len(scenes)} 场）"}
        content = s["content"]
        truncated = len(content) > TOOL_RESULT_CAP
        return {
            "ok": True, "scene": s["n"], "title": s["title"],
            "content": content[:TOOL_RESULT_CAP] + ("…（已截断）" if truncated else ""),
        }
    if name == "read_report_section":
        return _read_report_section(report, str(args.get("section", "")))
    return {"ok": False, "error": f"未知工具：{name}"}


def _tool_summary(name, result) -> str:
    """工具结果 → UI 展示用的一句话摘要。"""
    if isinstance(result, dict) and result.get("error"):
        return f"失败：{result['error'][:60]}"
    if name == "search_script":
        return result.get("note", "")
    if name == "get_scene":
        return f"第 {result.get('scene')} 场「{result.get('title', '')}」（{len(result.get('content', ''))} 字）"
    if name == "read_report_section":
        return "已读取章节" if result.get("found") else result.get("note", "")
    return ""


# ---------------------------------------------------------------------------
# 最终回答：解析 / 强制收尾 / schema 修复
# ---------------------------------------------------------------------------

def _parse_json(content):
    """宽松解析：剥掉代码块标记/前后缀后 json.loads，失败返回 None。"""
    content = (content or "").strip()
    m = re.search(r"\{.*\}", content, re.S)
    if m:
        content = m.group(0)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _validate_chat(data):
    """chat schema 校验，通过返回 None，否则返回错误描述。"""
    try:
        jsonschema.validate(data, MODULE_SCHEMAS["chat"])
        return None
    except jsonschema.ValidationError as e:
        return e.message[:200]


def _user_text(messages) -> str:
    """消息列表 → 纯文本（收尾调用不带工具，用文本重放对话）。"""
    parts = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            parts.append(f"[工具返回] {m.get('content', '')}")
        elif role == "assistant":
            calls = m.get("tool_calls") or []
            if calls:
                parts.append("[助手]（本步调用工具：" + "、".join(
                    c.get("function", {}).get("name", "") for c in calls) + "）")
            else:
                parts.append(f"[助手] {m.get('content', '')}")
        else:
            parts.append(f"[{role}] {m.get('content', '')}")
    return "\n\n".join(parts)


def _finalize(client, system, messages, first_attempt, warnings, usage_total):
    """产出并校验最终回答 JSON。失败（调用异常/校验不过且修复重试耗尽）返回 None。

    first_attempt：循环内模型已给出的正文（可能为空/非法），优先尝试免一次额外调用；
    无效则追加收尾指令，用 client.complete（json_object、无工具）强制输出并修复重试。
    """
    if first_attempt:
        parsed = _parse_json(first_attempt)
        if parsed is not None:
            err = _validate_chat(parsed)
            if err is None:
                return parsed
            warnings.append(f"[剧本医生Agent] 首答未通过校验：{err}，改用收尾调用")
        else:
            warnings.append("[剧本医生Agent] 首答不是合法 JSON，改用收尾调用")

    force_msgs = list(messages) + [{"role": "user", "content": FORCE_SUFFIX}]
    user_text = _user_text(force_msgs)
    for attempt in range(MAX_REPAIR_RETRIES + 1):
        try:
            res = client.complete(system, user_text)
        except Exception as e:
            warnings.append(f"[剧本医生Agent] 收尾调用失败：{e}（第 {attempt + 1} 次尝试）")
            continue
        u = res.get("usage") or {}
        usage_total["calls"] += 1
        usage_total["input_tokens"] += u.get("input_tokens", 0)
        usage_total["cache_hit_tokens"] += u.get("cache_hit_tokens", 0)
        usage_total["output_tokens"] += u.get("output_tokens", 0)
        data = res.get("data")
        err = _validate_chat(data) if isinstance(data, dict) else "不是 JSON 对象"
        if err is None:
            return data
        warnings.append(f"[剧本医生Agent] 收尾校验失败（第 {attempt + 1} 次）：{err}，修复重试")
        user_text += f"\n\n【上一次输出未通过校验：{err}，请修复后重新输出合法 json】"
    warnings.append(f"[剧本医生Agent] 修复重试 {MAX_REPAIR_RETRIES} 次后仍失败，降级")
    return None


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------

def run_doctor_agent(client, script_text, report, history, question,
                     step_cb=None, warnings=None):
    """剧本医生 agent：单问多轮查证。返回 (data, usage, trace)。

    step_cb(text)：每执行完一个工具后回调（UI 展示中间步骤，可为 None）。
    data 为 {"answer","evidence_quotes","confidence"}，引用已对剧本全文逐字硬校验；
    调用/校验彻底失败时 data 为 None（warnings 记录原因），调用方降级到单轮 ask_doctor。
    usage 含 calls（本问实际 LLM 调用次数）。
    trace 为 [{"name","args","summary"}]（UI 渲染查证步骤）。
    """
    warnings = warnings if warnings is not None else []
    trace = []
    scenes = analyzer.split_scenes(script_text)
    ctx_text, ctx_type = analyzer.chat_context_text(script_text)
    hist = (history or [])[-analyzer.CHAT_MAX_HISTORY:]
    hist_block = "\n".join(f"{m.get('role')}：{m.get('content')}" for m in hist) or "（无）"
    system = SYSTEM_BASE + "\n" + MODULE_SYSTEM_ADDON["chat"] + "\n" + AGENT_SYSTEM_ADDON
    user = (USER_TEMPLATES["chat"]
            .replace("{CONTEXT_TYPE}", ctx_type)
            .replace("{SCRIPT_CONTEXT}", ctx_text)
            .replace("{REPORT_DIGEST}", analyzer.report_digest(report))
            .replace("{HISTORY}", hist_block)
            .replace("{QUESTION}", question))
    messages = [{"role": "user", "content": user}]
    usage_total = {"input_tokens": 0, "cache_hit_tokens": 0, "output_tokens": 0, "calls": 0}

    def _acc(res):
        u = res.get("usage") or {}
        usage_total["calls"] += 1
        usage_total["input_tokens"] += u.get("input_tokens", 0)
        usage_total["cache_hit_tokens"] += u.get("cache_hit_tokens", 0)
        usage_total["output_tokens"] += u.get("output_tokens", 0)

    final_content = None
    for step in range(MAX_AGENT_STEPS):
        try:
            res = client.complete_with_tools(system, messages, TOOLS)
        except Exception as e:
            warnings.append(f"[剧本医生Agent] 第 {step + 1} 步调用失败：{e}")
            return None, usage_total, trace
        _acc(res)
        msg = res.get("message") or {}
        calls = msg.get("tool_calls") or []
        if not calls:
            final_content = msg.get("content") or ""
            break
        if step == MAX_AGENT_STEPS - 1:
            warnings.append(f"[剧本医生Agent] 已达最大步数 {MAX_AGENT_STEPS}，"
                            "本步查证不执行，直接收尾")
            break
        # 回写 assistant 消息（完整 tool_calls 结构）+ 逐个执行工具并回喂结果
        messages.append({
            "role": "assistant",
            "content": msg.get("content") or None,
            "tool_calls": [{
                "id": tc.get("id", f"call_{step}_{i}"),
                "type": "function",
                "function": {"name": tc.get("name", ""), "arguments": tc.get("arguments") or "{}"},
            } for i, tc in enumerate(calls[:MAX_TOOLS_PER_TURN])],
        })
        for i, tc in enumerate(calls[:MAX_TOOLS_PER_TURN]):
            result = _execute_tool(tc, scenes, report)
            summary = _tool_summary(tc.get("name", ""), result)
            trace.append({"name": tc.get("name", ""), "args": tc.get("arguments") or "{}",
                          "summary": summary})
            if step_cb:
                step_cb(f"{TOOL_LABELS.get(tc.get('name'), tc.get('name'))} · {summary}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"call_{step}_{i}"),
                "content": json.dumps(result, ensure_ascii=False)[:TOOL_RESULT_CAP],
            })

    data = _finalize(client, system, messages, final_content, warnings, usage_total)
    if data is not None:
        # 引用硬校验升级为对全文（工具可从全文取原文，长剧本不再局限于场头概览）
        flat = re.sub(r"\s+", "", script_text)
        data = analyzer._filter_quotes(data, flat, warnings, "chat")
    return data, usage_total, trace


def estimate_agent_cost(text, report, history, question="") -> dict:
    """单问 agent 成本预估（美元，闲时价）：按平均 AGENT_EST_STEPS 步 × 单轮成本估算。

    估算口径与 analyzer.estimate_chat_cost 一致，仅乘步数；实际以账单为准。
    """
    per = analyzer.estimate_chat_cost(text, report, history, question)
    usage = {
        "input_tokens": per["input_tokens"] * AGENT_EST_STEPS,
        "cache_hit_tokens": 0,
        "output_tokens": per["output_tokens"] * AGENT_EST_STEPS,
    }
    return {
        "calls": AGENT_EST_STEPS,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "est_cost_usd": round(analyzer.DeepSeekClient.estimate_cost(usage), 4),
    }
