"""模块勾选 + 成本预估回归测试：estimate_run_cost 单元 → 管线 modules 参数 → 界面勾选流程。

运行：py tests/test_modules_cost.py（在 script-doctor 目录下）
使用临时数据库，不污染真实 users.db；分析管线打桩，不调用 API，可反复运行。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth  # noqa: E402
import history  # noqa: E402
import analyzer  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

_TMP = os.path.join(tempfile.mkdtemp(), "users.db")
auth.DB_PATH = _TMP
history.DB_PATH = _TMP
auth.init_db()
history.init_db()
os.environ["DEEPSEEK_API_KEY"] = "sk-test"  # 仅用于构造客户端，不发网络请求
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
failures = []

ALL = list(analyzer.MODULES_R2)


def check(cond, msg):
    print(("PASS" if cond else "FAIL") + ": " + msg)
    if not cond:
        failures.append(msg)


def chart_contains(els, needle):
    """AppTest 的 plotly 元素：spec 是 JSON 字符串（中文被 \\u 转义），解码后全文搜索。"""
    for el in els:
        try:
            if needle in json.dumps(json.loads(el.proto.spec), ensure_ascii=False):
                return True
        except Exception:
            continue
    return False


# ---- 0. estimate_run_cost 单元测试 ----
TEXT_1000 = "动" * 1000

est_all = analyzer.estimate_run_cost(TEXT_1000, ALL)
check(est_all["calls"] == 10, "7 模块非分块：parse + 7 模块 + final + 改写 = 10 次调用")
check(est_all["input_tokens"] == 9 * (1000 + 600) + 1500 + 1500,
      "输入 token：9×(1000+600)+1500(上游)+1500(改写)=17400")
check(est_all["output_tokens"] == int((600 + 3800 + 800 + 900) * 1.2),
      "输出 token：(600+3800+800+900)×1.2=7320")
check(est_all["est_cost_usd"] == 0.026, "预估成本 17400/7320 → $0.026（闲时价）")

est_one = analyzer.estimate_run_cost(TEXT_1000, ["emotion"])
check(est_one["calls"] == 4 and est_one["input_tokens"] == 3 * 1600 + 1500 + 1500
      and est_one["output_tokens"] == int((600 + 600 + 800 + 900) * 1.2)
      and est_one["est_cost_usd"] == 0.012,
      "单模块：4 次调用（含改写），成本 $0.012")
check(est_one["est_cost_usd"] < est_all["est_cost_usd"], "勾选越少成本越低（单调）")

check(analyzer.estimate_run_cost(TEXT_1000, ["emotion", "bogus"]) == est_one,
      "非法模块名被过滤，不影响估算")
check(analyzer.estimate_run_cost(TEXT_1000, []) ==
      {"calls": 0, "input_tokens": 0, "output_tokens": 0, "est_cost_usd": 0.0},
      "0 模块 → 全零（纯免费硬检查）")
check(analyzer.estimate_run_cost("", ALL)["calls"] == 10, "空文本不崩溃（按 0 字估算）")

# 分块：25 场 × 910 字 = 22750 字 > 2 万 → 3 块
CHUNK_TEXT = "".join(f"第{i:02d}场 地点X\n" + "动" * 900 + "\n" for i in range(1, 26))
est_chunk = analyzer.estimate_run_cost(CHUNK_TEXT, ALL)
check(est_chunk["calls"] == 1 + 7 * 3 + 1 + 1, "分块模式：1 + 7 模块 × 3 块 + final + 改写 = 24 次调用")
check(est_chunk["input_tokens"] == int(1500 + 7 * 3 * (len(CHUNK_TEXT) / 3 + 600) + 1500 + 1500),
      "分块输入：概览 + 7×3 块×(22750/3+600) + 上游 + 改写")
check(est_chunk["output_tokens"] == int((600 + 3800 * 3 + 800 + 900) * 1.2), "分块输出 ×3 块（含改写）")
check(est_chunk["est_cost_usd"] == 0.1489, "分块预估成本 $0.1489")

# ---- 1. run_pipeline modules 参数（fake client）----
PARSE = {"title": "模块测试剧本", "scenes": [{"n": 1, "title": "第1场", "summary": "x"}],
         "acts": [], "characters": []}
FINAL_DATA = {
    "score": {"overall": 70, "dimensions": {"character": 70, "emotion": 70, "pacing": 70,
                                            "logic": 70, "structure": 70, "commercial": 70}},
    "suggestions": [{"rank": 1, "problem": "开场单薄", "action": {"scene": 1, "concrete": "补一句对白"},
                     "expected_effect": "人物立起来", "references": []}],
    "prev_suggestions_review": [],
}


class FakeClient:
    model = "fake"

    def __init__(self):
        self.calls = []

    def complete(self, system, user):
        self.calls.append({"system": system, "user": user})
        data = None
        if "结构解析器" in system:
            data = PARSE
        elif "角色维度" in system:
            data = {"cast": [], "distribution_issues": []}
        elif "角色关系" in system:
            data = {"relationships": []}
        elif "情感曲线" in system:
            data = {"granularity": "scene",
                    "points": [{"scene": 1, "value": 1, "character": "甲", "label": "平稳"}],
                    "summary": "", "flatness_issues": []}
        elif "节奏分析师" in system:
            data = {"per_act": [], "overall_verdict": "", "dragging_scenes": [], "rushed_scenes": []}
        elif "逻辑审查员" in system:
            data = {"holes": []}
        elif "结构分析师" in system:
            data = {"acts": [], "beats": [], "foreshadows": [], "arcs": []}
        elif "改写顾问" in system:
            data = {"rewrites": [{"rank": 1, "original": {"scene": 1, "text": "你好"},
                                  "rewritten": "改写文本", "note": "最小改动"}]}
        elif "市场视角" in system:
            data = {"genre_elements": [], "target_audience": "", "benchmarks": [],
                    "strengths": [], "risks": [], "confidence": 0.5}
        elif "总审读" in system:
            data = FINAL_DATA
        return {"data": data, "elapsed": 0.1,
                "usage": {"input_tokens": 10, "cache_hit_tokens": 0, "output_tokens": 10}}

    @staticmethod
    def estimate_cost(u):
        return 0.0


SCRIPT = "第1场 测试\n你好。"

c1 = FakeClient()
rep1, _ = analyzer.run_pipeline(SCRIPT, c1, modules=["emotion"])
check(len(c1.calls) == 4, "只勾情感曲线：4 次 LLM 调用（含改写示例）")
check("结构解析器" in c1.calls[0]["system"] and "总审读" in c1.calls[-2]["system"]
      and "改写顾问" in c1.calls[-1]["system"]
      and any("情感曲线" in x["system"] for x in c1.calls),
      "调用序列：结构解析器 → 情感曲线 → 总审读 → 改写顾问")
check(rep1["meta"]["modules_selected"] == ["emotion"], "报告 meta 记录 modules_selected")
check(rep1["score"]["dimensions"] == {"emotion": 70}, "未勾模块的评分维度被剔除")
check(rep1["meta"]["est_run"]["calls"] == 4, "报告 meta 附预估 4 次调用")
check(rep1["characters"]["cast"] == [], "未分析模块落到空默认结构（渲染不崩）")
check("hard_checks" in rep1, "硬检查仍随报告附带")
check(rep1["rewrites"][0]["rewritten"] == "改写文本", "改写示例进入报告")

c2 = FakeClient()
rep2, _ = analyzer.run_pipeline(SCRIPT, c2, modules=["relationships"])
check(rep2["score"]["dimensions"] == {}, "角色关系无评分维度 → dimensions 为空")

c3 = FakeClient()
rep3, _ = analyzer.run_pipeline(SCRIPT, c3, modules=["emotion", "bogus", ""])
check(len(c3.calls) == 4 and rep3["meta"]["modules_selected"] == ["emotion"],
      "非法模块名被过滤（同单模块行为）")

c4 = FakeClient()
rep4, warns4 = analyzer.run_pipeline("《深夜便利店》\n\n第一场 夜 地点\n甲：你好。", c4, modules=[])
check(c4.calls == [], "0 模块：不发起任何 LLM 调用")
check("score" not in rep4, "0 模块报告不含 score")
check(rep4["hard_checks"]["skipped"] is True, "0 模块报告仍附本地硬检查（短样本跳过）")
check(rep4["script_meta"]["title"] == "深夜便利店", "0 模块标题取首行并去《》")
check(rep4["script_meta"]["scene_count"] == 1, "0 模块场数统计正确")
check(rep4["meta"]["modules_selected"] == [] and rep4["meta"]["est_cost_usd"] == 0.0
      and rep4["meta"]["est_run"]["calls"] == 0, "0 模块 meta：modules_selected=[]、成本 0")
check(warns4 == [], "0 模块无警告")

c5 = FakeClient()
rep5, _ = analyzer.run_pipeline(SCRIPT, c5)  # modules=None → 全选（老调用兼容）
check(len(c5.calls) == 10, "modules=None → 全选 10 次调用")
check(rep5["meta"]["modules_selected"] == ALL, "modules=None → modules_selected 记录全选")
check(set(rep5["score"]["dimensions"]) == {"character", "emotion", "pacing", "logic",
                                           "structure", "commercial"},
      "全选时 6 维评分齐全")

# ---- 2. AppTest 界面流程 ----
FAKE_LOGS = {"modules": None}
FAKE_REPORT = {
    "script_meta": {"title": "模块测试剧本", "word_count": 100, "scene_count": 1, "acts": []},
    "score": {"overall": 77, "dimensions": {"character": 70, "emotion": 70, "pacing": 70,
                                            "logic": 70, "structure": 70, "commercial": 70}},
    "characters": {"cast": [], "distribution_issues": []},
    "relationships": [],
    "emotion_curve": {"points": [], "summary": "", "flatness_issues": []},
    "pacing": {"per_act": [], "overall_verdict": "", "dragging_scenes": [], "rushed_scenes": []},
    "logic": {"holes": []},
    "commercial": {"genre_elements": [], "target_audience": "", "benchmarks": [],
                   "strengths": [], "risks": [], "confidence": 0.5},
    "suggestions": [],
    "meta": {"model": "fake", "generated_at": "", "is_cached_demo": False, "chunked": False,
             "tokens": {}, "est_cost_usd": 0.0, "timings": {}, "total_elapsed_sec": 0.0},
}
FREE_REPORT = {
    "script_meta": {"title": "免费检查剧本", "word_count": 200, "scene_count": 1, "acts": []},
    "suggestions": [],
    "prev_suggestions_review": [],
    "hard_checks": {
        "dialogue": {"ratio": 0.0, "chars": 0, "lines": 0, "verdict": "样本过短，跳过判定（全文不足 5000 字）"},
        "scenes": {"count": 1, "lengths": [200], "avg": 200.0, "median": 200.0,
                   "longest": {"scene": 1, "chars": 200}, "shortest": {"scene": 1, "chars": 200},
                   "too_long": [], "too_short": [],
                   "verdict": "样本过短，跳过判定（全文不足 5000 字）"},
        "page_time": {"page_chars": 600, "chars": 200, "pages": 0.3, "minutes": 0.3},
        "skipped": True,
    },
    "meta": {"model": "fake", "generated_at": "", "is_cached_demo": False, "chunked": False,
             "modules_selected": [], "tokens": {}, "est_cost_usd": 0.0,
             "timings": {}, "total_elapsed_sec": 0.0},
}


def fake_pipeline(text, client, progress_cb=None, prev_suggestions=None, modules=None):
    FAKE_LOGS["modules"] = modules
    if progress_cb:
        progress_cb(1.0, "完成")
    if not modules:
        return FREE_REPORT, []
    rep = json.loads(json.dumps(FAKE_REPORT))
    rep["meta"]["modules_selected"] = list(modules)
    sel = {analyzer.MODULE_DIM[m] for m in modules if m in analyzer.MODULE_DIM}
    if sel != set(analyzer.MODULE_DIM.values()):
        rep["score"]["dimensions"] = {k: v for k, v in rep["score"]["dimensions"].items()
                                      if k in sel}
    rep["meta"]["est_run"] = analyzer.estimate_run_cost(text, modules)
    return rep, []


analyzer.run_pipeline = fake_pipeline

auth.register("模块用户", "abc12345")
at = AppTest.from_file(APP, default_timeout=60)
at.run()
check(not at.exception, "首次加载无异常（auth 页）")
at.text_input(key="login_username").set_value("模块用户")
at.text_input(key="login_password").set_value("abc12345")
at.button(key="btn_login").click().run()

mod_boxes = [b for b in at.checkbox if b.key and b.key.startswith("mod_")]
check(len(mod_boxes) == 7 and all(b.value for b in mod_boxes), "上传页 7 个模块勾选框且默认全选")

at.text_area(key="paste_area").set_value("第1场 模块测试")
at.run()
caps = [c.value for c in at.caption]
check(any("预估成本" in c and "10 次调用" in c for c in caps), "全选时预估 10 次调用")

for m in ALL:
    if m != "emotion":
        at.checkbox(key=f"mod_{m}").set_value(False)
at.run()
check(at.session_state["modules"] == ["emotion"], "取消勾选后 session_state 只剩 emotion")
check(any("4 次调用" in c.value for c in at.caption), "只勾情感曲线时预估 4 次调用")

at.button(key="btn_paste").click().run()
check(not at.exception, "模块分析（打桩）无异常")
check(at.session_state["stage"] == "report", "进入 report 页")
check(FAKE_LOGS["modules"] == ["emotion"], "管线收到勾选后的模块列表")
check(any("本次未分析该模块" in c.value for c in at.caption), "未勾选模块显示「本次未分析该模块」")
check(any(m.value == "77/100" for m in at.metric), "综合评分正常显示")
check(any(m.label == "情感" and m.value == "70" for m in at.metric), "已勾选模块的维度有分")
check(any(m.label == "角色" and m.value == "—" for m in at.metric), "未勾选模块的维度显示「—」")
plots = at.get("plotly_chart")
check(chart_contains(plots, "1 维评分") and not chart_contains(plots, "6 维评分"),
      "雷达图只画已勾选维度（1 维评分）")

# 全取消 → 免费硬检查报告
next(b for b in at.button if "重新分析" in b.label).click().run()
for m in ALL:
    at.checkbox(key=f"mod_{m}").set_value(False)
at.run()
check(at.session_state["modules"] == [], "全部取消勾选后 modules 为空")
at.text_area(key="paste_area").set_value("第1场 免费测试")
at.run()
check(any("0 次调用" in c.value and "仅运行免费硬检查" in c.value for c in at.caption),
      "0 模块时上传页提示「仅运行免费硬检查」")
at.button(key="btn_paste").click().run()
check(not at.exception, "0 模块报告渲染无异常")
check(at.session_state["stage"] == "report", "0 模块仍进入 report 页")
check(FAKE_LOGS["modules"] == [], "管线收到空模块列表（免费路径）")
check(any(m.value == "—" for m in at.metric), "无评分时综合评分显示「—」")
check(any("本次未分析该模块" in c.value for c in at.caption), "0 模块时所有 AI 模块均标注未分析")

# 免费报告入库后历史页不崩
at.button(key="btn_history").click().run()
check(not at.exception, "免费报告保存后历史页渲染无异常")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
