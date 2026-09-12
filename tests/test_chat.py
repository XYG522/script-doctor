"""剧本医生对话回归测试：摘要/上下文/成本单元 → ask_doctor 引用校验 → 报告页对话界面流程。

运行：py tests/test_chat.py（在 script-doctor 目录下）
使用临时数据库，不污染真实 users.db；分析管线与对话调用打桩，不调用 API，可反复运行。
"""
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


def check(cond, msg):
    print(("PASS" if cond else "FAIL") + ": " + msg)
    if not cond:
        failures.append(msg)


# ---- 0. report_digest 单元测试 ----
REP = {
    "script_meta": {"title": "对话剧本", "word_count": 100, "scene_count": 2, "acts": []},
    "score": {"overall": 77, "dimensions": {"character": 70, "emotion": 60, "pacing": 50,
                                            "logic": 40, "commercial": 65}},
    "logic": {"holes": [{"id": "lh1", "severity": "high", "description": "时间线矛盾"}]},
    "suggestions": [{"rank": 1, "problem": "修补时间线", "action": {"scene": 1, "concrete": "x"}}],
    "hard_checks": {"dialogue": {"verdict": "正常"}, "scenes": {"verdict": "正常"}},
}
d = analyzer.report_digest(REP)
check("综合评分：77/100" in d, "摘要含综合评分")
check("分项：角色 70、情感 60、节奏 50、逻辑 40、商业 65" in d, "摘要含 5 维分项")
check("[lh1][high] 时间线矛盾" in d, "摘要含漏洞（id/severity/描述）")
check("1. 修补时间线（落点第 1 场）" in d, "摘要含修改建议与落点")
check("硬检查：正常；正常" in d, "摘要含硬检查结论")
d_none = analyzer.report_digest({"script_meta": {"title": "免费", "word_count": 10, "scene_count": 1}})
check("未评分" in d_none, "无评分报告摘要标注未评分")

# ---- 1. chat_context_text：≤2 万全文 / 超长场头概览 ----
SCRIPT = "第1场 甲\n他说 你好。\n第2场 乙\n好quote"
ctx, kind = analyzer.chat_context_text(SCRIPT)
check(ctx == SCRIPT and kind == "全文", "≤2 万字上下文 = 全文")
LONG = ("第1场 甲\n" + "动" * 8000 + "\n第2场 乙\n" + "动" * 8000
        + "\n第3场 丙\n" + "动" * 8000)
lctx, lkind = analyzer.chat_context_text(LONG)
check(lkind.startswith("场头概览") and "第1场 甲" in lctx and "第2场 乙" in lctx,
      ">2 万字上下文 = 场头概览（含场头）")
check(len(lctx) < 1500, "场头概览不含全文（远小于原文）")

# ---- 2. estimate_chat_cost：公式与单调性 ----
est = analyzer.estimate_chat_cost(SCRIPT, REP, [], "")
in_tok = len(SCRIPT) + len(analyzer.report_digest(REP)) + 600
check(est["calls"] == 1 and est["input_tokens"] == int(in_tok) and est["output_tokens"] == 480,
      "单问成本公式：输入=剧本+摘要+开销，输出=400×1.2=480")
check(est["est_cost_usd"] == round((int(in_tok) * 0.66 + 480 * 1.98) / 1e6, 4),
      "单问成本按闲时价换算")
est_q = analyzer.estimate_chat_cost(SCRIPT, REP, [], "很长的追问" + "x" * 100)
check(est_q["input_tokens"] > est["input_tokens"], "追问越长成本越高（单调）")
est_h = analyzer.estimate_chat_cost(SCRIPT, REP, [{"role": "user", "content": "你好" * 10}], "")
check(est_h["input_tokens"] == est["input_tokens"] + 20, "历史消息计入输入成本")
check(analyzer.estimate_chat_cost(LONG, REP, [], "")["input_tokens"] < len(LONG) + 600,
      "长剧本按场头概览计费（远低于全文）")

# ---- 3. ask_doctor：prompt 组装 + 引用逐字硬校验 ----
GOOD = {"answer": "主角动机在第2场立起来。",
        "evidence_quotes": [{"scene": 2, "text": "好quote"}], "confidence": 0.7}


class FakeClient:
    model = "fake"

    def __init__(self, data=None, fail=False):
        self.calls = []
        self.data = data
        self.fail = fail

    def complete(self, system, user):
        self.calls.append({"system": system, "user": user})
        if self.fail:
            raise RuntimeError("网络错误")
        return {"data": self.data, "elapsed": 0.1,
                "usage": {"input_tokens": 100, "cache_hit_tokens": 0, "output_tokens": 50}}

    @staticmethod
    def estimate_cost(u):
        return (u.get("input_tokens", 0) * 0.66 + u.get("output_tokens", 0) * 1.98) / 1e6


c1 = FakeClient(data=GOOD)
data1, usage1 = analyzer.ask_doctor(c1, SCRIPT, REP, [], "主角的动机？")
check(data1 == GOOD and usage1 == {"input_tokens": 100, "cache_hit_tokens": 0, "output_tokens": 50},
      "有效回答原样返回（引用命中原文）")
check("剧本医生" in c1.calls[0]["system"], "system 复用 SYSTEM_BASE + 剧本医生角色卡")
u1 = c1.calls[0]["user"]
check("主角的动机？" in u1 and "第2场 乙" in u1 and "综合评分：77/100" in u1 and "（无）" in u1,
      "user 含剧本全文 + 报告摘要 + 提问 + 空历史标记")

c2 = FakeClient(data={"answer": "随便说", "evidence_quotes": [{"scene": 1, "text": "不存在引用"}],
                      "confidence": 0.5})
warns2 = []
data2, _ = analyzer.ask_doctor(c2, SCRIPT, REP, [], "问", warns2)
check(data2["answer"] == "随便说" and data2["evidence_quotes"] == [],
      "未命中原文的引用被剔除（答案保留）")
check(any("剔除未命中原文" in w for w in warns2), "剔除引用时记录警告")

c3 = FakeClient(data=GOOD)
history3 = [{"role": "user", "content": f"第{i}问"} for i in range(12)]
analyzer.ask_doctor(c3, SCRIPT, REP, history3, "新问题")
u3 = c3.calls[0]["user"]
check("user：第0问" not in u3 and "user：第11问" in u3 and "新问题" in u3,
      "历史只携带最近 10 条（最早 2 条被截断）")

orig_retries = analyzer.MAX_REPAIR_RETRIES
analyzer.MAX_REPAIR_RETRIES = 0  # 免重试等待，直接验证降级路径
c4 = FakeClient(data={"answer": "缺 confidence 字段"})
warns4 = []
data4, usage4 = analyzer.ask_doctor(c4, SCRIPT, REP, [], "问", warns4)
check(data4 is None and usage4 == {"input_tokens": 0, "cache_hit_tokens": 0, "output_tokens": 0},
      "schema 校验失败 → 降级为 None（调用方兜底）")
check(any("降级为空" in w for w in warns4), "校验失败记录降级警告")

c5 = FakeClient(data=GOOD, fail=True)
warns5 = []
data5, _ = analyzer.ask_doctor(c5, SCRIPT, REP, [], "问", warns5)
check(data5 is None and any("调用失败" in w for w in warns5), "网络异常不抛出，降级并记录")
analyzer.MAX_REPAIR_RETRIES = orig_retries

# ---- 4. AppTest 界面流程 ----
FAKE_LOGS = {"questions": [], "hist_lens": [], "script": None}
FAKE_REPORT = {
    "script_meta": {"title": "对话剧本", "word_count": 30, "scene_count": 2, "acts": []},
    "score": {"overall": 77, "dimensions": {"character": 70, "emotion": 70, "pacing": 70,
                                            "logic": 70, "commercial": 70}},
    "characters": {"cast": [], "distribution_issues": []},
    "relationships": [],
    "emotion_curve": {"points": [], "summary": "", "flatness_issues": []},
    "pacing": {"per_act": [], "overall_verdict": "", "dragging_scenes": [], "rushed_scenes": []},
    "logic": {"holes": []},
    "commercial": {"genre_elements": [], "target_audience": "", "benchmarks": [],
                   "strengths": [], "risks": [], "confidence": 0.5},
    "suggestions": [],
    "meta": {"model": "fake", "generated_at": "", "is_cached_demo": False, "chunked": False,
             "modules_selected": list(analyzer.MODULES_R2),
             "tokens": {}, "est_cost_usd": 0.0, "timings": {}, "total_elapsed_sec": 0.0},
}
CHAT_DATA = {"answer": "主角动机在第2场立起来。",
             "evidence_quotes": [{"scene": 2, "text": "好quote"}], "confidence": 0.9}


def fake_pipeline(text, client, progress_cb=None, prev_suggestions=None, modules=None):
    if progress_cb:
        progress_cb(1.0, "完成")
    return FAKE_REPORT, []


def fake_ask_doctor(client, script_text, report, history, question, warnings=None):
    FAKE_LOGS["questions"].append(question)
    FAKE_LOGS["hist_lens"].append(len(history))
    FAKE_LOGS["script"] = script_text
    return CHAT_DATA, {"input_tokens": 100, "cache_hit_tokens": 0, "output_tokens": 50}


analyzer.run_pipeline = fake_pipeline
analyzer.ask_doctor = fake_ask_doctor

auth.register("对话用户", "abc12345")
at = AppTest.from_file(APP, default_timeout=60)
at.run()
check(not at.exception, "首次加载无异常（auth 页）")
at.text_input(key="login_username").set_value("对话用户")
at.text_input(key="login_password").set_value("abc12345")
at.button(key="btn_login").click().run()
at.text_area(key="paste_area").set_value(SCRIPT)
at.run()
at.button(key="btn_paste").click().run()
check(not at.exception, "分析（打桩）无异常")
check(at.session_state["stage"] == "report", "进入 report 页")
check(any("剧本医生对话" in s.value for s in at.subheader), "报告页显示对话区标题")
check(any("单问预估" in c.value for c in at.caption), "显示单问成本预估")
check(len(at.chat_input) == 1, "在线报告渲染追问输入框")

at.chat_input[0].set_value("主角的动机？").run()
check(FAKE_LOGS["questions"] == ["主角的动机？"], "输入框提交内容传给 ask_doctor")
check(FAKE_LOGS["script"] == SCRIPT, "ask_doctor 收到剧本全文")
check(FAKE_LOGS["hist_lens"] == [1], "提交时历史含刚追加的用户消息")
check(not at.exception, "提交追问后渲染无异常")
msgs = at.chat_message
check(len(msgs) == 2, "渲染用户 + 医生两条气泡")
md = [m.value for m in at.markdown]
check(any("主角动机在第2场立起来" in x for x in md), "医生回答正文显示")
check(any("引用 · 第 2 场：“好quote”" in x for x in md), "已验证引用以引用块显示")
caps = [c.value for c in at.caption]
check(any("置信度" in c and "90%" in c for c in caps), "置信度徽章显示（0.9 → 高 · 90%）")
check(any("已问 1 次" in c and "累计" in c for c in caps), "累计调用与成本显示")
check(at.session_state["chat_usage"]["calls"] == 1, "会话累计 1 次调用")

at.chat_input[0].set_value("反派是谁？").run()
check(len(FAKE_LOGS["questions"]) == 2 and FAKE_LOGS["questions"][-1] == "反派是谁？",
      "第二轮追问正常提交")
check(FAKE_LOGS["hist_lens"][-1] == 3, "第二轮携带完整历史（2 条旧 + 1 条新用户）")
check(at.session_state["chat_usage"]["calls"] == 2, "会话累计 2 次调用")

# 游客：离线演示 → 无输入框
at.button(key="btn_logout").click().run()
at.button(key="btn_guest").click().run()
next(b for b in at.button if "离线演示报告" in b.label).click().run()
check(not at.exception, "游客离线演示无异常")
check(any("游客模式不支持对话" in i.value for i in at.info), "游客显示对话不可用说明")
check(len(at.chat_input) == 0, "游客不渲染追问输入框")

# 历史打开旧报告 → 禁用并说明
at.button(key="btn_logout").click().run()
at.text_input(key="login_username").set_value("对话用户")
at.text_input(key="login_password").set_value("abc12345")
at.button(key="btn_login").click().run()
at.button(key="btn_history").click().run()
at.session_state["hist_table"] = {"selection": {"rows": [0], "columns": []}}
at.run()
check(at.session_state["from_history"] is True, "历史选中进入 from_history 模式")
check(any("旧报告未存全文" in i.value for i in at.info), "历史报告显示「未存全文，暂不支持对话」")
check(len(at.chat_input) == 0, "历史报告不渲染追问输入框")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
