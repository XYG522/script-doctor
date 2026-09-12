"""改稿前后对比 —— 漏洞对齐（纯规则，不调 LLM）。

对齐依据：漏洞的逐字引用（evidence_quotes）是报告里唯一经过硬校验、与原文一一对应的数据。
规则：
- v1 漏洞与 v2 漏洞共享 ≥1 条相同引用（去空白后逐字比较）→ 同一漏洞，仍存在（open）
- v1 有引用但 v2 无同引用 → 未检出（gone）。改稿修复漏洞必然改动对应文本，
  原引用在 v2 中不存在（会被防幻觉硬校验剔除），所以这是「疑似已修复」的规则信号；
  但模型漏检也会表现为消失，UI 必须如实措辞。
- v1 漏洞无可用引用 → 无法判定（unknown）
- v2 中未被匹配的漏洞 → 新增（new_in_v2）
"""
import re


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def hole_quotes(hole: dict) -> set:
    """漏洞的引用集合（去空白）。"""
    return {
        _norm(q.get("text"))
        for q in (hole.get("evidence_quotes") or [])
        if _norm(q.get("text"))
    }


def match_holes(v1_holes: list, v2_holes: list) -> dict:
    """对齐两份报告的漏洞列表。

    返回 {"pairs": [...], "new_in_v2": [...]}
    pairs 每项：{"v1": hole, "v2": hole|None, "status": "open"|"gone"|"unknown"}
    """
    v2_used = set()
    pairs = []
    for h1 in v1_holes:
        q1 = hole_quotes(h1)
        if not q1:
            pairs.append({"v1": h1, "v2": None, "status": "unknown"})
            continue
        match_idx = None
        for i, h2 in enumerate(v2_holes):
            if i in v2_used:
                continue
            if q1 & hole_quotes(h2):
                match_idx = i
                break
        if match_idx is None:
            pairs.append({"v1": h1, "v2": None, "status": "gone"})
        else:
            v2_used.add(match_idx)
            pairs.append({"v1": h1, "v2": v2_holes[match_idx], "status": "open"})
    new_in_v2 = [h for i, h in enumerate(v2_holes) if i not in v2_used]
    return {"pairs": pairs, "new_in_v2": new_in_v2}
