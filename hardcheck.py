"""规则类硬检查：对白占比、每场字数、场次分布、页数↔时长换算（本地计算，不调 LLM）。

输入原始剧本文本，输出 report["hard_checks"]。全部为确定性规则：
- 场次切分复用 analyzer.split_scenes（与报告 scene_count 同一口径）
- 对白识别：「角色名：」开头的行（全角/半角冒号，名前缀 ≤8 字），括注动作的整体计入
- 全文 < MIN_SCRIPT_CHARS 字（迷你剧本/大纲）→ 只出统计，异常判定降级为「样本过短」
"""
import re
import statistics

import analyzer  # 复用场次切分，避免与报告 scene_count 口径不一致

# ---- 阈值常量（行业惯例默认值，可调）----
PAGE_CHARS = 600              # 每页字数基准（1 页 ≈ 1 分钟）
DIALOGUE_HIGH = 0.65          # 对白占比 ≥ 此值 → 偏高
DIALOGUE_LOW = 0.25           # 对白占比 ≤ 此值 → 偏低
SCENE_TOO_LONG_CHARS = 1800   # 单场 > 此字数（≈3 分钟）→ 过长
SCENE_TOO_SHORT_CHARS = 150   # 单场 ≤ 此字数 → 过短
MIN_SCRIPT_CHARS = 5000       # 全文 < 此字数 → 跳过异常判定（只出统计）
MIN_PER_SCENE_MIN = 1 / 3     # 平均每场 < 20 秒 → 碎片化
MAX_PER_SCENE_MIN = 8.0       # 平均每场 > 8 分钟 → 单场拖沓

SKIP_VERDICT = "样本过短，跳过判定（全文不足 5000 字）"

_DIALOGUE_RE = re.compile(r"^\s*[^：:，。、！？…\s]{1,8}[：:]\s*")


def _nonspace(text: str) -> str:
    return re.sub(r"\s+", "", text)


def count_dialogue(text: str) -> dict:
    """统计对白行数/字数：「角色名：」开头（全角/半角冒号）的行整体计入。"""
    lines = chars = 0
    for line in text.splitlines():
        if _DIALOGUE_RE.match(line):
            lines += 1
            chars += len(_nonspace(line))
    return {"lines": lines, "chars": chars}


def run_hard_checks(text: str, scenes: list | None = None) -> dict:
    """规则硬检查，返回 report["hard_checks"]。scenes 可复用调用方已切好的场次。"""
    text = text or ""
    total = len(_nonspace(text))
    dia = count_dialogue(text)
    if scenes is None:
        scenes = analyzer.split_scenes(text)
    lengths = [len(_nonspace(s.get("content", ""))) for s in scenes]
    ratio = (dia["chars"] / total) if total else 0.0
    pages = round(total / PAGE_CHARS, 1) if total else 0.0
    skipped = total < MIN_SCRIPT_CHARS

    if skipped:
        dia_verdict = scene_verdict = SKIP_VERDICT
        too_long = []
        too_short = []
    else:
        if ratio >= DIALOGUE_HIGH:
            dia_verdict = "偏高：对白占比过大，视觉叙事空间不足"
        elif ratio <= DIALOGUE_LOW:
            dia_verdict = "偏低：对白过少，检查是否动作描写过载"
        else:
            dia_verdict = "正常"
        too_long = [{"scene": i + 1, "chars": ch, "minutes": round(ch / PAGE_CHARS, 1)}
                    for i, ch in enumerate(lengths) if ch > SCENE_TOO_LONG_CHARS]
        too_short = [{"scene": i + 1, "chars": ch}
                     for i, ch in enumerate(lengths) if ch <= SCENE_TOO_SHORT_CHARS]
        avg_min = (pages / len(scenes)) if scenes else 0.0
        if avg_min < MIN_PER_SCENE_MIN:
            scene_verdict = "碎片化：平均每场不足 20 秒，场景切换过频"
        elif avg_min > MAX_PER_SCENE_MIN:
            scene_verdict = "单场拖沓：平均每场超过 8 分钟"
        else:
            scene_verdict = "正常"

    def _extreme(want_max: bool) -> dict:
        if not lengths:
            return {}
        idx = (max if want_max else min)(range(len(lengths)), key=lambda i: lengths[i])
        return {"scene": idx + 1, "chars": lengths[idx]}

    return {
        "dialogue": {
            "ratio": round(ratio, 3),
            "chars": dia["chars"],
            "lines": dia["lines"],
            "verdict": dia_verdict,
        },
        "scenes": {
            "count": len(scenes),
            "lengths": lengths,
            "avg": round(statistics.mean(lengths), 1) if lengths else 0.0,
            "median": round(statistics.median(lengths), 1) if lengths else 0.0,
            "longest": _extreme(True),
            "shortest": _extreme(False),
            "too_long": too_long,
            "too_short": too_short,
            "verdict": scene_verdict,
        },
        "page_time": {
            "page_chars": PAGE_CHARS,
            "chars": total,
            "pages": pages,
            "minutes": pages,  # 1 页 ≈ 1 分钟
        },
        "skipped": skipped,
    }
