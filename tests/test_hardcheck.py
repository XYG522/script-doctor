"""规则硬检查回归测试：对白识别/场次统计/页数换算单元测试 → 报告页与离线演示渲染。

运行：py tests/test_hardcheck.py（在 script-doctor 目录下）
使用临时数据库，不污染真实 users.db；分析管线打桩，不调用 API，可反复运行。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth  # noqa: E402
import hardcheck  # noqa: E402
import history  # noqa: E402
import charts  # noqa: E402

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


def chart_contains(els, needle):
    """AppTest 的 plotly 元素：spec 是 JSON 字符串（中文被 \\u 转义），解码后全文搜索。"""
    for el in els:
        try:
            if needle in json.dumps(json.loads(el.proto.spec), ensure_ascii=False):
                return True
        except Exception:
            continue
    return False


# ---- 0. 对白识别单元测试 ----
DIA = (
    "李薇：你好。\n"                       # 全角冒号 ✓
    "陈默: 晚上好。\n"                      # 半角冒号 ✓
    "陈默：（沉默片刻）家没人。\n"            # 括注动作整体计入 ✓
    "李薇站在收银台后打哈欠。\n"              # 动作行 ✗
    "这是一段超过八个字的叙述：不是对白。\n"   # 前缀 >8 字 ✗
)
d = hardcheck.count_dialogue(DIA)
check(d["lines"] == 3, "对白识别：全角/半角冒号 + 括注动作 = 3 行")
check(d["chars"] == 26, "对白识别：动作行与长前缀叙述不计入")
check(hardcheck.count_dialogue("") == {"lines": 0, "chars": 0}, "空文本对白为 0")

# ---- 1. run_hard_checks 单元测试 ----

def make_script(scene_lens, with_dialogue=False):
    """按给定每场字数造剧本；with_dialogue 时全部用「甲：台词」行填充。"""
    parts = []
    for i, n in enumerate(scene_lens, 1):
        parts.append(f"第{i}场 地点{i}")
        if with_dialogue:
            for _ in range(n // 62):
                parts.append("甲：" + "台" * 60)
            parts.append("甲：" + "台" * (n % 62))
        else:
            parts.append("动" * n)
    return "\n".join(parts)


hc = hardcheck.run_hard_checks(make_script([2000, 10, 1500, 1500]))
check(hc["skipped"] is False, "长剧本（≥5000 字）执行判定")
check(hc["dialogue"]["verdict"].startswith("偏低"), "对白占比 0 → 偏低")
check([x["scene"] for x in hc["scenes"]["too_long"]] == [1], "仅第1场 2000 字 → 过长")
check([x["scene"] for x in hc["scenes"]["too_short"]] == [2], "第2场 10 字 → 过短")
check(hc["scenes"]["longest"] == {"scene": 1, "chars": 2000}, "最长场次定位正确")
check(hc["scenes"]["shortest"] == {"scene": 2, "chars": 10}, "最短场次定位正确")
check(hc["scenes"]["verdict"] == "正常", "平均每场约 2 分钟 → 分布正常")

hc_dia = hardcheck.run_hard_checks(make_script([3000, 3000], with_dialogue=True))
check(hc_dia["dialogue"]["ratio"] > 0.9 and hc_dia["dialogue"]["verdict"].startswith("偏高"),
      "对白占比 ≈1 → 偏高")

hc_frag = hardcheck.run_hard_checks(make_script([170] * 30))
check("碎片化" in hc_frag["scenes"]["verdict"], "30 场 × 170 字 → 碎片化")

hc_slow = hardcheck.run_hard_checks(make_script([6000]))
check("单场拖沓" in hc_slow["scenes"]["verdict"], "单场 10 分钟 → 单场拖沓")
check(hc_slow["page_time"]["pages"] == 10.0 and hc_slow["page_time"]["minutes"] == 10.0,
      "页数↔时长：约 6000 字 ≈ 10 页 ≈ 10 分钟")

hc_short = hardcheck.run_hard_checks("第1场 测试\n你好。")
check(hc_short["skipped"] is True and "样本过短" in hc_short["dialogue"]["verdict"],
      "短样本 → 跳过判定")
check(hc_short["scenes"]["too_long"] == [] and hc_short["scenes"]["too_short"] == [],
      "短样本不出异常场次清单")

hc_empty = hardcheck.run_hard_checks("")
check(hc_empty["skipped"] is True and hc_empty["page_time"]["chars"] == 0, "空文本不崩溃且跳过判定")

# ---- 1.5 场次切分：首个场头前的标题行不建场 ----
import analyzer  # noqa: E402

scenes = analyzer.split_scenes("《剧名》\n\n第一场 夜 地点\n甲：你好。")
check(len(scenes) == 1 and scenes[0]["title"] == "第一场 夜 地点",
      "场头前的《剧名》标题不建场")
check(hardcheck.run_hard_checks("《剧名》\n\n第一场 夜 地点\n甲：你好。")["scenes"]["count"] == 1,
      "硬检查场数与切分口径一致")

# ---- 2. AppTest：报告页渲染硬检查节 ----
import analyzer as ana2  # noqa: E402

FAKE_REPORT = {
    "script_meta": {"title": "硬检查测试剧本", "word_count": 3000, "scene_count": 3, "acts": []},
    "score": {"overall": 77,
              "dimensions": {"character": 70, "emotion": 70, "pacing": 70, "logic": 70, "commercial": 70}},
    "characters": {"cast": [], "distribution_issues": []},
    "relationships": [],
    "emotion_curve": {"points": [], "summary": "", "flatness_issues": []},
    "pacing": {"per_act": [], "overall_verdict": "", "dragging_scenes": [], "rushed_scenes": []},
    "logic": {"holes": []},
    "commercial": {"genre_elements": [], "target_audience": "", "benchmarks": [],
                   "strengths": [], "risks": [], "confidence": 0.5},
    "suggestions": [],
    "hard_checks": {
        "dialogue": {"ratio": 0.5, "chars": 1500, "lines": 20, "verdict": "正常"},
        "scenes": {
            "count": 3, "lengths": [2000, 100, 900],
            "avg": 1000.0, "median": 900.0,
            "longest": {"scene": 1, "chars": 2000},
            "shortest": {"scene": 2, "chars": 100},
            "too_long": [{"scene": 1, "chars": 2000, "minutes": 3.3}],
            "too_short": [{"scene": 2, "chars": 100}],
            "verdict": "正常",
        },
        "page_time": {"page_chars": 600, "chars": 3000, "pages": 5.0, "minutes": 5.0},
        "skipped": False,
    },
    "meta": {"model": "fake", "generated_at": "", "is_cached_demo": False, "chunked": False,
             "tokens": {}, "est_cost_usd": 0.0, "timings": {}, "total_elapsed_sec": 0.0},
}


def fake_pipeline(text, client, progress_cb=None, prev_suggestions=None, modules=None):
    if progress_cb:
        progress_cb(1.0, "完成")
    return FAKE_REPORT, []


ana2.run_pipeline = fake_pipeline

auth.register("硬检查用户", "abc12345")
at = AppTest.from_file(APP, default_timeout=60)
at.run()
check(not at.exception, "首次加载无异常（auth 页）")
at.text_input(key="login_username").set_value("硬检查用户")
at.text_input(key="login_password").set_value("abc12345")
at.button(key="btn_login").click().run()
at.text_area(key="paste_area").set_value("第1场 硬检查测试")
at.run()
at.button(key="btn_paste").click().run()
check(not at.exception, "分析（打桩）无异常")
check(at.session_state["stage"] == "report", "进入 report 页")

check(any(m.value == "50%" for m in at.metric), "对白占比 50% 指标显示")
check(any(m.value == "≈ 5.0 页" for m in at.metric), "预计页数指标显示")
check(any(m.value == "≈ 5.0 分钟" for m in at.metric), "预计片长指标显示")
check(any("每场字数" in m.value for m in at.markdown), "每场字数统计显示")
check(chart_contains(at.get("plotly_chart"), "第2场"), "每场字数柱状图渲染")
check(any("第1场过长" in w.value for w in at.warning), "过长场次警告显示")
check(any("第2场过短" in w.value for w in at.warning), "过短场次警告显示")

# ---- 3. AppTest：离线演示（skipped 路径）+ 老报告无数据 ----
at.button(key="btn_logout").click().run()
at.button(key="btn_guest").click().run()
next(b for b in at.button if "离线演示报告" in b.label).click().run()
check(not at.exception, "离线演示无异常")
check(any(m.value == "37%" for m in at.metric), "离线演示对白占比 37% 指标显示")
check(chart_contains(at.get("plotly_chart"), "第4场"), "离线演示每场字数柱状图渲染")
caps = [c.value for c in at.caption]
check(any("样本过短" in c for c in caps), "离线演示显示「样本过短，跳过判定」")

# 老报告（无 hard_checks）→ 显示无数据提示
FAKE_OLD = {k: v for k, v in FAKE_REPORT.items() if k != "hard_checks"}


def fake_pipeline_old(text, client, progress_cb=None, prev_suggestions=None, modules=None):
    if progress_cb:
        progress_cb(1.0, "完成")
    return FAKE_OLD, []


ana2.run_pipeline = fake_pipeline_old
at2 = AppTest.from_file(APP, default_timeout=60)
at2.run()
at2.text_input(key="login_username").set_value("硬检查用户")
at2.text_input(key="login_password").set_value("abc12345")
at2.button(key="btn_login").click().run()
at2.text_area(key="paste_area").set_value("第1场 旧报告测试")
at2.run()
at2.button(key="btn_paste").click().run()
check(not at2.exception, "老报告（无 hard_checks）渲染无异常")
caps2 = [c.value for c in at2.caption]
check(any("旧版报告未包含硬检查" in c for c in caps2), "老报告显示「无数据（旧版报告未包含硬检查）」")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
