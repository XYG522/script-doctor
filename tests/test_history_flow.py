"""分析历史记录回归测试：入库/列表/取回 → 游客无入口 → 分析自动保存 → 历史页打开报告。

运行：py tests/test_history_flow.py（在 script-doctor 目录下）
使用临时数据库，不污染真实 users.db；分析管线打桩，不调用 API，可反复运行。
"""
import os
import sys
import tempfile

# 必须在 AppTest 之前打补丁：app.py 里的 init_db() 会用到 DB_PATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth  # noqa: E402
import history  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

_TMP = os.path.join(tempfile.mkdtemp(), "users.db")
auth.DB_PATH = _TMP
history.DB_PATH = _TMP
auth.init_db()  # 函数层用例在 AppTest 之前运行，需先建表
history.init_db()
os.environ["DEEPSEEK_API_KEY"] = "sk-test"  # 仅用于构造客户端，不发网络请求
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
failures = []


def check(cond, msg):
    print(("PASS" if cond else "FAIL") + ": " + msg)
    if not cond:
        failures.append(msg)


# ---- 0. 函数层：注册 → save → list → get → 隔离 ----
ok, _ = auth.register("历史单元", "abc12345")
check(ok, "注册测试用户成功")
uid = auth.get_user_id("历史单元")
check(isinstance(uid, int), f"get_user_id 返回用户 id（{uid}）")

SAMPLE = {
    "script_meta": {"title": "单元剧本", "word_count": 1234, "scene_count": 7},
    "score": {"overall": 88, "dimensions": {}},
}
rid = history.save_report(uid, script_excerpt="  第 1 场\n测试内容  " * 60, report=SAMPLE)
check(isinstance(rid, int), f"save_report 返回记录 id（{rid}）")
lst = history.list_reports(uid)
check(len(lst) == 1, "list_reports 返回 1 条")
check(lst[0]["title"] == "单元剧本" and lst[0]["score"] == 88, "列表含标题与评分")
check(
    lst[0]["script_excerpt"].startswith("第1场测试内容") and len(lst[0]["script_excerpt"]) <= 200,
    "摘要去空白且不超过 200 字",
)
check("report_json" not in lst[0], "列表不含完整 JSON")
got = history.get_report(uid, rid)
check(got is not None and got["script_meta"]["title"] == "单元剧本", "get_report 返回完整报告")
check(history.get_report(uid + 999, rid) is None, "非本人 get_report 返回 None")
check(history.get_report(uid, rid + 999) is None, "不存在 id 返回 None")
auth.register("隔离用户", "abc12345")
check(history.list_reports(auth.get_user_id("隔离用户")) == [], "用户间数据隔离")

# ---- 打桩：分析管线换成假实现（不调 API）----
import analyzer  # noqa: E402

FAKE_REPORT = {
    "script_meta": {"title": "界面剧本", "word_count": 8, "scene_count": 1, "acts": []},
    "score": {"overall": 77,
              "dimensions": {"character": 7, "emotion": 7, "pacing": 7, "logic": 7, "commercial": 7}},
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
    if progress_cb:
        progress_cb(1.0, "完成")
    return FAKE_REPORT, []


analyzer.run_pipeline = fake_pipeline

# ---- 1. AppTest 界面流程 ----
auth.register("界面用户", "abc12345")
uid_ui = auth.get_user_id("界面用户")

at = AppTest.from_file(APP, default_timeout=60)
at.run()
check(not at.exception, "首次加载无异常（auth 页）")

# 1a. 游客不显示历史入口
at.button(key="btn_guest").click().run()
check("我的历史" not in [b.label for b in at.button], "游客不显示「我的历史」按钮")
at.button(key="btn_logout").click().run()

# 1b. 登录 → 历史页空状态 → 返回上传页
at.text_input(key="login_username").set_value("界面用户")
at.text_input(key="login_password").set_value("abc12345")
at.button(key="btn_login").click().run()
at.button(key="btn_history").click().run()
check(at.session_state["stage"] == "history", "点「我的历史」进入 history 页")
check(any("还没有分析记录" in i.value for i in at.info), "空状态提示可见")
at.button(key="btn_hist_back").click().run()
check(at.session_state["stage"] == "upload", "「返回上传页」回到 upload")

# 1c. 粘贴文本 → 在线分析（打桩）→ 自动入库
at.text_area(key="paste_area").set_value("第1场 界面测试内容")
at.run()
at.button(key="btn_paste").click().run()
check(not at.exception, "分析（打桩）无异常")
check(at.session_state["stage"] == "report", "分析完成进入 report 页")
check(any("界面剧本" in t.value for t in at.title), "报告页显示标题")
saved = history.list_reports(uid_ui)
check(len(saved) == 1 and saved[0]["script_excerpt"] == "第1场界面测试内容",
      "分析完成后自动保存（摘要=原文去空白）")

# 1d. 重新分析入口 → 历史页列表 → 模拟点行打开报告
next(b for b in at.button if b.label == "重新分析其他剧本").click().run()
check(at.session_state["stage"] == "upload", "「重新分析」回到 upload")
at.button(key="btn_history").click().run()
check(at.session_state["stage"] == "history", "再次进入 history 页")
check(len(at.dataframe) == 1 and len(at.dataframe[0].value) == 1, "历史列表 1 行")
at.session_state["hist_table"] = {"selection": {"rows": [0], "columns": []}}
at.run()
check(at.session_state["stage"] == "report", "点行后打开报告页")
check(at.session_state["from_history"] is True, "from_history=True")
check(any(b.label == "返回历史" for b in at.button), "报告页显示「返回历史」按钮")

# 1e. 返回历史：确认选中已清空，不被选中事件弹回报告页
next(b for b in at.button if b.label == "返回历史").click().run()
check(at.session_state["stage"] == "history", "「返回历史」回到 history 页且未被弹回")

# 1f. 退出登录清 user_id
at.button(key="btn_logout").click().run()
check(at.session_state["stage"] == "auth" and at.session_state["user_id"] is None,
      "退出登录回到 auth 且 user_id 清空")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
