"""报告页图表构建（纯函数：输入报告 dict，输出 plotly Figure 或 None）。

角色关系网络图：networkx 力导向布局（spring_layout，固定 seed 保证稳定）+ plotly 渲染。
节点 = 关系涉及的角色（属性取自 characters.cast，缺省为孤儿节点）；边 = 每条关系。
"""
import math

import networkx as nx

try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:  # 与 app.py 一致：plotly 缺失时图表静默降级为"无数据"
    HAS_PLOTLY = False

# 角色定位中文标签（app.py 角色表格共用）
ROLE_LABEL = {"protagonist": "主角", "antagonist": "反派", "supporting": "配角", "minor": "次要角色"}

# 深色「放映厅」双色系：琥珀金主色 + 图灰中性；赤陶仅作问题/反派语义色
_PROTAGONIST_COLOR = "#C9A86A"  # 主角：琥珀金
_ANTAGONIST_COLOR = "#B3543A"   # 反派：赤陶
_OTHER_COLOR = "#7A828C"        # 其他角色：图灰
_EDGE_COLOR = "#3A4048"         # 正常关系边：暗灰实线
_EDGE_ISSUE_COLOR = "#B3543A"   # 有问题关系边：赤陶虚线
_ROLE_COLOR = {"protagonist": _PROTAGONIST_COLOR, "antagonist": _ANTAGONIST_COLOR}

# 评分雷达图：5 维固定顺序与中文标签
_SCORE_DIMENSIONS = [
    ("character", "角色"),
    ("emotion", "情感"),
    ("pacing", "节奏"),
    ("logic", "逻辑"),
    ("commercial", "商业"),
]
_SCORE_COLOR = "#C9A86A"        # 雷达线：琥珀金
_EMOTION_NEUTRAL = "#7A828C"    # 情感曲线第三角色：图灰

# 图内统一暗色样式（不引外部字体，离线可用）
_FONT = "Georgia, 'Songti SC', 'STSong', 'SimSun', serif"
_TEXT_COLOR = "#B8BCC4"
_GRID_COLOR = "rgba(255,255,255,0.06)"
_AXIS_LINE = "#2A3038"
_PANEL_BG = "#161A21"


def style_fig(fig):
    """统一图表暗色样式：透明底 + 衬线字体 + 暗网格 + 深色悬停面板。

    app.py 的内联图表（角色柱图 / 节奏图 / 对比雷达）也调用本函数保持一致。
    注意：各函数应在调用后再设自己的 height/margin 等布局参数以覆盖默认值。
    """
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_FONT, color=_TEXT_COLOR),
        hoverlabel=dict(bgcolor=_PANEL_BG, bordercolor="#2A3038",
                        font=dict(family=_FONT, color="#E8E6E1")),
    )
    fig.update_xaxes(gridcolor=_GRID_COLOR, zerolinecolor=_GRID_COLOR, linecolor=_AXIS_LINE)
    fig.update_yaxes(gridcolor=_GRID_COLOR, zerolinecolor=_GRID_COLOR, linecolor=_AXIS_LINE)
    return fig


def score_radar(dimensions: dict):
    """单份报告的评分雷达图（0~100）。

    容错：缺失/非数值的维度跳过（模块勾选后未分析的维度不占轴）；
    全部缺失或 plotly 缺失 → 返回 None（调用方不渲染）。
    """
    if not HAS_PLOTLY:
        return None
    dims = dimensions or {}
    labels, values = [], []
    for key, zh in _SCORE_DIMENSIONS:
        v = dims.get(key)
        if isinstance(v, (int, float)):
            labels.append(zh)
            values.append(v)
    if not any(values):
        return None
    fig = go.Figure(go.Scatterpolar(
        r=values + [values[0]],
        theta=labels + [labels[0]],
        name=f"{len(labels)} 维评分",
        fill="toself",
        line=dict(color=_SCORE_COLOR, width=2),
        fillcolor="rgba(201, 168, 106, 0.18)",
        hovertemplate="%{theta}：%{r} 分<extra></extra>",
        showlegend=False,
    ))
    style_fig(fig)
    fig.update_layout(
        height=380, margin=dict(l=60, r=60, t=20, b=20),
        polar=dict(radialaxis=dict(range=[0, 100], visible=False),
                   angularaxis=dict(direction="clockwise")),
    )
    return fig


def emotion_curves(emotion_curve: dict, cast: list | None = None):
    """情感曲线图：按角色拆多条线（最多 3 条）。

    - 旧报告 point 无 character 字段 → 全部归「主角」单线（向后兼容）
    - 颜色：主角=琥珀金、反派=赤陶、其他角色=图灰；>1 条线时显示图例
    - 无数据 / plotly 缺失 → None（调用方显示"无数据"）
    """
    if not HAS_PLOTLY:
        return None
    points = (emotion_curve or {}).get("points") or []
    if not points:
        return None
    role_of = {c.get("name"): c.get("role") for c in (cast or [])}

    tracks: dict[str, list] = {}
    for p in points:
        name = (p.get("character") or "").strip() or "主角"
        tracks.setdefault(name, []).append(p)

    fig = go.Figure()
    for name, pts in tracks.items():
        pts = sorted(pts, key=lambda x: x.get("scene", 0))
        role = role_of.get(name)
        if name == "主角" or role == "protagonist":
            color = _PROTAGONIST_COLOR
        elif role == "antagonist":
            color = _ANTAGONIST_COLOR
        else:
            color = _EMOTION_NEUTRAL
        fig.add_trace(go.Scatter(
            x=[p.get("scene") for p in pts],
            y=[p.get("value", 0) for p in pts],
            mode="lines+markers", name=name,
            line=dict(color=color, width=2),
            marker=dict(size=8, line=dict(width=2, color="#0E1116")),
            customdata=[[p.get("label", "")] for p in pts],
            hovertemplate=f"{name} · 第%{{x}}场<br>情感值 %{{y}}<br>%{{customdata[0]}}<extra></extra>",
        ))
    fig.add_hline(y=0, line_dash="dash", line_color="#3A4048", line_width=1)
    fig.update_yaxes(range=[-2.3, 2.3], title="情感值")
    style_fig(fig)
    fig.update_layout(
        height=320, margin=dict(t=30, b=10),
        showlegend=len(tracks) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis_title="场次",
    )
    return fig


def scene_length_chart(lengths: list, page_chars: int = 600):
    """规则硬检查：每场字数柱状图（本地统计，非 LLM）。空数据/plotly 缺失 → None。"""
    if not HAS_PLOTLY or not lengths:
        return None
    fig = go.Figure(go.Bar(
        x=[f"第{i}场" for i in range(1, len(lengths) + 1)],
        y=list(lengths),
        marker_color=_PROTAGONIST_COLOR,
        text=[str(v) for v in lengths],
        textposition="outside",
        customdata=[round(v / page_chars, 1) for v in lengths],
        hovertemplate="%{x}：%{y} 字（≈%{customdata} 分钟）<extra></extra>",
    ))
    style_fig(fig)
    fig.update_layout(
        height=280, margin=dict(t=20, b=10), showlegend=False,
        yaxis_title="字数（不含空白）",
    )
    return fig


def relationship_network(report: dict):
    """把报告的 relationships + characters.cast 转成角色关系力导向网络图。

    - 节点大小 ∝ 出场场次（sqrt 缩放）；颜色 = 角色定位（主角琥珀金/反派赤陶/其他灰）
    - 边：issues 非空 → 赤陶虚线；否则暗灰实线
    - 悬停：节点显示定位/出场/叙事功能；边显示类型/走向/问题
    - 容错：pair 里的名字不在 cast 中 → 孤儿节点（灰、默认大小）；
      无关系数据或无可画边 → 返回 None（调用方显示"无数据"）
    """
    rels = report.get("relationships") or []
    if not rels or not HAS_PLOTLY:
        return None
    cast = {c.get("name"): c for c in (report.get("characters", {}).get("cast") or [])}

    g = nx.Graph()
    for r in rels:
        pair = r.get("pair") or []
        if len(pair) < 2 or not pair[0] or not pair[1]:
            continue
        g.add_node(pair[0])
        g.add_node(pair[1])
        # 同一对角色重复出现时，后一条覆盖前一条（保留最后的关系描述）
        g.add_edge(pair[0], pair[1],
                   type=r.get("type", ""),
                   trajectory=r.get("trajectory", ""),
                   issues=r.get("issues", ""))
    if g.number_of_edges() == 0:
        return None

    # 力导向布局：k 随节点数自适应，seed 固定 → 每次渲染位置稳定
    pos = nx.spring_layout(g, seed=42, k=1.6 / math.sqrt(max(g.number_of_nodes(), 1)))

    fig = go.Figure()
    # 先画边（在下层），再画节点（在上层）
    for u, v, d in g.edges(data=True):
        has_issue = bool((d.get("issues") or "").strip())
        tip = f"<b>{u} ↔ {v}</b><br>{d.get('type', '')}<br>{d.get('trajectory', '')}"
        if has_issue:
            tip += f"<br>问题：{d['issues']}"
        fig.add_trace(go.Scatter(
            x=[pos[u][0], pos[v][0]], y=[pos[u][1], pos[v][1]], mode="lines",
            line=dict(color=_EDGE_ISSUE_COLOR if has_issue else _EDGE_COLOR,
                      width=2.5, dash="dot" if has_issue else "solid"),
            text=tip, hoverinfo="text", showlegend=False,
        ))

    for name in g.nodes():
        c = cast.get(name, {})
        role = c.get("role") or ""
        sc = c.get("scene_count") or 0
        size = min(10 + 8 * math.sqrt(max(sc, 1)), 50)
        label = ROLE_LABEL.get(role, role)
        tip = f"<b>{name}</b>" + (f"（{label}）" if label else "")
        if sc:
            tip += f"<br>出场：{sc} 场"
        if c.get("function"):
            tip += f"<br>{c['function']}"
        elif name not in cast:
            tip += "<br>（未收录于角色表）"
        fig.add_trace(go.Scatter(
            x=[pos[name][0]], y=[pos[name][1]], mode="markers+text",
            marker=dict(size=size, color=_ROLE_COLOR.get(role, _OTHER_COLOR),
                        line=dict(color="#0E1116", width=1.5)),
            text=name, textposition="top center", textfont=dict(size=11),
            hovertext=tip, hoverinfo="text", showlegend=False,
        ))

    style_fig(fig)
    fig.update_layout(
        showlegend=False, height=430, margin=dict(l=20, r=20, t=20, b=20),
        hovermode="closest",
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, scaleanchor="x", scaleratio=1),
    )
    return fig
