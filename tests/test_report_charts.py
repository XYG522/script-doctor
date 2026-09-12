"""角色关系网络图回归测试：建图函数单元测试 → 报告页/离线演示的图表渲染。

运行：py tests/test_report_charts.py（在 script-doctor 目录下）
使用临时数据库，不污染真实 users.db；分析管线打桩，不调用 API，可反复运行。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth  # noqa: E402
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


REPORT = {
    "characters": {"cast": [
        {"name": "甲", "role": "protagonist", "first_scene": 1, "scene_count": 9,
         "function": "主线人物", "analysis": "a"},
        {"name": "乙", "role": "antagonist", "first_scene": 1, "scene_count": 1,
         "function": "对立面", "analysis": "b"},
        {"name": "丁", "role": "supporting", "first_scene": 2, "scene_count": 4,
         "function": "帮手", "analysis": "c"},
    ]},
    "relationships": [
        {"pair": ["甲", "乙"], "type": "宿敌", "trajectory": "对抗—和解",
         "turning_points": [], "issues": "动机不足"},
        {"pair": ["甲", "丙"], "type": "同伙", "trajectory": "合作",
         "turning_points": [], "issues": ""},
    ],
}


def node_traces(fig):
    """节点 trace（markers+text），按角色名索引。"""
    return {list(t.text)[0]: t for t in fig.data if t.mode == "markers+text"}


def edge_traces(fig):
    return [t for t in fig.data if t.mode == "lines"]


def chart_contains(els, needle):
    """AppTest 的 plotly 元素：spec 是 JSON 字符串（中文被 \\u 转义），解码后全文搜索。"""
    for el in els:
        try:
            if needle in json.dumps(json.loads(el.proto.spec), ensure_ascii=False):
                return True
        except Exception:
            continue
    return False


# ---- 0. 建图函数单元测试 ----
check(charts.relationship_network({"relationships": []}) is None, "无关系数据返回 None")
check(charts.relationship_network({"relationships": [{"pair": ["甲"], "type": "", "trajectory": ""}]}) is None,
      "pair 不足 2 人（无可画边）返回 None")

fig = charts.relationship_network(REPORT)
check(fig is not None, "正常报告生成图")
nodes = node_traces(fig)
edges = edge_traces(fig)
check(set(nodes) == {"甲", "乙", "丙"}, "节点 = 关系涉及角色（丁未出场于关系 → 不画）")
check(len(edges) == 2, "两对关系 → 两条边")
check(edges[0].line.color == "#B3543A" and edges[0].line.dash == "dot",
      "issues 非空 → 赤陶虚线")
check(edges[1].line.color == "#3A4048" and edges[1].line.dash == "solid",
      "无 issues → 暗灰实线")
check("宿敌" in edges[0].text and "动机不足" in edges[0].text, "边悬停含类型/走向/问题")

dup = charts.relationship_network({
    "relationships": [
        {"pair": ["甲", "乙"], "type": "宿敌", "trajectory": "对抗—和解",
         "turning_points": [], "issues": "动机不足"},
        {"pair": ["甲", "乙"], "type": "宿敌", "trajectory": "对抗—决裂",
         "turning_points": [], "issues": ""},
    ],
})
check(len(edge_traces(dup)) == 1 and edge_traces(dup)[0].line.dash == "solid"
      and "对抗—决裂" in edge_traces(dup)[0].text,
      "重复 pair 合并为一条边（后一条覆盖）")
check(nodes["甲"].marker.color == "#C9A86A", "主角节点 = 琥珀金")
check(nodes["乙"].marker.color == "#B3543A", "反派节点 = 赤陶")
check(nodes["丙"].marker.color == "#7A828C", "未收录角色（孤儿节点）= 图灰")
check("未收录于角色表" in (nodes["丙"].hovertext or ""), "孤儿节点悬停标注「未收录」")
check(nodes["甲"].marker.size > nodes["乙"].marker.size, "出场场次多 → 节点更大")
check("出场：9 场" in (nodes["甲"].hovertext or ""), "节点悬停含出场场次")
check("（主角）" in (nodes["甲"].hovertext or ""), "节点悬停含角色定位")

fig2 = charts.relationship_network(REPORT)
xs = [(t.x[0], t.y[0]) for t in node_traces(fig).values()]
ys = [(t.x[0], t.y[0]) for t in node_traces(fig2).values()]
check(xs == ys, "固定 seed → 两次布局坐标一致")

# ---- 0.5 评分雷达图单元测试 ----
radar = charts.score_radar({"character": 70, "emotion": 60, "pacing": 50, "logic": 40, "commercial": 80})
check(radar is not None, "正常维度生成雷达图")
check(list(radar.data[0].theta) == ["角色", "情感", "节奏", "逻辑", "商业", "角色"], "雷达 5 维标签闭合")
check(list(radar.data[0].r) == [70, 60, 50, 40, 80, 70], "雷达分值闭合且顺序固定")
check(radar.data[0].fill == "toself" and radar.data[0].line.color == "#C9A86A", "雷达填充 + 琥珀金")
single = charts.score_radar({"character": 70})
check(single is not None and list(single.data[0].theta) == ["角色", "角色"]
      and list(single.data[0].r) == [70, 70], "缺失维度直接跳过（单维雷达可渲染）")
check(charts.score_radar({}) is None, "全空维度返回 None")
check(charts.score_radar({"character": "70"}) is None, "非数值维度跳过（全跳过 → None）")

# ---- 0.6 情感曲线（多角色）单元测试 ----
EMO = {
    "granularity": "scene",
    "points": [
        {"scene": 1, "value": -1, "character": "甲", "label": "疲惫"},
        {"scene": 2, "value": 2, "character": "甲", "label": "上扬"},
        {"scene": 1, "value": 0, "character": "乙", "label": "观望"},
        {"scene": 2, "value": -1, "character": "乙", "label": "低落"},
        {"scene": 2, "value": 1, "character": "戊", "label": "转暖"},
        {"scene": 1, "value": 0, "character": "戊", "label": "旁观"},
    ],
}
CAST2 = [
    {"name": "甲", "role": "protagonist"},
    {"name": "乙", "role": "antagonist"},
    {"name": "戊", "role": "supporting"},
]
fig_emo = charts.emotion_curves(EMO, CAST2)
check(fig_emo is not None, "多角色情感曲线生成")
by_name = {t.name: t for t in fig_emo.data}
check(set(by_name) == {"甲", "乙", "戊"}, "三条线齐全")
check(by_name["甲"].line.color == "#C9A86A", "主角线 = 琥珀金")
check(by_name["乙"].line.color == "#B3543A", "反派线 = 赤陶")
check(by_name["戊"].line.color == "#7A828C", "配角线 = 图灰")
check(list(by_name["戊"].x) == [1, 2] and list(by_name["戊"].y) == [0, 1], "每条线按场次排序")
check(fig_emo.layout.showlegend is True, "多线显示图例")
old_emo = charts.emotion_curves(
    {"points": [{"scene": 1, "value": 0}, {"scene": 2, "value": 1}]}, CAST2)
check(len(old_emo.data) == 1 and old_emo.data[0].name == "主角"
      and old_emo.data[0].line.color == "#C9A86A", "旧报告（无 character）归「主角」单线琥珀金")
check(old_emo.layout.showlegend is False, "单线不显示图例")
check(charts.emotion_curves({"points": []}) is None, "空数据返回 None")

# ---- 1. AppTest：报告页渲染关系图 ----
import analyzer  # noqa: E402

FAKE_REPORT = {
    "script_meta": {"title": "关系测试剧本", "word_count": 8, "scene_count": 1, "acts": []},
    "score": {"overall": 77,
              "dimensions": {"character": 7, "emotion": 7, "pacing": 7, "logic": 7, "commercial": 7}},
    "characters": {"cast": [
        {"name": "甲", "role": "protagonist", "first_scene": 1, "scene_count": 5,
         "function": "主线人物", "analysis": "a"},
        {"name": "乙", "role": "antagonist", "first_scene": 1, "scene_count": 3,
         "function": "对立面", "analysis": "b"},
    ], "distribution_issues": []},
    "relationships": [
        {"pair": ["甲", "乙"], "type": "宿敌", "trajectory": "对抗—和解",
         "turning_points": [], "issues": "动机不足"},
    ],
    "emotion_curve": {
        "granularity": "scene",
        "points": [
            {"scene": 1, "value": 1, "character": "甲", "label": "平稳"},
            {"scene": 1, "value": 0, "character": "戊", "label": "旁观"},
        ],
        "summary": "", "flatness_issues": [],
    },
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

auth.register("图表用户", "abc12345")
at = AppTest.from_file(APP, default_timeout=60)
at.run()
check(not at.exception, "首次加载无异常（auth 页）")
at.text_input(key="login_username").set_value("图表用户")
at.text_input(key="login_password").set_value("abc12345")
at.button(key="btn_login").click().run()
at.text_area(key="paste_area").set_value("第1场 关系测试")
at.run()
at.button(key="btn_paste").click().run()
check(not at.exception, "分析（打桩）无异常")
check(at.session_state["stage"] == "report", "进入 report 页")

plotly_els = at.get("plotly_chart")
check(chart_contains(plotly_els, "甲"), "报告页渲染出关系网络图（含角色名）")
check(chart_contains(plotly_els, "动机不足"), "图内边悬停含关系问题")
check(chart_contains(plotly_els, "5 维评分"), "报告页渲染出评分雷达图")
check(chart_contains(plotly_els, "戊"), "报告页情感曲线含第二角色线（戊）")

# ---- 2. AppTest：游客离线演示也渲染关系图 ----
at.button(key="btn_logout").click().run()
at.button(key="btn_guest").click().run()
next(b for b in at.button if "离线演示报告" in b.label).click().run()
check(not at.exception, "离线演示无异常")
check(at.session_state["stage"] == "report", "离线演示进入 report 页")
check(chart_contains(at.get("plotly_chart"), "李薇"), "离线演示报告渲染关系图（含 李薇）")
check(chart_contains(at.get("plotly_chart"), "5 维评分"), "离线演示报告渲染雷达图")
check(chart_contains(at.get("plotly_chart"), "放松打开"), "离线演示情感曲线双线（陈默第3场标签）")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
