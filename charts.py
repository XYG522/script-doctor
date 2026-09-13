"""报告页图表构建（纯函数：输入报告 dict，输出 plotly Figure 或 None）。

角色关系网络图：networkx 力导向布局（spring_layout，固定 seed 保证稳定）+ plotly 渲染。
节点 = 关系涉及的角色（属性取自 characters.cast，缺省为孤儿节点）；边 = 每条关系。

配色随主题：运行时通过 st.context.theme 自动取 light/dark 调色板；
脱离 Streamlit 运行时（单元测试直接调用）固定回退 light 调色板，保证测试确定性。
调色板颜色与 .streamlit/config.toml 保持一致（苹果官网浅色 / 深色双主题）。
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

# 评分雷达图：6 维固定顺序与中文标签
_SCORE_DIMENSIONS = [
    ("character", "角色"),
    ("emotion", "情感"),
    ("pacing", "节奏"),
    ("logic", "逻辑"),
    ("structure", "结构"),
    ("commercial", "商业"),
]

# ---------------------------------------------------------------------------
# 双主题调色板：light = 苹果官网浅色；dark = 苹果官网深色（与 config.toml 一致）
# ---------------------------------------------------------------------------
PALETTES = {
    "light": {
        "protagonist": "#0071E3",    # 主角 / 主色：苹果蓝
        "antagonist": "#FF3B30",     # 反派 / 问题语义：苹果红
        "other": "#8E8E93",          # 其他角色：苹果灰
        "good": "#34C759",           # 正常 / 高置信：苹果绿
        "warn": "#FF9500",           # 中置信：苹果橙
        "edge": "#D2D2D7",           # 正常关系边
        "edge_issue": "#FF3B30",     # 有问题关系边：红虚线
        "score": "#0071E3",          # 雷达线
        "score_fill": "rgba(0, 113, 227, 0.15)",
        "emotion_neutral": "#8E8E93",
        "marker_line": "#FFFFFF",    # 标记描边
        "text": "#6E6E73",
        "grid": "rgba(0, 0, 0, 0.08)",
        "axis": "#D2D2D7",
        "panel": "#FFFFFF",          # 悬停面板
        "hover_text": "#1D1D1F",
        "hline": "#E8E8ED",          # 情感曲线零线
    },
    "dark": {
        "protagonist": "#0A84FF",
        "antagonist": "#FF453A",
        "other": "#98989D",
        "good": "#30D158",
        "warn": "#FF9F0A",
        "edge": "#48484A",
        "edge_issue": "#FF453A",
        "score": "#0A84FF",
        "score_fill": "rgba(10, 132, 255, 0.20)",
        "emotion_neutral": "#98989D",
        "marker_line": "#0D0D0F",
        "text": "#AEAEB2",
        "grid": "rgba(255, 255, 255, 0.08)",
        "axis": "#48484A",
        "panel": "#1D1D1F",
        "hover_text": "#F5F5F7",
        "hline": "#3A3A3C",
    },
}

# 图内统一字体（系统无衬线栈，与 config.toml 一致；不引外部字体，离线可用）
_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
_FALLBACK_THEME = "light"  # 脱离 Streamlit 运行时（单测）→ 固定浅色调色板


def _current_theme() -> str:
    """当前 Streamlit 主题：light / dark。脱离运行时（单测）回退 light。"""
    try:
        from streamlit import context
        return "dark" if context.theme.type == "dark" else "light"
    except Exception:
        return _FALLBACK_THEME


def get_palette(theme: str | None = None) -> dict:
    """按主题名取调色板；None = 自动检测当前运行时主题。"""
    return PALETTES.get(theme or _current_theme(), PALETTES[_FALLBACK_THEME])


def _role_color_map(palette: dict) -> dict:
    return {"protagonist": palette["protagonist"], "antagonist": palette["antagonist"]}


def style_fig(fig, palette: dict | None = None):
    """统一图表样式：透明底 + 系统无衬线字体 + 细网格 + 随主题的悬停面板。

    app.py 的内联图表（角色柱图 / 节奏图 / 对比雷达）也调用本函数保持一致。
    注意：各函数应在调用后再设自己的 height/margin 等布局参数以覆盖默认值。
    """
    p = palette or get_palette()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_FONT, color=p["text"]),
        hoverlabel=dict(bgcolor=p["panel"], bordercolor=p["axis"],
                        font=dict(family=_FONT, color=p["hover_text"])),
    )
    fig.update_xaxes(gridcolor=p["grid"], zerolinecolor=p["grid"], linecolor=p["axis"])
    fig.update_yaxes(gridcolor=p["grid"], zerolinecolor=p["grid"], linecolor=p["axis"])
    return fig


def score_radar(dimensions: dict, palette: dict | None = None):
    """单份报告的评分雷达图（0~100）。

    容错：缺失/非数值的维度跳过（模块勾选后未分析的维度不占轴）；
    全部缺失或 plotly 缺失 → 返回 None（调用方不渲染）。
    """
    if not HAS_PLOTLY:
        return None
    p = palette or get_palette()
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
        line=dict(color=p["score"], width=2),
        fillcolor=p["score_fill"],
        hovertemplate="%{theta}：%{r} 分<extra></extra>",
        showlegend=False,
    ))
    style_fig(fig, p)
    fig.update_layout(
        height=380, margin=dict(l=60, r=60, t=20, b=20),
        polar=dict(radialaxis=dict(range=[0, 100], visible=False),
                   angularaxis=dict(direction="clockwise")),
    )
    return fig


def emotion_curves(emotion_curve: dict, cast: list | None = None, palette: dict | None = None):
    """情感曲线图：按角色拆多条线（最多 3 条）。

    - 旧报告 point 无 character 字段 → 全部归「主角」单线（向后兼容）
    - 颜色：主角=蓝、反派=红、其他角色=灰；>1 条线时显示图例
    - 无数据 / plotly 缺失 → None（调用方显示"无数据"）
    """
    if not HAS_PLOTLY:
        return None
    p = palette or get_palette()
    points = (emotion_curve or {}).get("points") or []
    if not points:
        return None
    role_of = {c.get("name"): c.get("role") for c in (cast or [])}

    tracks: dict[str, list] = {}
    for pt in points:
        name = (pt.get("character") or "").strip() or "主角"
        tracks.setdefault(name, []).append(pt)

    fig = go.Figure()
    for name, pts in tracks.items():
        pts = sorted(pts, key=lambda x: x.get("scene", 0))
        role = role_of.get(name)
        if name == "主角" or role == "protagonist":
            color = p["protagonist"]
        elif role == "antagonist":
            color = p["antagonist"]
        else:
            color = p["emotion_neutral"]
        fig.add_trace(go.Scatter(
            x=[pt.get("scene") for pt in pts],
            y=[pt.get("value", 0) for pt in pts],
            mode="lines+markers", name=name,
            line=dict(color=color, width=2),
            marker=dict(size=8, line=dict(width=2, color=p["marker_line"])),
            customdata=[[pt.get("label", "")] for pt in pts],
            hovertemplate=f"{name} · 第%{{x}}场<br>情感值 %{{y}}<br>%{{customdata[0]}}<extra></extra>",
        ))
    fig.add_hline(y=0, line_dash="dash", line_color=p["hline"], line_width=1)
    fig.update_yaxes(range=[-2.3, 2.3], title="情感值")
    style_fig(fig, p)
    fig.update_layout(
        height=320, margin=dict(t=30, b=10),
        showlegend=len(tracks) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis_title="场次",
    )
    return fig


def scene_length_chart(lengths: list, page_chars: int = 600, palette: dict | None = None):
    """规则硬检查：每场字数柱状图（本地统计，非 LLM）。空数据/plotly 缺失 → None。"""
    if not HAS_PLOTLY or not lengths:
        return None
    p = palette or get_palette()
    fig = go.Figure(go.Bar(
        x=[f"第{i}场" for i in range(1, len(lengths) + 1)],
        y=list(lengths),
        marker_color=p["protagonist"],
        text=[str(v) for v in lengths],
        textposition="outside",
        customdata=[round(v / page_chars, 1) for v in lengths],
        hovertemplate="%{x}：%{y} 字（≈%{customdata} 分钟）<extra></extra>",
    ))
    style_fig(fig, p)
    fig.update_layout(
        height=280, margin=dict(t=20, b=10), showlegend=False,
        yaxis_title="字数（不含空白）",
    )
    return fig


def structure_act_chart(report: dict, palette: dict | None = None):
    """结构体检三幕图：幕色带 + 关键节拍菱形标记（悬停看描述与引用）。

    - 每幕一条横向色带（蓝/绿/橙，按场次范围）；节拍落在所属幕带内，无幕可落时标在顶部
    - 伏笔回收不画图，由 app.py 以清单展示
    - 无幕且无节拍、或 plotly 缺失 → None（调用方显示"无数据"）
    """
    if not HAS_PLOTLY:
        return None
    p = palette or get_palette()
    st = report.get("structure") or {}
    acts = st.get("acts") or []
    beats = st.get("beats") or []
    if not acts and not beats:
        return None

    def _i(v, d=0):
        try:
            return int(v)
        except (TypeError, ValueError):
            return d

    xmax = report.get("script_meta", {}).get("scene_count") or 0
    for a in acts:
        xmax = max(xmax, _i(a.get("scene_end")))
    for b in beats:
        xmax = max(xmax, _i(b.get("scene")))
    if xmax < 1:
        return None

    act_colors = [p["protagonist"], p["good"], p["warn"]]  # 三幕：蓝 / 绿 / 橙
    fig = go.Figure()
    for i, a in enumerate(acts):
        s = max(_i(a.get("scene_start"), 1), 1)
        e = max(_i(a.get("scene_end")), s)
        fig.add_hrect(y0=i, y1=i + 1, x0=s - 0.5, x1=e + 0.5,
                      fillcolor=act_colors[i % len(act_colors)], opacity=0.16, line_width=0)
        fig.add_annotation(
            x=(s + e) / 2, y=i + 0.5,
            text=f"{a.get('name', f'第{_i(a.get('act'), i + 1)}幕')} 第{s}-{e}场",
            showarrow=False, font=dict(size=12, color=p["text"]),
        )
    ymax = max(len(acts), 1)
    for b in beats:
        sc = _i(b.get("scene"))
        if sc < 1:
            continue
        y = ymax - 0.5  # 默认顶部；落在某幕范围内则放入该幕带
        for i, a in enumerate(acts):
            s = max(_i(a.get("scene_start"), 1), 1)
            if s <= sc <= max(_i(a.get("scene_end")), s):
                y = i + 0.5
                break
        tip = f"<b>{b.get('name', '节拍')}</b> · 第{sc}场<br>{b.get('description', '')}"
        ev = b.get("evidence") or {}
        if ev.get("text"):
            tip += f"<br>“{ev['text']}”"
        fig.add_trace(go.Scatter(
            x=[sc], y=[y], mode="markers+text",
            marker=dict(symbol="diamond", size=13, color=p["antagonist"],
                        line=dict(color=p["marker_line"], width=1.5)),
            text=[b.get("name", "")], textposition="top center",
            textfont=dict(size=11, color=p["text"]),
            hovertext=tip, hoverinfo="text", showlegend=False,
        ))
    style_fig(fig, p)
    fig.update_layout(
        showlegend=False, height=130 + 70 * ymax,
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis=dict(dtick=1, range=[0.5, xmax + 0.5], title="场次"),
        yaxis=dict(visible=False, range=[-0.3, ymax + 0.6], fixedrange=True),
    )
    return fig


def relationship_network(report: dict, palette: dict | None = None):
    """把报告的 relationships + characters.cast 转成角色关系力导向网络图。

    - 节点大小 ∝ 出场场次（sqrt 缩放）；颜色 = 角色定位（主角蓝/反派红/其他灰）
    - 边：issues 非空 → 红虚线；否则灰实线
    - 悬停：节点显示定位/出场/叙事功能；边显示类型/走向/问题
    - 容错：pair 里的名字不在 cast 中 → 孤儿节点（灰、默认大小）；
      无关系数据或无可画边 → 返回 None（调用方显示"无数据"）
    """
    rels = report.get("relationships") or []
    if not rels or not HAS_PLOTLY:
        return None
    p = palette or get_palette()
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
            line=dict(color=p["edge_issue"] if has_issue else p["edge"],
                      width=2.5, dash="dot" if has_issue else "solid"),
            text=tip, hoverinfo="text", showlegend=False,
        ))

    role_color = _role_color_map(p)
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
            marker=dict(size=size, color=role_color.get(role, p["other"]),
                        line=dict(color=p["marker_line"], width=1.5)),
            text=name, textposition="top center", textfont=dict(size=11),
            hovertext=tip, hoverinfo="text", showlegend=False,
        ))

    style_fig(fig, p)
    fig.update_layout(
        showlegend=False, height=430, margin=dict(l=20, r=20, t=20, b=20),
        hovermode="closest",
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True, scaleanchor="x", scaleratio=1),
    )
    return fig
