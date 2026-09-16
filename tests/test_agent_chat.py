"""剧本医生 Agent 回归测试：工具执行 / 多轮循环 / 引用硬校验 / 步数上限 / 修复重试 / 成本预估 / 降级。

运行：py tests/test_agent_chat.py（在 script-doctor 目录下）
全部使用 FakeAgentClient 打桩（脚本化工具轮次 + 收尾输出），不发网络请求；
AppTest 部分使用临时数据库，不污染真实 users.db。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analyzer  # noqa: E402
import doctor_agent  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

failures = []


def check(cond, msg):
    print(("PASS" if cond else "FAIL") + ": " + msg)
    if not cond:
        failures.append(msg)


SCRIPT = (
    "第1场 深夜便利店\n"
    "男主林远走进便利店，说：我要一包烟。\n"
    "第2场 街角\n"
    "林远想起母亲的遗言：别回头。\n"
    "第3场 天台\n"
    "林远决定自首。动机在此立起。\n"
)
REP = {
    "script_meta": {"title": "对话剧本", "word_count": 100, "scene_count": 2, "acts": []},
    "score": {"overall": 77, "dimensions": {"character": 70, "emotion": 60, "pacing": 50,
                                            "logic": 40, "commercial": 65}},
    "logic": {"holes": [{"id": "lh1", "severity": "high", "description": "时间线矛盾"}]},
    "suggestions": [{"rank": 1, "problem": "修补时间线", "action": {"scene": 1, "concrete": "x"}}],
    "hard_checks": {"dialogue": {"verdict": "正常"}, "scenes": {"verdict": "正常"}},
}
TOOL = lambda kw: {"content": "", "tool_calls": [  # noqa: E731
    {"id": "c1", "name": "search_script", "arguments": '{"keyword": "%s"}' % kw}]}
FINAL_OK = {"content": '{"answer":"主角动机在第3场立起。",'
                       '"evidence_quotes":[{"scene":3,"text":"动机在此立起"}],'
                       '"confidence":0.9}', "tool_calls": []}


class FakeAgentClient:
    """脚本化假客户端：complete_with_tools 按预设轮次返回；complete 按预设序列返回收尾结果。"""

    model = "fake-agent"

    def __init__(self, turns, finals=None):
        self.turns = list(turns)
        self.finals = list(finals or [])
        self.i = 0
        self.final_i = 0
        self.log = []  # [("tools", messages) / ("complete", user_text)]

    def complete_with_tools(self, system, messages, tools):
        self.log.append({"kind": "tools", "system": system, "messages": messages})
        assert self.i < len(self.turns), "工具轮次超预期"
        turn = self.turns[self.i]
        self.i += 1
        return {"message": turn, "elapsed": 0.1,
                "usage": {"input_tokens": 100, "cache_hit_tokens": 0, "output_tokens": 50}}

    def complete(self, system, user):
        self.log.append({"kind": "complete", "system": system, "user": user})
        assert self.final_i < len(self.finals), "收尾调用超预期"
        data = self.finals[self.final_i]
        self.final_i += 1
        return {"data": data, "elapsed": 0.1,
                "usage": {"input_tokens": 100, "cache_hit_tokens": 0, "output_tokens": 50}}

    @staticmethod
    def estimate_cost(u):
        return (u.get("input_tokens", 0) * 0.66 + u.get("output_tokens", 0) * 1.98) / 1e6


# ---- 0. 工具单元测试 ----
scenes = analyzer.split_scenes(SCRIPT)
r = doctor_agent._search_script(scenes, "林远")
check(r["found"] == 3 and all("林远" in h["excerpt"] for h in r["hits"]),
      "搜索命中 3 场且片段含关键词")
check("命中 3 条" in r["note"], "命中摘要含条数")
r0 = doctor_agent._search_script(scenes, "不存在")
check(r0["found"] == 0 and "未找到" in r0["note"], "无命中明确提示")
check(doctor_agent._search_script(scenes, "  ")["note"] == "关键词为空", "空关键词提示")
s2 = doctor_agent._get_scene(scenes, 2)
check(s2 is not None and "别回头" in s2["content"], "get_scene 返回场次原文")
check(doctor_agent._get_scene(scenes, 99) is None, "不存在的场次返回 None")
sec = doctor_agent._read_report_section(REP, "logic")
check(sec["found"] and "时间线矛盾" in sec["data"], "报告章节可读")
check(not doctor_agent._read_report_section(REP, "structure")["found"],
      "缺失章节返回 found=False")
bad = doctor_agent._execute_tool({"name": "不存在工具", "arguments": "{}"}, scenes, REP)
check("未知工具" in bad["error"], "未知工具返回错误")
check(all(t["function"]["name"] in doctor_agent.TOOL_LABELS for t in doctor_agent.TOOLS),
      "全部工具都有 UI 中文标签")

# ---- 1. 多轮循环：查证 → 回喂 → 最终回答 + 引用硬校验 ----
c1 = FakeAgentClient([TOOL("动机"), FINAL_OK])
warn1 = []
data1, usage1, trace1 = doctor_agent.run_doctor_agent(
    c1, SCRIPT, REP, [], "主角的动机在哪立起？", warnings=warn1)
check(data1 and data1["answer"] == "主角动机在第3场立起。", "最终回答返回")
check(data1["evidence_quotes"][0]["text"] == "动机在此立起", "命中原文的引用保留")
check(usage1["calls"] == 2 and usage1["input_tokens"] == 200, "2 步 = 2 次调用，用量累计")
check(len(trace1) == 1 and trace1[0]["name"] == "search_script"
      and trace1[0]["summary"] == "命中 1 条", "trace 记录工具执行与摘要")
tool_msgs = [m for m in c1.log[1]["messages"] if m.get("role") == "tool"]
check(len(tool_msgs) == 1 and "动机在此立起" in tool_msgs[0]["content"],
      "工具结果回喂给下一轮")
u0 = c1.log[0]["messages"][0]["content"]
check("主角的动机在哪立起？" in u0 and "剧本医生" in c1.log[0]["system"] and "（无）" in u0,
      "首轮 user 含提问 + 空历史，system 含剧本医生角色")

# ---- 2. 引用硬校验：未命中原文的引用剔除 ----
FINAL_BAD = {"content": '{"answer":"随便说","evidence_quotes":[{"scene":1,"text":"不存在的台词"}],'
                        '"confidence":0.5}', "tool_calls": []}
warn2 = []
data2, _, _ = doctor_agent.run_doctor_agent(
    FakeAgentClient([FINAL_BAD]), SCRIPT, REP, [], "问", warnings=warn2)
check(data2["answer"] == "随便说" and data2["evidence_quotes"] == [],
      "未命中全文的引用被剔除（答案保留）")
check(any("剔除未命中原文" in w for w in warn2), "剔除引用时记录警告")

# ---- 3. 步数上限：6 步全是工具调用 → 强制收尾 ----
always_tool = [{"content": "", "tool_calls": [
    {"id": f"c{i}", "name": "search_script", "arguments": '{"keyword": "林远"}'}]}
    for i in range(6)]
warn3 = []
c3 = FakeAgentClient(always_tool, finals=[
    {"answer": "查证后回答", "evidence_quotes": [], "confidence": 0.5}])
data3, usage3, trace3 = doctor_agent.run_doctor_agent(
    c3, SCRIPT, REP, [], "林远出现了几次？", warnings=warn3)
check(data3 and data3["answer"] == "查证后回答", "收尾强制调用产出最终回答")
check(len(trace3) == 5, "前 5 步执行工具，第 6 步留给收尾")
check(usage3["calls"] == 7, "6 步循环 + 1 次收尾 = 7 次调用")
check(any("最大步数" in w for w in warn3), "记录超步数警告")
force_text = next((l["user"] for l in c3.log if l["kind"] == "complete"), "")
check("不要调用工具" in force_text and "林远出现了几次？" in force_text,
      "收尾指令重放完整对话并强制直接回答")
check(usage3["input_tokens"] == 700, "7 次调用的输入 token 累计")

# ---- 4. 首答不是合法 JSON → 收尾调用修复 ----
warn4 = []
data4, usage4, _ = doctor_agent.run_doctor_agent(
    FakeAgentClient([{"content": "抱歉我无法回答这个问题", "tool_calls": []}],
                    finals=[{"answer": "已修复", "evidence_quotes": [], "confidence": 0.6}]),
    SCRIPT, REP, [], "问", warnings=warn4)
check(data4 and data4["answer"] == "已修复", "首答非法 → 收尾调用修复")
check(usage4["calls"] == 2, "1 步循环 + 1 次收尾")
check(any("不是合法 JSON" in w for w in warn4), "记录首答非法警告")

# ---- 5. 收尾 schema 校验失败 → 修复重试 ----
warn5 = []
data5, usage5, _ = doctor_agent.run_doctor_agent(
    FakeAgentClient([{"content": "", "tool_calls": []}],
                    finals=[{"answer": "缺 confidence"},
                            {"answer": "好了", "evidence_quotes": [], "confidence": 0.5}]),
    SCRIPT, REP, [], "问", warnings=warn5)
check(data5 and data5["answer"] == "好了", "schema 失败 → 修复重试 1 次成功")
check(usage5["calls"] == 3, "1 步循环 + 2 次收尾（含修复重试）")
check(any("修复重试" in w for w in warn5), "记录校验失败与修复")

# ---- 6. 工具轮调用异常 → 返回 None（由调用方降级单轮）----
warn6 = []
data6, usage6, trace6 = doctor_agent.run_doctor_agent(
    FakeAgentClient([], finals=[]), SCRIPT, REP, [], "问", warnings=warn6)
check(data6 is None and usage6["calls"] == 0 and trace6 == [],
      "工具轮无可用输出且异常 → 返回 None")
check(any("调用失败" in w for w in warn6), "记录异常")

# ---- 7. 工具参数非法 JSON → 错误回喂，循环继续 ----
warn7 = []
c7 = FakeAgentClient([{"content": "", "tool_calls": [
    {"id": "c1", "name": "search_script", "arguments": "不是json"}]}, FINAL_OK])
data7, _, trace7 = doctor_agent.run_doctor_agent(c7, SCRIPT, REP, [], "问", warnings=warn7)
check(data7 is not None, "参数非法不中断循环，最终仍有回答")
check(trace7[0]["summary"].startswith("失败"), "非法参数 → 工具失败摘要")
tool_msgs7 = [m for m in c7.log[1]["messages"] if m.get("role") == "tool"]
check("error" in tool_msgs7[0]["content"], "错误信息回喂模型")

# ---- 8. 成本预估：单轮 × 3 步 ----
est = doctor_agent.estimate_agent_cost(SCRIPT, REP, [], "")
per = analyzer.estimate_chat_cost(SCRIPT, REP, [], "")
check(est["calls"] == doctor_agent.AGENT_EST_STEPS
      and est["input_tokens"] == per["input_tokens"] * doctor_agent.AGENT_EST_STEPS,
      "预估 = 单轮成本 × 平均步数")

# ---- 9. AppTest：agent 成功（trace 渲染 + 调用计数）→ 异常降级单轮 ----
import auth  # noqa: E402
import history  # noqa: E402

_TMP = os.path.join(tempfile.mkdtemp(), "users.db")
auth.DB_PATH = _TMP
history.DB_PATH = _TMP
auth.init_db()
history.init_db()
os.environ["DEEPSEEK_API_KEY"] = "sk-test"  # 仅用于构造客户端，不发网络请求
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
FAKE_REPORT = {
    "script_meta": {"title": "Agent剧本", "word_count": 30, "scene_count": 3, "acts": []},
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
AGENT_LOGS = {"questions": []}


def fake_pipeline(text, client, progress_cb=None, prev_suggestions=None, modules=None):
    if progress_cb:
        progress_cb(1.0, "完成")
    return FAKE_REPORT, []


def fake_agent_ok(client, script_text, report, history, question, step_cb=None, warnings=None):
    AGENT_LOGS["questions"].append(question)
    return ({"answer": "Agent查证回答", "evidence_quotes": [], "confidence": 0.8},
            {"input_tokens": 10, "cache_hit_tokens": 0, "output_tokens": 5, "calls": 3},
            [{"name": "search_script", "args": "{}", "summary": "命中 1 条"}])


def fake_agent_raise(client, script_text, report, history, question, step_cb=None, warnings=None):
    raise RuntimeError("agent 挂了")


def fake_ask_doctor(client, script_text, report, history, question, warnings=None):
    return ({"answer": "单轮兜底回答", "evidence_quotes": [], "confidence": 0.5},
            {"input_tokens": 10, "cache_hit_tokens": 0, "output_tokens": 5})


analyzer.run_pipeline = fake_pipeline
doctor_agent.run_doctor_agent = fake_agent_ok

auth.register("Agent用户", "abc12345")
at = AppTest.from_file(APP, default_timeout=60)
at.run()
check(not at.exception, "首次加载无异常（auth 页）")
at.text_input(key="login_username").set_value("Agent用户")
at.text_input(key="login_password").set_value("abc12345")
at.button(key="btn_login").click().run()
at.text_area(key="paste_area").set_value(SCRIPT)
at.run()
at.button(key="btn_paste").click().run()
check(at.session_state["stage"] == "report", "进入 report 页")
check(any("agent 模式" in c.value for c in at.caption), "成本预估标注 agent 模式")

at.chat_input[0].set_value("主角动机？").run()
check(AGENT_LOGS["questions"] == ["主角动机？"], "提问传给 run_doctor_agent")
check(not at.exception, "agent 回答后渲染无异常")
check(any("Agent查证回答" in x for x in [m.value for m in at.markdown]), "agent 回答正文显示")
check(any("已查证" in c.value and "搜索原文" in c.value for c in at.caption),
      "查证步骤（trace）以标题行显示")
check(any("已调用 3 次" in c.value for c in at.caption), "usage.calls 计入会话累计")

doctor_agent.run_doctor_agent = fake_agent_raise
analyzer.ask_doctor = fake_ask_doctor
at.chat_input[0].set_value("再问一次").run()
check(any("单轮兜底回答" in x for x in [m.value for m in at.markdown]),
      "agent 异常 → 单轮兜底回答显示")
check(any("降级单轮" in c.value for c in at.caption), "降级原因写入 note 并显示")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
