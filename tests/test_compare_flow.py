"""改稿前后对比回归测试：漏洞对齐规则 → 建议注入管线 → 对比页界面流程。

运行：py tests/test_compare_flow.py（在 script-doctor 目录下）
使用临时数据库，不污染真实 users.db；分析管线打桩，不调用 API，可反复运行。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth  # noqa: E402
import history  # noqa: E402
import analyzer  # noqa: E402
import compare  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

_TMP = os.path.join(tempfile.mkdtemp(), "users.db")
auth.DB_PATH = _TMP
history.DB_PATH = _TMP
auth.init_db()
history.init_db()
os.environ["DEEPSEEK_API_KEY"] = "sk-test"  # 仅用于构造客户端，不发网络请求
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
failures = []


def check(cond, msg):
    print(("PASS" if cond else "FAIL") + ": " + msg)
    if not cond:
        failures.append(msg)


# ---- 0. compare.match_holes 规则单元测试 ----
H1 = [
    {"id": "lh1", "severity": "high", "type": "逻辑漏洞", "description": "时间线矛盾",
     "evidence_quotes": [{"scene": 1, "text": "昨天 他 说 没 见过 她"}], "confidence": 0.9, "basis": ""},
    {"id": "lh2", "severity": "medium", "type": "动机问题", "description": "动机不足",
     "evidence_quotes": [{"scene": 3, "text": "突然 决定 离开"}], "confidence": 0.7, "basis": ""},
    {"id": "lh3", "severity": "low", "type": "设定矛盾", "description": "无引用漏洞",
     "evidence_quotes": [], "confidence": 0.5, "basis": ""},
]
H2 = [
    {"id": "lh2", "severity": "medium", "type": "动机问题", "description": "动机不足（编号变了但引用相同）",
     "evidence_quotes": [{"scene": 3, "text": "突然 决定 离开"}], "confidence": 0.7, "basis": ""},
    {"id": "lh4", "severity": "medium", "type": "逻辑漏洞", "description": "新增漏洞",
     "evidence_quotes": [{"scene": 5, "text": "新 台词"}], "confidence": 0.6, "basis": ""},
]
r = compare.match_holes(H1, H2)
check([p["status"] for p in r["pairs"]] == ["gone", "open", "unknown"], "漏洞状态：疑似修复/仍存在/无法判定")
check(r["pairs"][1]["v2"]["id"] == "lh2", "共享引用跨 id 编号对齐")
check(len(r["new_in_v2"]) == 1 and r["new_in_v2"][0]["id"] == "lh4", "v2 新增漏洞识别")
r2 = compare.match_holes([], H2)
check(len(r2["pairs"]) == 0 and len(r2["new_in_v2"]) == 2, "空 v1：全部视为新增")

# ---- 1. analyzer 注入管线单元测试（fake client）----
PARSE = {"title": "测试剧本", "scenes": [{"n": 1, "title": "第1场", "summary": "x"}],
         "acts": [], "characters": []}
FINAL_DATA = {
    "score": {"overall": 70, "dimensions": {"character": 70, "emotion": 70, "pacing": 70, "logic": 70, "commercial": 70}},
    "suggestions": [{"rank": 1, "problem": "p", "action": {"scene": 1, "concrete": "c"}, "expected_effect": "e"}],
    "prev_suggestions_review": [{"rank": 1, "adopted": True, "note": "已改"}],
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
        elif "市场视角" in system:
            data = {"genre_elements": [], "target_audience": "", "benchmarks": [],
                    "strengths": [], "risks": [], "confidence": 0.5}
        elif "总审读" in system:
            if "上一版" in user:
                data = FINAL_DATA
            else:
                data = {k: v for k, v in FINAL_DATA.items() if k != "prev_suggestions_review"}
        return {"data": data, "elapsed": 0.1,
                "usage": {"input_tokens": 10, "cache_hit_tokens": 0, "output_tokens": 10}}

    @staticmethod
    def estimate_cost(u):
        return 0.0


SCRIPT = "第1场 测试\n你好。"

c1 = FakeClient()
rep, warns = analyzer.run_pipeline(
    SCRIPT, c1,
    prev_suggestions=[{"rank": 1, "problem": "改戏", "action": {"scene": 1, "concrete": "改成哭"}}],
)
final_call = c1.calls[-1]["user"]
check("上一版" in final_call and "改戏" in final_call, "prev 建议注入 final prompt")
check(rep["prev_suggestions_review"] == [{"rank": 1, "adopted": True, "note": "已改"}], "review 挂进报告")
check(not any("整体校验未通过" in str(w) for w in warns), "报告整体 schema 校验通过")

c2 = FakeClient()
rep2, _ = analyzer.run_pipeline(SCRIPT, c2, prev_suggestions=None)
check("上一版" not in c2.calls[-1]["user"], "无 prev 时不注入")
check(rep2["prev_suggestions_review"] == [], "无 prev 时 review 为空")
check(rep["emotion_curve"]["points"][0].get("character") == "甲",
      "schema 校验接受带 character 的情感点")
check("hard_checks" in rep and rep["hard_checks"].get("skipped") is True,
      "管线附带本地硬检查（短样本 → 跳过判定）")

# ---- 1.5 分块合并：情感曲线按 (角色, 场次) 去重 ----
merged = analyzer._merge_module("emotion", [
    {"granularity": "scene", "points": [
        {"scene": 1, "value": 0, "character": "甲"},
        {"scene": 1, "value": -1, "character": "乙"},
    ], "summary": "s1", "flatness_issues": []},
    {"granularity": "scene", "points": [
        {"scene": 1, "value": 1, "character": "甲"},  # 同角色同场 → 丢弃
        {"scene": 2, "value": 1, "character": "甲"},
    ], "summary": "s2", "flatness_issues": ["i"]},
])
mpts = merged["points"]
check([(p["character"], p["scene"]) for p in mpts] == [("甲", 1), ("乙", 1), ("甲", 2)],
      "合并：同角色同场去重、跨角色同场保留")
check(merged["flatness_issues"] == ["i"], "合并：flatness_issues 拼接")

# ---- 2. AppTest 界面流程 ----
auth.register("对比用户", "abc12345")
uid = auth.get_user_id("对比用户")

V1 = {
    "script_meta": {"title": "对比剧本v1", "word_count": 100, "scene_count": 2, "acts": []},
    "score": {"overall": 60, "dimensions": {"character": 55, "emotion": 60, "pacing": 50, "logic": 40, "commercial": 65}},
    "logic": {"holes": [
        {"id": "lh1", "severity": "high", "type": "逻辑漏洞", "description": "时间线矛盾",
         "evidence_quotes": [{"scene": 1, "text": "他昨天说过没见过她"}], "confidence": 0.9, "basis": "b"},
        {"id": "lh2", "severity": "low", "type": "设定矛盾", "description": "无引用漏洞",
         "evidence_quotes": [], "confidence": 0.5, "basis": "b"},
    ]},
    "suggestions": [
        {"rank": 1, "problem": "修补时间线", "action": {"scene": 1, "concrete": "删掉矛盾台词"},
         "expected_effect": "e", "references": ["lh1"]},
    ],
}
V2 = {
    "script_meta": {"title": "对比剧本v2", "word_count": 110, "scene_count": 2, "acts": []},
    "score": {"overall": 80, "dimensions": {"character": 70, "emotion": 75, "pacing": 72, "logic": 78, "commercial": 68}},
    "logic": {"holes": [
        {"id": "lh9", "severity": "medium", "type": "动机问题", "description": "新增漏洞",
         "evidence_quotes": [{"scene": 2, "text": "新的矛盾台词"}], "confidence": 0.6, "basis": "b"},
    ]},
    "suggestions": [],
    "prev_suggestions_review": [
        {"rank": 1, "adopted": True, "note": "台词已删", "evidence": {"scene": 1, "text": "新的台词"}},
    ],
}
rid1 = history.save_report(uid, script_excerpt="v1", report=V1)
rid2 = history.save_report(uid, script_excerpt="v2", report=V2)

# 打桩：分析管线换成假实现（记录收到的 prev_suggestions）
FAKE_LOGS = {"prev_suggestions": None}
FAKE_REPORT = {
    "script_meta": {"title": "对比剧本v2", "word_count": 110, "scene_count": 2, "acts": []},
    "score": {"overall": 80, "dimensions": {"character": 70, "emotion": 75, "pacing": 72, "logic": 78, "commercial": 68}},
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


def fake_pipeline(text, client, progress_cb=None, prev_suggestions=None, modules=None):
    FAKE_LOGS["modules"] = modules
    FAKE_LOGS["prev_suggestions"] = prev_suggestions
    if progress_cb:
        progress_cb(1.0, "完成")
    return FAKE_REPORT, []


analyzer.run_pipeline = fake_pipeline

at = AppTest.from_file(APP, default_timeout=60)
at.run()
check(not at.exception, "首次加载无异常（auth 页）")

# 2a. 登录 → 历史页 → 选择 v1/v2 → 对比页
at.text_input(key="login_username").set_value("对比用户")
at.text_input(key="login_password").set_value("abc12345")
at.button(key="btn_login").click().run()
at.button(key="btn_history").click().run()
at.selectbox(key="cmp_a").select(rid1)
at.selectbox(key="cmp_b").select(rid2)
at.run()
at.button(key="btn_compare").click().run()
check(not at.exception, "对比页渲染无异常")
check(at.session_state["stage"] == "compare", "进入 compare 页")
check(any(m.value == "60/100" for m in at.metric) and any(m.value == "80/100" for m in at.metric),
      "v1/v2 总分显示")
check(any("+20" in (m.value or "") for m in at.metric), "总分变化 +20 显示")
subs = [s.value for s in at.subheader]
check("5 维评分对比" in subs and "漏洞对照" in subs and "v1 建议采纳情况" in subs, "三块内容齐全")
md = [m.value for m in at.markdown]
check(any("已落实" in x for x in md), "建议采纳：已落实")
check(any("v2 新增 1 个漏洞" in x for x in md), "v2 新增漏洞提示")
statuses = [str(v) for v in at.dataframe[0].value["状态"]]
check(any(s.startswith("未检出") for s in statuses), "漏洞状态：疑似已修复")
check(any(s.startswith("无法判定") for s in statuses), "漏洞状态：无法判定")

# 2b. 返回历史 → 选同一条记录 → 报错
at.button(key="btn_cmp_back").click().run()
check(at.session_state["stage"] == "history", "「返回历史」回到 history 页")
at.selectbox(key="cmp_a").select(rid1)
at.selectbox(key="cmp_b").select(rid1)
at.run()
at.button(key="btn_compare").click().run()
check(at.session_state["stage"] == "history", "选择相同记录停留 history 页")
check(any("请选择两条不同的记录" in e.value for e in at.error), "显示「请选择两条不同的记录」")

# 2c. 上传页：上一版选择器 + 分析时注入
at.button(key="btn_hist_back").click().run()
check(at.session_state["stage"] == "upload", "回到 upload 页")
check(len(at.selectbox(key="prev_version_sel").options) == 3, "上一版选择器含 0+2 条记录")
at.selectbox(key="prev_version_sel").select(rid1)
at.text_area(key="paste_area").set_value("第1场 改稿后的内容")
at.run()
at.button(key="btn_paste").click().run()
check(at.session_state["stage"] == "report", "分析（打桩）完成进入 report 页")
check(at.session_state["prev_report_id"] == rid1, "prev_report_id 已设置")
check(FAKE_LOGS["prev_suggestions"] == V1["suggestions"], "管线收到上一版建议")
check(FAKE_LOGS.get("modules") == list(analyzer.MODULES_R2), "管线收到模块勾选（默认全选）")

# 2d. 游客无上一版选择器
at.button(key="btn_logout").click().run()
at.button(key="btn_guest").click().run()
check(all(b.key != "prev_version_sel" for b in at.selectbox), "游客不显示上一版选择器")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
