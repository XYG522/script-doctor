"""分析编排器：文本加载、场次切分、Prompt 链（4 轮 10 调用）、长文本分块、校验与防幻觉。

流程：
- ≤2 万字：R1 解析 → R2 并行 7 模块 → R3 评分与建议 → R4 改写示例
- >2 万字：L1 场头概览解析 → L2 分块细读（8~12 场/块，重叠 1 场）→ L3 汇总合并 → R4 改写示例

防幻觉手段：
1. 引用硬校验：quote.text 去空白后必须能在原文中找到，否则剔除并记录警告
2. 出场场次由规则统计（re 匹配角色名+别名），LLM 禁止输出硬数字
3. 模块级 jsonschema 校验 + 错误回喂修复重试（≤2 次），失败则该模块降级为空
"""
import io
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import jsonschema

from llm import DeepSeekClient  # 仅用于成本预估（复用 estimate_cost 的官方单价）
from prompts import (
    MODULE_SCHEMAS,
    REPORT_SCHEMA,
    SYSTEM_BASE,
    MODULE_SYSTEM_ADDON,
    USER_TEMPLATES,
    MERGE_TEMPLATE,
)

CHUNK_THRESHOLD_CHARS = 20000
CHUNK_MAX_SCENES = 12
CHUNK_OVERLAP_SCENES = 1
MAX_REPAIR_RETRIES = 2
MODULES_R2 = ["characters", "relationships", "emotion", "pacing", "logic", "structure", "commercial"]
MODULE_LABELS = {
    "parse": "剧本解析",
    "characters": "角色分布",
    "relationships": "角色关系",
    "emotion": "情感曲线",
    "pacing": "节奏分析",
    "logic": "逻辑漏洞",
    "structure": "结构体检",
    "commercial": "商业潜力",
    "final": "评分与建议",
    "rewrite": "改写示例",
    "chat": "剧本医生",
}
# 模块 → 评分维度（relationships 无对应维度）
MODULE_DIM = {"characters": "character", "emotion": "emotion", "pacing": "pacing",
              "logic": "logic", "structure": "structure", "commercial": "commercial"}

# ---- 成本预估常量（上传页实时展示；为估算值，与实际账单有偏差）----
EST_OUTPUT_TOKENS = {"parse": 600, "characters": 500, "relationships": 400, "emotion": 600,
                     "pacing": 500, "logic": 700, "structure": 600, "commercial": 500,
                     "final": 800, "rewrite": 900, "chat": 400}
EST_OVERHEAD_TOKENS = 600    # 每次调用的模板/schema 固定开销
EST_UPSTREAM_TOKENS = 1500   # final 调用的上游 JSON 估算
EST_REWRITE_INPUT_TOKENS = 1500  # R4 改写示例：3 条建议 ~300 + 落点场次原文 ~600 + 开销 600
EST_OVERVIEW_PER_SCENE = 60  # 分块模式场头概览每场约 60 token
EST_CHARS_PER_TOKEN = 1.0    # 保守口径：1 字 ≈ 1 token（中文实际约 0.6~1.0）
EST_BUFFER = 1.2             # 输出 token 重试余量


def estimate_run_cost(text: str, modules: list) -> dict:
    """预估一次分析的调用次数与成本（美元，闲时价）。本地计算，用于上传页实时展示。

    模型：输入 = 全文/分块正文 × 1 token/字 + 每次调用固定开销；输出 = 各模块经验常数 ×1.2。
    >2 万字按本地切场估算块数（每块 12 场）。0 个模块 → 全部为 0。
    """
    modules = [m for m in modules if m in MODULES_R2]
    chars = len(text or "")
    if not modules:
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "est_cost_usd": 0.0}

    if chars > CHUNK_THRESHOLD_CHARS:
        scenes = split_scenes(text)
        chunks = max(1, math.ceil(len(scenes) / CHUNK_MAX_SCENES))
        overview = len(scenes) * EST_OVERVIEW_PER_SCENE
        per_chunk_in = (chars * EST_CHARS_PER_TOKEN) / chunks + EST_OVERHEAD_TOKENS
        calls = 1 + len(modules) * chunks + 1 + 1
        in_tok = (overview + len(modules) * chunks * per_chunk_in
                  + EST_UPSTREAM_TOKENS + EST_REWRITE_INPUT_TOKENS)
        out_tok = EST_OUTPUT_TOKENS["parse"] + sum(EST_OUTPUT_TOKENS[m] for m in modules) * chunks \
            + EST_OUTPUT_TOKENS["final"] + EST_OUTPUT_TOKENS["rewrite"]
    else:
        # R4 改写示例不携带全文，只带建议+落点场次原文 → 输入单独按常量估算
        calls = 2 + len(modules) + 1
        in_tok = (calls - 1) * (chars * EST_CHARS_PER_TOKEN + EST_OVERHEAD_TOKENS) \
            + EST_UPSTREAM_TOKENS + EST_REWRITE_INPUT_TOKENS
        out_tok = EST_OUTPUT_TOKENS["parse"] + sum(EST_OUTPUT_TOKENS[m] for m in modules) \
            + EST_OUTPUT_TOKENS["final"] + EST_OUTPUT_TOKENS["rewrite"]

    usage = {
        "input_tokens": int(in_tok),
        "cache_hit_tokens": 0,
        "output_tokens": int(out_tok * EST_BUFFER),
    }
    return {
        "calls": calls,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "est_cost_usd": round(DeepSeekClient.estimate_cost(usage), 4),
    }


def _build_review_block(prev_suggestions: list, chunked: bool) -> str:
    """把上一版建议拼成 final 调用的回顾块（改稿对比模式）；无建议时返回空串。"""
    if not prev_suggestions:
        return ""
    items = [
        {
            "rank": s.get("rank"),
            "problem": s.get("problem", ""),
            "落点场次": (s.get("action") or {}).get("scene"),
            "具体动作": (s.get("action") or {}).get("concrete", ""),
        }
        for s in prev_suggestions
    ]
    ev_note = "（分块模式看不到全文，evidence 可省略）" if chunked else ""
    return (
        "【上一版修改建议回顾】\n"
        "上一版分析给出了以下修改建议。请逐条判断当前剧本是否已落实，并在输出中增加 "
        "prev_suggestions_review 数组：rank 对应建议序号；adopted 为 true（已落实）或 false（未落实）；"
        "evidence 为当前剧本中支持判断的原文引用（逐字≤40字）" + ev_note + "；"
        "note 为判断依据≤40字；adopted=false 时，note 必须写明可执行的「还差哪一步」。\n"
        "上一版建议（json）：\n" + json.dumps(items, ensure_ascii=False)
    )


# ---------------------------------------------------------------------------
# 文本加载
# ---------------------------------------------------------------------------

def load_text(file_bytes: bytes, filename: str) -> str:
    """按扩展名解析 txt/pdf/docx；txt 自动探测 UTF-8/GBK 编码。"""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        import fitz  # PyMuPDF

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        if len(text.strip()) < 20:
            raise ValueError("PDF 未提取到文本：可能是扫描件，请改用粘贴文本。")
        return text
    if name.endswith(".docx"):
        from docx import Document

        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs)
    # txt / 未知后缀：按文本处理
    text = None
    for enc in ("utf-8", "gb18030"):
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("无法识别文件编码，请另存为 UTF-8 的 txt 后重试。")
    return text


# ---------------------------------------------------------------------------
# 场次切分
# ---------------------------------------------------------------------------

SCENE_RE = re.compile(r"^[第]?\s*([0-9一二三四五六七八九十百]+)\s*[场幕]\s*[:：]?\s*(.*)$")


def split_scenes(text: str):
    """按场号切分；无场号时按空行切成伪场景。返回 [{"n","title","content"}]。

    首个场头之前的内容（如《剧名》标题行）不建场，直接丢弃；
    全文无任何场头时才整体当作 1 场。
    """
    lines = text.splitlines()
    scenes, cur, cur_title = [], [], ""
    seen_header = False
    for line in lines:
        m = SCENE_RE.match(line.strip())
        if m:
            if seen_header and cur:
                scenes.append({
                    "n": len(scenes) + 1,
                    "title": cur_title or f"第{len(scenes) + 1}场",
                    "content": "\n".join(cur).strip(),
                })
            seen_header = True
            cur_title = f"第{m.group(1)}场 {m.group(2).strip()}".strip()
            cur = []
        else:
            cur.append(line)
    if cur:
        scenes.append({
            "n": len(scenes) + 1,
            "title": cur_title or f"第{len(scenes) + 1}段",
            "content": "\n".join(cur).strip(),
        })
    # 未识别出场号（整篇一个场景且文本较长）→ 退化为按空行分块
    if len(scenes) <= 1 and len(text) > 2000:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        scenes = [{"n": i + 1, "title": f"段{i + 1}", "content": p} for i, p in enumerate(paras)]
    return scenes


def scene_overview(scenes, head_chars=120) -> str:
    """L1 场头概览：场号+标题+每场开头，供长剧本全局解析（不包含全文）。"""
    lines = []
    for s in scenes:
        lines.append(f"{s['title']}\n{s['content'][:head_chars]}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# 规则统计（防幻觉：硬数字不交给 LLM）
# ---------------------------------------------------------------------------

def build_stats(scenes, characters) -> list:
    """按角色名单+别名，统计每个角色出现过的场次数（规则计算）。"""
    stats = []
    for ch in characters or []:
        names = [ch.get("name")] + [a for a in (ch.get("aliases") or []) if a]
        names = [n for n in names if n]
        scene_count = 0
        for s in scenes:
            if any(n in s["content"] for n in names):
                scene_count += 1
        stats.append({
            "name": ch.get("name"),
            "scene_count": scene_count,
            "role": ch.get("role"),
        })
    return stats


# ---------------------------------------------------------------------------
# 防幻觉：引用硬校验
# ---------------------------------------------------------------------------

def _filter_quotes(obj, flat_script: str, warnings: list, module: str):
    """递归遍历数据：所有 {scene,text} 引用必须去空白后命中原文，否则剔除并记录。"""
    if isinstance(obj, dict):
        if "text" in obj and "scene" in obj and isinstance(obj.get("text"), str):
            needle = re.sub(r"\s+", "", obj.get("text", ""))
            if not needle or needle not in flat_script:
                warnings.append(
                    f"[{MODULE_LABELS.get(module, module)}] 剔除未命中原文的引用："
                    f"第 {obj.get('scene')} 场 “{obj.get('text')}”"
                )
                return None
            return obj
        out = {}
        for k, v in obj.items():
            fv = _filter_quotes(v, flat_script, warnings, module)
            if fv is not None:
                out[k] = fv
        return out
    if isinstance(obj, list):
        return [x for x in (_filter_quotes(v, flat_script, warnings, module) for v in obj) if x is not None]
    return obj


# ---------------------------------------------------------------------------
# 单模块调用：schema 校验 + 修复重试 + 降级
# ---------------------------------------------------------------------------

def _run_module(client, module: str, system: str, user: str, warnings: list) -> dict:
    schema = MODULE_SCHEMAS.get(module)
    last_err = "未知错误"
    for attempt in range(MAX_REPAIR_RETRIES + 1):
        try:
            result = client.complete(system, user)
        except Exception as e:
            last_err = f"调用失败：{e}"
            warnings.append(
                f"[{MODULE_LABELS.get(module, module)}] {last_err}（第 {attempt + 1} 次尝试）"
            )
            time.sleep(1.5 * (attempt + 1))
            continue
        data = result.get("data")
        if schema is None or data is None:
            return result
        try:
            jsonschema.validate(data, schema)
            return result
        except jsonschema.ValidationError as e:
            last_err = f"JSON 校验失败：{e.message[:300]}"
            user = user + f"\n\n【上一次输出未通过校验，请修复后重新输出合法 json】\n错误信息：{last_err}"
    warnings.append(
        f"[{MODULE_LABELS.get(module, module)}] 重试 {MAX_REPAIR_RETRIES} 次后仍失败，"
        f"该模块降级为空：{last_err}"
    )
    return {
        "data": None,
        "elapsed": 0.0,
        "usage": {"input_tokens": 0, "cache_hit_tokens": 0, "output_tokens": 0},
    }


# ---------------------------------------------------------------------------
# 剧本医生对话：报告页追问（复用 SYSTEM_BASE / schema 校验 / 引用硬校验）
# ---------------------------------------------------------------------------

CHAT_MAX_HISTORY = 10  # 只携带最近 10 条对话消息，控制每问输入成本


def report_digest(report: dict) -> str:
    """把报告压成对话用的摘要上下文（评分/漏洞/建议/硬检查结论，不含引用，控制成本）。"""
    sm = report.get("script_meta") or {}
    sc = report.get("score") or {}
    dims = sc.get("dimensions") or {}
    lines = [f"标题：{sm.get('title', '未命名')}；字数 {sm.get('word_count', 0)}；场次 {sm.get('scene_count', 0)}"]
    ov = sc.get("overall")
    lines.append("综合评分：" + (f"{ov}/100" if ov is not None else "未评分（本次未运行评分模块）"))
    if dims:
        zh = {"character": "角色", "emotion": "情感", "pacing": "节奏", "logic": "逻辑",
              "structure": "结构", "commercial": "商业"}
        lines.append("分项：" + "、".join(
            f"{zh.get(k, k)} {v}" for k, v in dims.items() if isinstance(v, (int, float))))
    holes = (report.get("logic") or {}).get("holes") or []
    lines.append("逻辑漏洞：" + (
        "；".join(f"[{h.get('id')}][{h.get('severity')}] {h.get('description', '')}" for h in holes[:8])
        if holes else "未检出"))
    sugg = report.get("suggestions") or []
    lines.append("修改建议：" + (
        "；".join(f"{s.get('rank')}. {s.get('problem', '')}"
                  f"（落点第 {(s.get('action') or {}).get('scene', '?')} 场）" for s in sugg[:3])
        if sugg else "无"))
    hc = report.get("hard_checks")
    if hc:
        lines.append("硬检查：" + hc.get("dialogue", {}).get("verdict", "")
                     + "；" + hc.get("scenes", {}).get("verdict", ""))
    return "\n".join(lines)


def chat_context_text(text: str):
    """剧本医生上下文：≤2 万字直接塞全文；更长用场头概览（与分块模式 R1 同口径）。

    返回 (context, context_type)；引用逐字校验一律针对 context 做。
    """
    text = text or ""
    if len(text) <= CHUNK_THRESHOLD_CHARS:
        return text, "全文"
    return scene_overview(split_scenes(text)), "场头概览（长剧本，不含全文）"


def estimate_chat_cost(text: str, report: dict, history: list, question: str = "") -> dict:
    """单次追问的预估成本（美元，闲时价）。本地计算，用于报告页对话区展示。"""
    context, _ = chat_context_text(text)
    hist_chars = sum(len(m.get("content", "")) for m in (history or [])[-CHAT_MAX_HISTORY:])
    in_tok = (len(context) * EST_CHARS_PER_TOKEN + len(report_digest(report))
              + hist_chars + len(question or "") + EST_OVERHEAD_TOKENS)
    usage = {
        "input_tokens": int(in_tok),
        "cache_hit_tokens": 0,
        "output_tokens": int(EST_OUTPUT_TOKENS["chat"] * EST_BUFFER),
    }
    return {
        "calls": 1,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "est_cost_usd": round(DeepSeekClient.estimate_cost(usage), 4),
    }


def ask_doctor(client, script_text: str, report: dict, history: list, question: str,
               warnings=None):
    """剧本医生单轮追问：返回 (data, usage)。

    data 为 {"answer", "evidence_quotes", "confidence"}，引用已逐字硬校验（未命中的被剔除）；
    校验/调用失败时 data 为 None（warnings 记录原因），调用方降级展示。
    """
    warnings = warnings if warnings is not None else []
    context, ctx_type = chat_context_text(script_text)
    hist = (history or [])[-CHAT_MAX_HISTORY:]
    hist_block = "\n".join(f"{m.get('role')}：{m.get('content')}" for m in hist) or "（无）"
    system = SYSTEM_BASE + "\n" + MODULE_SYSTEM_ADDON["chat"]
    user = (USER_TEMPLATES["chat"]
            .replace("{CONTEXT_TYPE}", ctx_type)
            .replace("{SCRIPT_CONTEXT}", context)
            .replace("{REPORT_DIGEST}", report_digest(report))
            .replace("{HISTORY}", hist_block)
            .replace("{QUESTION}", question))
    res = _run_module(client, "chat", system, user, warnings)
    data = res.get("data")
    if data is not None:
        data = _filter_quotes(data, re.sub(r"\s+", "", context), warnings, "chat")
    return data, res.get("usage") or {"input_tokens": 0, "cache_hit_tokens": 0, "output_tokens": 0}


# ---------------------------------------------------------------------------
# 长剧本：L2 分块细读 + L3 合并
# ---------------------------------------------------------------------------

def _merge_module(module: str, parts: list):
    """合并各分块的模块结果（曲线拼接、漏洞去重、列表拼接）。"""
    parts = [p for p in parts if p]
    if not parts:
        return None
    if module == "characters":
        cast, issues = [], []
        for p in parts:
            for c in p.get("cast", []):
                if c.get("name") not in [x.get("name") for x in cast]:
                    cast.append(c)
            issues += p.get("distribution_issues", [])
        return {"cast": cast, "distribution_issues": issues}
    if module == "relationships":
        seen, out = set(), []
        for p in parts:
            for r in p.get("relationships", []):
                key = tuple(sorted(r.get("pair", [])))
                if key not in seen:
                    seen.add(key)
                    out.append(r)
        return {"relationships": out}
    if module == "emotion":
        points, seen = [], set()
        for p in parts:
            for pt in p.get("points", []):
                # 多角色曲线：同一角色同一场只留一个点；旧数据无 character 时退化为按场去重
                key = (pt.get("character"), pt.get("scene"))
                if key not in seen:
                    seen.add(key)
                    points.append(pt)
        points.sort(key=lambda x: x.get("scene", 0))
        flat_issues = []
        for p in parts:
            flat_issues += p.get("flatness_issues", [])
        return {
            "granularity": "scene",
            "points": points,
            "summary": parts[-1].get("summary", ""),
            "flatness_issues": flat_issues,
        }
    if module == "pacing":
        dragging, rushed, per_act = [], [], []
        for i, p in enumerate(parts):
            dragging += p.get("dragging_scenes", [])
            rushed += p.get("rushed_scenes", [])
            for a in p.get("per_act", []):
                a2 = dict(a)
                a2["act"] = i + 1  # 分块模式下幕号按块序重新编号（近似）
                per_act.append(a2)
        return {
            "per_act": per_act,
            "dragging_scenes": dragging,
            "rushed_scenes": rushed,
            "overall_verdict": parts[-1].get("overall_verdict", ""),
        }
    if module == "logic":
        holes = []
        for p in parts:
            holes += p.get("holes", [])
        return {"holes": holes}
    if module == "commercial":
        merged = {
            "genre_elements": [], "target_audience": "", "benchmarks": [],
            "strengths": [], "risks": [], "confidence": 1.0,
        }
        for p in parts:
            for k in ("genre_elements", "benchmarks", "strengths", "risks"):
                for x in p.get(k, []):
                    if x not in merged[k]:
                        merged[k].append(x)
            if not merged["target_audience"]:
                merged["target_audience"] = p.get("target_audience", "")
            try:
                merged["confidence"] = min(merged["confidence"], float(p.get("confidence", 0.5)))
            except (TypeError, ValueError):
                pass
        return merged
    if module == "structure":
        foreshadows, seen_f, arcs = [], set(), []
        for p in parts:
            for f in p.get("foreshadows", []):
                key = (f.get("setup_scene"), (f.get("setup") or "").strip())
                if key not in seen_f:
                    seen_f.add(key)
                    foreshadows.append(f)
            for a in p.get("arcs", []):
                if a.get("character") not in [x.get("character") for x in arcs]:
                    arcs.append(a)
        return {
            # 三幕跨越全文：分块各自划分不可信，仅取末块（含结局）划分
            "acts": parts[-1].get("acts", []),
            "beats": [b for p in parts for b in p.get("beats", [])],
            "foreshadows": foreshadows,
            "arcs": arcs,
        }
    return parts[-1]


def _validate_structure(data: dict, warnings: list) -> dict:
    """结构模块规则校验：伏笔回收场次必须 ≥ 埋点场次。

    已回收（resolved）但回收场次小于埋点场次 → 疑似编造，强制改为 unresolved、
    清空回收内容并告警；status 缺失/非法也归为 unresolved。保证报告页
    「回收 ≥ 埋点」的口径成立（与逻辑漏洞模块同源的防幻觉约束）。
    """
    out = {
        "acts": data.get("acts") or [],
        "beats": data.get("beats") or [],
        "foreshadows": [],
        "arcs": data.get("arcs") or [],
    }
    for f in data.get("foreshadows") or []:
        f = dict(f)
        try:
            setup = int(f.get("setup_scene") or 0)
            payoff = int(f.get("payoff_scene") or 0)
        except (TypeError, ValueError):
            setup, payoff = 0, 0
        if f.get("status") not in ("resolved", "unresolved"):
            f["status"] = "unresolved"
        if f.get("status") == "resolved" and payoff < setup:
            warnings.append(
                f"[结构体检] 伏笔回收场次（第 {payoff} 场）小于埋点场次（第 {setup} 场），"
                f"疑似编造，已按未回收处理：{(f.get('setup') or '')[:30]}"
            )
            f["status"] = "unresolved"
            f["payoff"] = ""
            f["payoff_scene"] = None
        out["foreshadows"].append(f)
    return out


def _run_chunked(client, script_text, scenes, stats, progress, track, warnings, modules) -> dict:
    """L2：分块细读（每块 8~12 场、重叠 1 场），块间并行；逐块做引用硬校验。"""
    flat = re.sub(r"\s+", "", script_text)
    chunks, i = [], 0
    while i < len(scenes):
        j = min(i + CHUNK_MAX_SCENES, len(scenes))
        chunks.append(scenes[i:j])
        i = j - CHUNK_OVERLAP_SCENES if j < len(scenes) else len(scenes)

    def _one_chunk(ci, chunk_scenes):
        text = "\n\n".join(f"{s['title']}\n{s['content']}" for s in chunk_scenes)
        ctx = {"SCRIPT": text, "STATS": json.dumps(stats, ensure_ascii=False)}
        out = {}
        for module in modules:
            system = SYSTEM_BASE + "\n" + MODULE_SYSTEM_ADDON[module]
            user = USER_TEMPLATES[module]
            for ph, val in ctx.items():
                user = user.replace("{" + ph + "}", val)
            res = _run_module(client, module, system, user, warnings)
            track(res, f"{module}#c{ci + 1}")
            data = res.get("data")
            out[module] = _filter_quotes(data, flat, warnings, module) if data is not None else None
        return ci, out

    results = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(_one_chunk, ci, cs): ci for ci, cs in enumerate(chunks)}
        done = 0
        for fut in as_completed(futures):
            ci, out = fut.result()
            results[ci] = out
            done += 1
            progress(
                0.2 + 0.5 * done / len(chunks),
                f"② 分块分析 {done}/{len(chunks)} 块（每块 {CHUNK_MAX_SCENES} 场，重叠 {CHUNK_OVERLAP_SCENES} 场）",
            )

    merged = {}
    for m in modules:
        merged[m] = _merge_module(m, [results[c].get(m) for c in sorted(results)])
    return merged


# ---------------------------------------------------------------------------
# 报告组装
# ---------------------------------------------------------------------------

def _assemble(script_text, scenes, parse_data, clean, final_data, client, chunked,
              usage_total, timings):
    """把各模块结果组装为最终报告；注入规则统计的出场场次；整体 schema 校验。"""
    warnings = []
    parse_chars = {c.get("name"): c for c in (parse_data or {}).get("characters", [])}
    stats = build_stats(scenes, parse_data.get("characters", []) if parse_data else [])

    chars_obj = clean.get("characters") or {}
    cast = []
    for item in chars_obj.get("cast", []):
        pc = parse_chars.get(item.get("name"), {})
        item["role"] = pc.get("role", "supporting")
        item["first_scene"] = pc.get("first_scene", 1)
        item["aliases"] = pc.get("aliases", [])
        st_item = next((s for s in stats if s["name"] == item.get("name")), None)
        item["scene_count"] = st_item["scene_count"] if st_item else 0
        cast.append(item)
    # 补上 M2 遗漏的角色（仅基础信息）
    for name, pc in parse_chars.items():
        if name not in [c.get("name") for c in cast]:
            st_item = next((s for s in stats if s["name"] == name), None)
            cast.append({
                "name": name,
                "role": pc.get("role", "supporting"),
                "first_scene": pc.get("first_scene", 1),
                "aliases": pc.get("aliases", []),
                "scene_count": st_item["scene_count"] if st_item else 0,
                "function": "",
                "analysis": "",
            })

    report = {
        "script_meta": {
            "title": parse_data.get("title") or "未命名剧本",
            "word_count": len(script_text),
            "scene_count": len(scenes),
            "acts": parse_data.get("acts", []),
        },
        "score": final_data.get("score", {"overall": 0, "dimensions": {}}),
        "characters": {"cast": cast, "distribution_issues": chars_obj.get("distribution_issues", [])},
        "relationships": (clean.get("relationships") or {}).get("relationships", []),
        "emotion_curve": clean.get("emotion") or {
            "granularity": "scene", "points": [], "summary": "", "flatness_issues": [],
        },
        "pacing": clean.get("pacing") or {
            "per_act": [], "overall_verdict": "", "dragging_scenes": [], "rushed_scenes": [],
        },
        "logic": {"holes": (clean.get("logic") or {}).get("holes", [])},
        "structure": clean.get("structure") or {
            "acts": [], "beats": [], "foreshadows": [], "arcs": [],
        },
        "commercial": clean.get("commercial") or {
            "genre_elements": [], "target_audience": "", "benchmarks": [],
            "strengths": [], "risks": [], "confidence": 0.0,
        },
        "suggestions": (final_data.get("suggestions") or [])[:3],
        "rewrites": ((clean.get("rewrite") or {}).get("rewrites") or [])[:3],
        "prev_suggestions_review": final_data.get("prev_suggestions_review") or [],
        "meta": {
            "model": client.model,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "is_cached_demo": False,
            "chunked": chunked,
            "tokens": usage_total,
            "est_cost_usd": round(client.estimate_cost(usage_total), 4),
            "timings": timings,
        },
    }
    report["score"]["disclaimer"] = "AI参考分，非行业标准评价"

    # 整体校验：失败仅警告，不阻断渲染
    try:
        jsonschema.validate(report, REPORT_SCHEMA)
    except jsonschema.ValidationError as e:
        warnings.append(f"最终报告整体校验未通过（不影响查看）：{e.message[:200]}")
    return report, warnings


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_pipeline(script_text: str, client, progress_cb=None, prev_suggestions=None, modules=None):
    """执行完整 Prompt 链，返回 (report, warnings)。

    progress_cb(fraction: float, label: str) 由调用方传入（如 Streamlit 进度条）。
    prev_suggestions：上一版报告的 suggestions 列表（改稿对比模式）。非空时注入 final 调用，
    模型逐条判断是否已落实，结果挂 report["prev_suggestions_review"]。
    modules：勾选的 AI 模块（MODULES_R2 子集）；None=全选（老调用兼容）；
    []=只跑免费硬检查（0 次 LLM 调用，报告无 score）。
    """
    if modules is None:
        modules = list(MODULES_R2)
    modules = [m for m in modules if m in MODULES_R2]
    warnings = []
    t0 = time.time()
    timings = {}
    usage_total = {"input_tokens": 0, "cache_hit_tokens": 0, "output_tokens": 0, "calls": 0}

    def track(res, label):
        usage_total["calls"] += 1
        usage_total["input_tokens"] += res.get("usage", {}).get("input_tokens", 0)
        usage_total["cache_hit_tokens"] += res.get("usage", {}).get("cache_hit_tokens", 0)
        usage_total["output_tokens"] += res.get("usage", {}).get("output_tokens", 0)
        timings[label] = round(res.get("elapsed", 0), 1)

    def progress(fraction, label):
        if progress_cb:
            progress_cb(fraction, label)

    # ---- 切分 ----
    scenes = split_scenes(script_text)
    chunked = len(script_text) > CHUNK_THRESHOLD_CHARS
    if chunked:
        progress(0.05, f"剧本 {len(script_text)} 字（>2 万），启用分块模式：{len(scenes)} 场")
    else:
        progress(0.05, f"剧本 {len(script_text)} 字，单次上下文内分析：{len(scenes)} 场")

    # ---- 0 个 AI 模块：纯免费硬检查（本地计算，不调 LLM）----
    if not modules:
        progress(0.3, "0 个 AI 模块：仅运行免费硬检查（本地计算）")
        import hardcheck  # noqa: F401 函数内导入：hardcheck 顶部复用 analyzer.split_scenes，避免循环依赖
        first_line = next((ln.strip() for ln in script_text.splitlines() if ln.strip()), "")
        title = re.sub(r"[《》]", "", first_line).strip()[:20] or "未命名剧本"
        report = {
            "script_meta": {"title": title, "word_count": len(script_text),
                            "scene_count": len(scenes), "acts": []},
            "suggestions": [],
            "prev_suggestions_review": [],
            "meta": {
                "model": client.model,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "is_cached_demo": False,
                "chunked": False,
                "modules_selected": [],
                "tokens": usage_total,
                "est_cost_usd": 0.0,
                "est_run": estimate_run_cost(script_text, []),
                "timings": timings,
                "total_elapsed_sec": 0.0,
            },
        }
        report["hard_checks"] = hardcheck.run_hard_checks(script_text, scenes)
        report["meta"]["total_elapsed_sec"] = round(time.time() - t0, 1)
        progress(1.0, "完成")
        return report, warnings

    # ---- R1 解析 ----
    progress(0.15, "① 剧本解析（场次表 / 幕结构 / 角色名单）")
    system1 = SYSTEM_BASE + "\n" + MODULE_SYSTEM_ADDON["parse"]
    src = scene_overview(scenes) if chunked else script_text
    user1 = USER_TEMPLATES["parse"].replace("{SCRIPT}", src)
    r1 = _run_module(client, "parse", system1, user1, warnings)
    track(r1, "parse")
    parse_data = r1["data"] or {"title": "", "scenes": [], "acts": [], "characters": []}

    stats = build_stats(scenes, parse_data.get("characters", []))

    # ---- R2 勾选模块 ----
    clean = {}
    if chunked:
        clean = _run_chunked(client, script_text, scenes, stats, progress, track, warnings, modules)
    else:
        ctx = {"SCRIPT": script_text, "STATS": json.dumps(stats, ensure_ascii=False)}

        def _one(module):
            system = SYSTEM_BASE + "\n" + MODULE_SYSTEM_ADDON[module]
            user = USER_TEMPLATES[module]
            for ph, val in ctx.items():
                user = user.replace("{" + ph + "}", val)
            return module, _run_module(client, module, system, user, warnings)

        results = {}
        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(_one, m): m for m in modules}
            done = 0
            for fut in as_completed(futures):
                module, res = fut.result()
                results[module] = res
                done += 1
                progress(
                    0.2 + 0.5 * done / len(modules),
                    f"② 并行分析 {done}/{len(modules)}：{MODULE_LABELS[module]} 完成",
                )
        flat = re.sub(r"\s+", "", script_text)
        for module, res in results.items():
            track(res, module)
            data = res.get("data")
            clean[module] = _filter_quotes(data, flat, warnings, module) if data is not None else None

    # 结构模块规则校验：伏笔回收场次 ≥ 埋点场次（分块合并结果同样适用）
    if clean.get("structure"):
        clean["structure"] = _validate_structure(clean["structure"], warnings)

    # ---- R3 评分与建议 ----
    progress(0.85, "③ 综合评分与 3 条修改建议")
    system8 = SYSTEM_BASE + "\n" + MODULE_SYSTEM_ADDON["final"]
    upstream = {k: v for k, v in clean.items() if v}
    prev_block = _build_review_block(prev_suggestions, chunked)
    if chunked:
        user8 = (
            MERGE_TEMPLATE
            .replace("{UPSTREAM}", json.dumps(upstream, ensure_ascii=False))
            .replace("{PREV_SUGGESTIONS}", prev_block)
        )
    else:
        user8 = (
            USER_TEMPLATES["final"]
            .replace("{UPSTREAM}", json.dumps(upstream, ensure_ascii=False))
            .replace("{SCRIPT}", script_text)
            .replace("{PREV_SUGGESTIONS}", prev_block)
        )
    r8 = _run_module(client, "final", system8, user8, warnings)
    track(r8, "final")
    final_data = r8["data"] or {"score": {"overall": 0, "dimensions": {}}, "suggestions": []}
    if final_data:
        final_data = _filter_quotes(final_data, re.sub(r"\s+", "", script_text), warnings, "final")

    # ---- R4 改写示例（每条建议 → 可直接替换的剧本片段；只喂落点场次原文）----
    suggestions = final_data.get("suggestions") or []
    if suggestions:
        progress(0.9, "④ 改写示例（建议 → 可直接替换的片段）")
        scene_map = {s["n"]: s for s in scenes}
        scene_parts = []
        for s in suggestions[:3]:
            sc = (s.get("action") or {}).get("scene")
            content = (scene_map.get(sc) or {}).get("content", "")
            if content:
                scene_parts.append(f"第{sc}场：\n{content}")
        scene_text = "\n\n".join(scene_parts) or "（无对应场次原文，仅基于建议给出改写方向）"
        user_rw = (
            USER_TEMPLATES["rewrite"]
            .replace("{SUGGESTIONS}", json.dumps(suggestions, ensure_ascii=False))
            .replace("{SCENE_TEXT}", scene_text)
        )
        r_rw = _run_module(client, "rewrite",
                           SYSTEM_BASE + "\n" + MODULE_SYSTEM_ADDON["rewrite"],
                           user_rw, warnings)
        track(r_rw, "rewrite")
        rw_data = r_rw["data"]
        if rw_data is not None:
            rw_data = _filter_quotes(rw_data, re.sub(r"\s+", "", script_text), warnings, "rewrite")
        clean["rewrite"] = rw_data

    # ---- 组装 ----
    progress(0.95, "组装报告与整体校验")
    report, asm_warnings = _assemble(
        script_text, scenes, parse_data, clean, final_data, client, chunked, usage_total, timings
    )
    warnings += asm_warnings
    # ---- 模块勾选落地：未选模块的评分维度剔除（校验后过滤，schema 不限制 dimensions 键）----
    sel_dims = {MODULE_DIM[m] for m in modules if m in MODULE_DIM}
    if sel_dims != set(MODULE_DIM.values()):
        dims = report["score"]["dimensions"]
        report["score"]["dimensions"] = {k: v for k, v in dims.items() if k in sel_dims}
    report["meta"]["modules_selected"] = modules
    report["meta"]["est_run"] = estimate_run_cost(script_text, modules)
    # ---- 规则硬检查（本地计算，不调 LLM；挂在整体 schema 校验之后，不影响校验）----
    import hardcheck  # noqa: E402 函数内导入：hardcheck 顶部复用 analyzer.split_scenes，避免循环依赖
    report["hard_checks"] = hardcheck.run_hard_checks(script_text, scenes)
    report["meta"]["total_elapsed_sec"] = round(time.time() - t0, 1)
    progress(1.0, "完成")
    return report, warnings
