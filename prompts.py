"""Prompt 链与 JSON Schema —— AI 剧本体检报告。

约定：
- 所有 LLM 输出必须是 json 对象（DeepSeek json_object 模式要求 prompt 含 "json" 字样，已保证）
- 引用类字段统一为 {"scene": 场次号, "text": 逐字引用原文 ≤40 字}
- 置信度锚点：0.9=原文直接支持 / 0.7=多线索推断 / 0.5=弱线索 / 0.3=仅印象
- 模板占位符：{SCRIPT} 剧本文本、{STATS} 规则统计表、{UPSTREAM} 上游模块结果
"""

# ---------------------------------------------------------------------------
# JSON Schema（draft 2020-12）
# ---------------------------------------------------------------------------

QUOTE = {
    "type": "object",
    "required": ["scene", "text"],
    "properties": {"scene": {"type": "integer"}, "text": {"type": "string"}},
}

# 最终报告整体 schema（用于文档与整体校验）
REPORT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "script_meta", "score", "characters", "relationships",
        "emotion_curve", "pacing", "logic", "structure", "commercial", "suggestions", "meta",
    ],
    "properties": {
        "script_meta": {
            "type": "object",
            "required": ["word_count", "scene_count", "acts"],
            "properties": {
                "title": {"type": "string"},
                "word_count": {"type": "integer"},
                "scene_count": {"type": "integer"},
                "acts": {"type": "array"},
            },
        },
        "score": {
            "type": "object",
            "required": ["overall", "dimensions"],
            "properties": {
                "overall": {"type": "integer", "minimum": 0, "maximum": 100},
                "dimensions": {"type": "object"},
            },
        },
        "characters": {
            "type": "object",
            "required": ["cast", "distribution_issues"],
            "properties": {
                "cast": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name", "role", "first_scene", "function", "analysis"],
                        "properties": {
                            "name": {"type": "string"},
                            "role": {"type": "string"},
                            "first_scene": {"type": "integer"},
                            "aliases": {"type": "array", "items": {"type": "string"}},
                            "scene_count": {"type": "integer"},
                            "function": {"type": "string"},
                            "analysis": {"type": "string"},
                            "evidence": QUOTE,
                        },
                    },
                },
                "distribution_issues": {"type": "array", "items": {"type": "string"}},
            },
        },
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["pair", "type", "trajectory"],
                "properties": {
                    "pair": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": {"type": "string"},
                    },
                    "type": {"type": "string"},
                    "trajectory": {"type": "string"},
                    "turning_points": {"type": "array", "items": QUOTE},
                    "issues": {"type": "string"},
                },
            },
        },
        "emotion_curve": {
            "type": "object",
            "required": ["granularity", "points"],
            "properties": {
                "granularity": {"type": "string"},
                "points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["scene", "value"],
                        "properties": {
                            "scene": {"type": "integer"},
                            "value": {"type": "number", "minimum": -2, "maximum": 2},
                            "character": {"type": "string"},
                            "label": {"type": "string"},
                            "evidence": QUOTE,
                        },
                    },
                },
                "summary": {"type": "string"},
                "flatness_issues": {"type": "array", "items": {"type": "string"}},
            },
        },
        "pacing": {
            "type": "object",
            "required": ["per_act", "overall_verdict"],
            "properties": {
                "per_act": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["act", "tension", "verdict", "reason"],
                        "properties": {
                            "act": {"type": "integer"},
                            "tension": {"type": "number", "minimum": 0, "maximum": 10},
                            "verdict": {"type": "string"},
                            "reason": {"type": "string"},
                            "evidence": QUOTE,
                        },
                    },
                },
                "dragging_scenes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["scene", "value"],
                        "properties": {
                            "scene": {"type": "integer"},
                            "value": {"type": "number", "minimum": 0, "maximum": 10},
                            "label": {"type": "string"},
                            "evidence": QUOTE,
                        },
                    },
                },
                "rushed_scenes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["scene", "value"],
                        "properties": {
                            "scene": {"type": "integer"},
                            "value": {"type": "number", "minimum": 0, "maximum": 10},
                            "label": {"type": "string"},
                            "evidence": QUOTE,
                        },
                    },
                },
                "overall_verdict": {"type": "string"},
            },
        },
        "logic": {
            "type": "object",
            "required": ["holes"],
            "properties": {
                "holes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "id", "severity", "type", "description",
                            "evidence_quotes", "confidence", "basis",
                        ],
                        "properties": {
                            "id": {"type": "string"},
                            "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                            "type": {"type": "string", "enum": ["逻辑漏洞", "动机问题", "设定矛盾"]},
                            "description": {"type": "string"},
                            "evidence_quotes": {"type": "array", "items": QUOTE},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "basis": {"type": "string"},
                            "suggestion_hint": {"type": "string"},
                        },
                    },
                }
            },
        },
        "structure": {
            "type": "object",
            "required": ["acts", "beats", "foreshadows", "arcs"],
            "properties": {
                "acts": {"type": "array"},
                "beats": {"type": "array"},
                "foreshadows": {"type": "array"},
                "arcs": {"type": "array"},
            },
        },
        "commercial": {
            "type": "object",
            "required": ["genre_elements", "target_audience", "strengths", "risks", "confidence"],
            "properties": {
                "genre_elements": {"type": "array", "items": {"type": "string"}},
                "target_audience": {"type": "string"},
                "benchmarks": {"type": "array", "items": {"type": "string"}},
                "strengths": {"type": "array", "items": {"type": "string"}},
                "risks": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
        "suggestions": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["rank", "problem", "action", "expected_effect"],
                "properties": {
                    "rank": {"type": "integer"},
                    "problem": {"type": "string"},
                    "action": {
                        "type": "object",
                        "required": ["scene", "concrete"],
                        "properties": {
                            "scene": {"type": "integer"},
                            "concrete": {"type": "string"},
                        },
                    },
                    "expected_effect": {"type": "string"},
                    "references": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "rewrites": {"type": "array"},
        "prev_suggestions_review": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["rank", "adopted"],
                "properties": {
                    "rank": {"type": "integer"},
                    "adopted": {"type": "boolean"},
                    "evidence": QUOTE,
                    "note": {"type": "string"},
                },
            },
        },
        "meta": {
            "type": "object",
            "required": ["model", "generated_at", "is_cached_demo"],
            "properties": {
                "model": {"type": "string"},
                "generated_at": {"type": "string"},
                "is_cached_demo": {"type": "boolean"},
            },
        },
    },
}

# 各模块输出的小 schema（用于模块级校验 + 修复重试）
MODULE_SCHEMAS = {
    "parse": {
        "type": "object",
        "required": ["scenes", "characters"],
        "properties": {
            "title": {"type": "string"},
            "scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["n", "title"],
                    "properties": {
                        "n": {"type": "integer"},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                },
            },
            "acts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["n", "name", "scene_range"],
                    "properties": {
                        "n": {"type": "integer"},
                        "name": {"type": "string"},
                        "scene_range": {"type": "string"},
                    },
                },
            },
            "characters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "role", "first_scene"],
                    "properties": {
                        "name": {"type": "string"},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "role": {"type": "string"},
                        "first_scene": {"type": "integer"},
                    },
                },
            },
        },
    },
    "characters": {
        "type": "object",
        "required": ["cast", "distribution_issues"],
        "properties": {
            "cast": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "function", "analysis"],
                    "properties": {
                        "name": {"type": "string"},
                        "function": {"type": "string"},
                        "analysis": {"type": "string"},
                        "evidence": QUOTE,
                    },
                },
            },
            "distribution_issues": {"type": "array", "items": {"type": "string"}},
        },
    },
    "relationships": {
        "type": "object",
        "required": ["relationships"],
        "properties": {
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["pair", "type", "trajectory"],
                    "properties": {
                        "pair": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 2,
                            "items": {"type": "string"},
                        },
                        "type": {"type": "string"},
                        "trajectory": {"type": "string"},
                        "turning_points": {"type": "array", "items": QUOTE},
                        "issues": {"type": "string"},
                    },
                },
            }
        },
    },
    "emotion": {
        "type": "object",
        "required": ["granularity", "points"],
        "properties": {
            "granularity": {"type": "string"},
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["scene", "value"],
                    "properties": {
                        "scene": {"type": "integer"},
                        "value": {"type": "number", "minimum": -2, "maximum": 2},
                        "character": {"type": "string"},
                        "label": {"type": "string"},
                        "evidence": QUOTE,
                    },
                },
            },
            "summary": {"type": "string"},
            "flatness_issues": {"type": "array", "items": {"type": "string"}},
        },
    },
    "pacing": {
        "type": "object",
        "required": ["per_act", "overall_verdict"],
        "properties": {
            "per_act": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["act", "tension", "verdict", "reason"],
                    "properties": {
                        "act": {"type": "integer"},
                        "tension": {"type": "number", "minimum": 0, "maximum": 10},
                        "verdict": {"type": "string"},
                        "reason": {"type": "string"},
                        "evidence": QUOTE,
                    },
                },
            },
            "dragging_scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["scene", "value"],
                    "properties": {
                        "scene": {"type": "integer"},
                        "value": {"type": "number", "minimum": 0, "maximum": 10},
                        "label": {"type": "string"},
                        "evidence": QUOTE,
                    },
                },
            },
            "rushed_scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["scene", "value"],
                    "properties": {
                        "scene": {"type": "integer"},
                        "value": {"type": "number", "minimum": 0, "maximum": 10},
                        "label": {"type": "string"},
                        "evidence": QUOTE,
                    },
                },
            },
            "overall_verdict": {"type": "string"},
        },
    },
    "logic": {
        "type": "object",
        "required": ["holes"],
        "properties": {
            "holes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "id", "severity", "type", "description",
                        "evidence_quotes", "confidence", "basis",
                    ],
                    "properties": {
                        "id": {"type": "string"},
                        "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                        "type": {"type": "string", "enum": ["逻辑漏洞", "动机问题", "设定矛盾"]},
                        "description": {"type": "string"},
                        "evidence_quotes": {"type": "array", "items": QUOTE},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "basis": {"type": "string"},
                        "suggestion_hint": {"type": "string"},
                    },
                },
            }
        },
    },
    "structure": {
        "type": "object",
        "required": ["acts", "beats", "foreshadows", "arcs"],
        "properties": {
            "acts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["act", "name", "scene_start", "scene_end", "summary"],
                    "properties": {
                        "act": {"type": "integer"},
                        "name": {"type": "string"},
                        "scene_start": {"type": "integer"},
                        "scene_end": {"type": "integer"},
                        "summary": {"type": "string"},
                    },
                },
            },
            "beats": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "scene", "description"],
                    "properties": {
                        "name": {"type": "string"},
                        "scene": {"type": "integer"},
                        "description": {"type": "string"},
                        "evidence": QUOTE,
                    },
                },
            },
            "foreshadows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["setup", "setup_scene", "status"],
                    "properties": {
                        "setup": {"type": "string"},
                        "setup_scene": {"type": "integer"},
                        "payoff": {"type": "string"},
                        "payoff_scene": {"type": "integer"},
                        "status": {"type": "string", "enum": ["resolved", "unresolved"]},
                    },
                },
            },
            "arcs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["character", "start_state", "turning_event", "turning_scene", "end_state"],
                    "properties": {
                        "character": {"type": "string"},
                        "start_state": {"type": "string"},
                        "turning_event": {"type": "string"},
                        "turning_scene": {"type": "integer"},
                        "end_state": {"type": "string"},
                    },
                },
            },
        },
    },
    "commercial": {
        "type": "object",
        "required": ["genre_elements", "target_audience", "strengths", "risks", "confidence"],
        "properties": {
            "genre_elements": {"type": "array", "items": {"type": "string"}},
            "target_audience": {"type": "string"},
            "benchmarks": {"type": "array", "items": {"type": "string"}},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    },
    "rewrite": {
        "type": "object",
        "required": ["rewrites"],
        "properties": {
            "rewrites": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "required": ["rank", "original", "rewritten", "note"],
                    "properties": {
                        "rank": {"type": "integer"},
                        "original": QUOTE,
                        "rewritten": {"type": "string"},
                        "note": {"type": "string"},
                    },
                },
            },
        },
    },
    "chat": {
        "type": "object",
        "required": ["answer", "confidence"],
        "properties": {
            "answer": {"type": "string"},
            "evidence_quotes": {"type": "array", "items": QUOTE},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    },
    "final": {
        "type": "object",
        "required": ["score", "suggestions"],
        "properties": {
            "score": {
                "type": "object",
                "required": ["overall", "dimensions"],
                "properties": {
                    "overall": {"type": "integer", "minimum": 0, "maximum": 100},
                    "dimensions": {"type": "object"},
                },
            },
            "suggestions": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "required": ["rank", "problem", "action", "expected_effect"],
                    "properties": {
                        "rank": {"type": "integer"},
                        "problem": {"type": "string"},
                        "action": {
                            "type": "object",
                            "required": ["scene", "concrete"],
                            "properties": {
                                "scene": {"type": "integer"},
                                "concrete": {"type": "string"},
                            },
                        },
                        "expected_effect": {"type": "string"},
                        "references": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "prev_suggestions_review": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["rank", "adopted"],
                    "properties": {
                        "rank": {"type": "integer"},
                        "adopted": {"type": "boolean"},
                        "evidence": QUOTE,
                        "note": {"type": "string"},
                    },
                },
            },
        },
    },
}

# ---------------------------------------------------------------------------
# 系统提示词
# ---------------------------------------------------------------------------

SYSTEM_BASE = """你是资深剧本审读顾问，服务对象是编剧与剧本策划。你的分析将进入"剧本体检报告"。

【硬性规则】
1. 所有结论可追溯：每条判断要么附原文引用（逐字抄自剧本，≤40字，注明场次），要么明确不填 evidence 并降低置信度。
2. 严禁编造：剧本中不存在的情节、台词、人物一律不得声称存在；引用必须能在原文中找到。
3. 场次号只能使用场次表中的编号；角色名只能使用角色名单中的规范名。
4. 找不到证据时：相关字段输出空数组或空字符串，不得虚构。
5. 置信度 confidence（0~1）锚点：0.9=原文直接支持；0.7=多处线索综合推断；0.5=单一弱线索或行业惯例；0.3=仅风格印象、无原文证据。
6. 你的意见是参考性分析，不是行业标准评价。

【输出格式】
只输出一个合法 json 对象（遵循任务给定的 schema），不要输出解释文字、代码块标记或 json 以外的任何内容。"""

MODULE_SYSTEM_ADDON = {
    "parse": "你是剧本结构解析器。只做事实提取，不做任何评价。",
    "characters": "你是角色维度分析师。出场次数以提供的统计表为准——你的任务是解读分布，不是数数。",
    "relationships": "你是角色关系分析师。只分析剧本中有实际互动的角色对。",
    "emotion": "你是情感曲线分析师。以主角视角为主，逐场判定情感值。",
    "pacing": "你是节奏分析师。判定锚点：连续≥3场无新信息或冲突推进=拖沓；关键转折缺少过渡=过快。",
    "logic": "你是逻辑审查员。只报告明显的问题；confidence<0.5 的条目不得标记为 high；完全无证据的问题不输出。",
    "structure": "你是结构分析师。三幕划分与节拍定位必须落到场次号；伏笔必须给出埋点场次与回收场次（回收场次 ≥ 埋点场次），未回收的伏笔 status 标 unresolved 且不填回收信息；找不到证据时输出空数组，禁止编造。",
    "commercial": "你是市场视角分析师。严禁编造任何市场数据、票房数据或虚构作品；对标作品仅为风格参考，标注\"仅供参考\"。",
    "final": "你是总审读。评分只代表模型参考意见；建议必须可执行，禁止\"重写全篇\"类空话。",
    "rewrite": "你是改写顾问。只做建议要求的最小改动：保持原场次头与对白格式、人物口吻；不新增人物、不改情节事实、不改场次号；original 必须逐字摘自落点场次原文；改写片段可直接替换使用。",
    "chat": "你是「剧本医生」，与编剧围绕刚体检完的剧本进行追问答疑。"
            "只依据提供的剧本文本与体检报告回答；引用原文必须逐字抄写并注明场次；"
            "剧本中没有的情节、台词、人物一律不得声称存在；拿不准就直说，不编造。",
}

# ---------------------------------------------------------------------------
# 用户提示词模板（10 模块）
# ---------------------------------------------------------------------------

USER_TEMPLATES = {
    "parse": """请解析以下剧本文本，输出 json 对象。

任务：
0. 剧本标题 title：取剧本首行书名号《》中的内容，若无则为空字符串
1. 场次表 scenes：按剧本原有场号切分，summary ≤30 字
2. 幕结构 acts（场次≥3 时划分）：n、name、scene_range（如"1-4"）
3. 角色名单 characters：name、aliases（剧本中出现的其他称呼）、role、first_scene

输出 json 结构：
{"title":"深夜便利店","scenes":[{"n":1,"title":"夜 便利店","summary":"..."}],
 "acts":[{"n":1,"name":"第一幕","scene_range":"1-4"}],
 "characters":[{"name":"李薇","aliases":[],"role":"protagonist","first_scene":1}]}

剧本：
\"""
{SCRIPT}
\""" """,

    "characters": """请输出角色维度的 json 分析。出场次数统计表（规则计算，请直接采用，不要重新计数）：
{STATS}

任务：
1. 每个角色的 function（叙事功能，≤30 字）与 analysis（塑造与作用，≤80 字，须附 evidence 引用）
2. distribution_issues：戏份失衡、功能角色冗余等分布问题，每条须带场次+引用

输出 json 结构：
{"cast":[{"name":"李薇","function":"主线人物","analysis":"...","evidence":{"scene":1,"text":"..."}}],
 "distribution_issues":["主角戏份占比过高（第2场：\"...\"）"]}

剧本：\"""
{SCRIPT}
\""" """,

    "relationships": """请输出角色关系的 json 分析。

任务：
1. 列出所有有实际互动的角色对（pair，两个规范名）
2. 每对关系给出：type（如"陌生—相识"）、trajectory（关系走向）、turning_points（关键转折，每点附引用）、issues（关系线的问题，可空字符串）

输出 json 结构：
{"relationships":[{"pair":["李薇","陈默"],"type":"陌生—相识","trajectory":"...",
  "turning_points":[{"scene":2,"text":"..."}],"issues":"..."}]}

剧本：\"""
{SCRIPT}
\""" """,

    "emotion": """请输出情感曲线的 json 分析。

任务：
1. 按角色拆多条曲线（最多 3 条）：
   - 主角必出；反派/主要对手有戏份时出第二条；可再选 1 个情感变化重要的重要配角
   - 每个点：scene、value（-2~+2 整数：-2 低谷 / -1 低落 / 0 中性 / +1 上扬 / +2 高涨）、character（角色规范名）、label（≤10 字）、evidence 引用（无明确证据时省略 evidence）
   - 每条曲线至少 2 个点；角色名必须使用角色名单中的规范名
2. summary：情感弧线小结（≤80 字）
3. flatness_issues：情感变化不足、情绪单调等问题（可为空数组）

输出 json 结构：
{"granularity":"scene","points":[{"scene":1,"value":-1,"character":"李薇","label":"疲惫低回","evidence":{"scene":1,"text":"..."}},
 {"scene":1,"value":0,"character":"陈默","label":"平静观望"}],
 "summary":"...","flatness_issues":[]}

剧本：\"""
{SCRIPT}
\""" """,

    "pacing": """请输出节奏分析的 json 分析。

任务：
1. per_act：每幕的 tension（0~10）、verdict（拖沓/正常/过快）、reason（≤60 字，附 evidence）
2. dragging_scenes / rushed_scenes：问题场次，value 为问题程度（0~10），可空数组
3. overall_verdict：总体节奏判定

输出 json 结构：
{"per_act":[{"act":1,"tension":4,"verdict":"拖沓","reason":"...","evidence":{"scene":1,"text":"..."}}],
 "dragging_scenes":[{"scene":1,"value":3,"label":"...","evidence":{"scene":1,"text":"..."}}],
 "rushed_scenes":[],"overall_verdict":"..."}

剧本：\"""
{SCRIPT}
\""" """,

    "logic": """请输出逻辑漏洞与动机问题的 json 分析。

任务：
1. 找出逻辑漏洞、动机问题、设定矛盾，逐条输出：
   - id：lh1、lh2…（顺序编号）
   - severity：high（影响叙事成立）/ medium（影响观感）/ low（细枝末节）
   - type：逻辑漏洞 / 动机问题 / 设定矛盾
   - description（≤60 字）、evidence_quotes（至少 1 条逐字引用）、confidence、basis（判断依据 ≤60 字）、suggestion_hint（修复方向 ≤40 字）
2. 规则：完全无证据的问题不输出；找不到就输出空数组

输出 json 结构：
{"holes":[{"id":"lh1","severity":"medium","type":"动机问题","description":"...",
  "evidence_quotes":[{"scene":4,"text":"..."}],"confidence":0.6,"basis":"...","suggestion_hint":"..."}]}

剧本：\"""
{SCRIPT}
\""" """,

    "structure": """请输出结构体检的 json 分析。

任务：
1. acts：三幕结构划分（剧本 ≥3 场时输出；每幕 act、name、scene_start/scene_end（含首尾场次）、summary ≤30 字）
2. beats：关键节拍定位（激励事件、第一幕结尾转折、中点、高潮、结局等）：name、scene（场次号）、description ≤40 字、evidence 引用（无明确证据时省略 evidence）
3. foreshadows：伏笔清单：
   - 每条：setup（埋点内容 ≤40 字）、setup_scene（埋点场次）
   - 已回收：payoff（回收内容 ≤40 字）、payoff_scene（必须 ≥ setup_scene）、status="resolved"
   - 埋而未收：status="unresolved"，不填 payoff / payoff_scene
4. arcs：主要人物弧光（主角必出，重要配角可选）：character（规范名）、start_state（起点状态 ≤20 字）、turning_event（转变事件 ≤30 字）、turning_scene、end_state（终点状态 ≤20 字）
5. 场次号只能使用场次表中的编号；找不到证据的条目输出空数组，严禁编造

输出 json 结构：
{"acts":[{"act":1,"name":"第一幕 相遇","scene_start":1,"scene_end":2,"summary":"..."}],
 "beats":[{"name":"激励事件","scene":1,"description":"...","evidence":{"scene":1,"text":"..."}}],
 "foreshadows":[{"setup":"...","setup_scene":1,"payoff":"...","payoff_scene":4,"status":"resolved"}],
 "arcs":[{"character":"李薇","start_state":"...","turning_event":"...","turning_scene":3,"end_state":"..."}]}

剧本：\"""
{SCRIPT}
\""" """,

    "commercial": """请输出商业潜力与类型元素的 json 分析。

任务：
1. genre_elements：类型元素（≤5 个）
2. target_audience：目标受众（≤30 字）
3. benchmarks：风格参考的对标作品（可为空数组；严禁编造数据，每条标注"仅供参考"）
4. strengths / risks：卖点与风险各 ≤4 条
5. confidence：整体判断置信度（0~1，无市场数据支撑时 ≤0.5）

输出 json 结构：
{"genre_elements":["都市情感","文艺短片"],"target_audience":"...","benchmarks":[],
 "strengths":["..."],"risks":["..."],"confidence":0.5}

剧本：\"""
{SCRIPT}
\""" """,

    "final": """请基于剧本与以下各维度分析结果，输出综合评分与修改建议的 json。

【各维度分析摘要（结构化数据，请直接引用其中的漏洞 ID 与场次号）】
{UPSTREAM}
{PREV_SUGGESTIONS}

任务：
1. score.overall（0-100 整数）与 6 个分项（character/emotion/pacing/logic/structure/commercial，0-100 整数）
2. suggestions 恰好 3 条（rank 1-3）：
   - problem：要解决的问题（≤40 字）
   - action.scene：落点场次；action.concrete：具体修改动作（≤60 字，可直接执行）
   - expected_effect（≤40 字）
   - references：关联的漏洞 ID 或场次号
   规则：只能引用 confidence≥0.5 的漏洞；建议必须落到具体场次+具体动作。

输出 json 结构：
{"score":{"overall":68,"dimensions":{"character":62,"emotion":75,"pacing":60,"logic":70,"structure":66,"commercial":55}},
 "suggestions":[{"rank":1,"problem":"...","action":{"scene":1,"concrete":"..."},"expected_effect":"...","references":["lh1"]}]}

剧本：\"""
{SCRIPT}
\""" """,

    "rewrite": """请针对以下修改建议，逐条输出可直接替换使用的改写示例。

【修改建议】
{SUGGESTIONS}

【落点场次原文】
{SCENE_TEXT}

任务：
1. 每条建议输出一个改写示例（rank 对应建议序号）：
   - original：从落点场次原文中逐字摘出的待修改片段（{scene, text}，text ≤60 字，必须逐字命中原文）
   - rewritten：改写后的剧本片段（保持场次头/对白格式与人物口吻，可直接替换使用）
   - note：改写理由 ≤40 字
2. 只做建议要求的最小改动：不新增人物、不改情节事实、不改场次号
3. 找不到可改动的原文时输出空数组，严禁编造

输出 json 结构：
{"rewrites":[{"rank":1,"original":{"scene":1,"text":"..."},"rewritten":"...","note":"..."}]}""",

    "chat": """请以剧本医生的身份回答编剧的追问，输出 json 对象。

【剧本（{CONTEXT_TYPE}）】
\"""
{SCRIPT_CONTEXT}
\"""

【本次体检报告摘要】
{REPORT_DIGEST}

【对话历史（最近若干轮，若无则为空）】
{HISTORY}

【本次提问】
{QUESTION}

输出 json 结构：
{"answer":"回答正文（markdown，≤300 字，可直接给编剧看）",
 "evidence_quotes":[{"scene":1,"text":"逐字引用 ≤40 字"}],
 "confidence":0.7}

要求：
1. answer 必须基于上述剧本与报告回答；涉及具体情节时给出 evidence_quotes（逐字抄自剧本，去空白后必须与原文一致）
2. 与剧本无关或信息不足的问题：明确说明"剧本中无相关信息"，confidence 降为 0.3，不编造引用
3. 引用只能取自上述剧本上下文中的原文；场次号必须存在"""
}

# 长剧本（分块模式）最终合并模板：不传全文，只传各块汇总
MERGE_TEMPLATE = """以下是长剧本分块分析的各模块汇总结果（每块已独立分析完成）：
{UPSTREAM}
{PREV_SUGGESTIONS}

请基于上述汇总，输出综合评分与修改建议的 json。
任务：
1. score.overall（0-100 整数）与 6 个分项（character/emotion/pacing/logic/structure/commercial，0-100 整数）
2. suggestions 恰好 3 条（rank 1-3）：
   - problem（≤40 字）
   - action.scene：落点场次；action.concrete：具体修改动作（≤60 字）
   - expected_effect（≤40 字）
   - references：关联的漏洞 ID 或场次号
   规则：只能引用 confidence≥0.5 的漏洞；建议必须落到具体场次+具体动作。

输出 json 结构：
{"score":{"overall":68,"dimensions":{"character":62,"emotion":75,"pacing":60,"logic":70,"structure":66,"commercial":55}},
 "suggestions":[{"rank":1,"problem":"...","action":{"scene":1,"concrete":"..."},"expected_effect":"...","references":["lh1"]}]}

注意：此为分块模式，长线跨块逻辑检测能力有限。"""
