"""AI 剧本体检报告 —— Streamlit 演示应用。

运行：streamlit run app.py
六阶段页面：auth（登录/注册）→ upload（上传）→ running（分析中，带进度）→ report（报告+图表+导出）→ history（我的历史）→ compare（改稿前后对比）。
登录后主界面右上角显示用户名与退出按钮；游客仅可离线演示。
"""
import json
import os

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import analyzer
import auth
import charts
import compare
import hardcheck
import history
from charts import ROLE_LABEL
from llm import get_client, is_valid_key

st.set_page_config(page_title="AI 剧本体检报告", page_icon="🎬", layout="wide")

# ---------------------------------------------------------------------------
# 深色「放映厅」主题 CSS：深炭底 + 骨白字 + 琥珀金强调，衬线标题 + 编号章节
# ---------------------------------------------------------------------------
_CSS = """
<style>
/* ---- 基础：去原生 chrome、暗底、居中窄栏 ---- */
#MainMenu, footer, header[data-testid="stHeader"], [data-testid="stToolbar"],
[data-testid="stDecoration"], [data-testid="stStatusWidget"] {display: none;}
.stApp, [data-testid="stAppViewContainer"] {background: #0E1116; color: #E8E6E1;}
body {font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;}
.block-container {max-width: 1100px; padding-top: 1.2rem; padding-bottom: 5rem; counter-reset: sd-sec;}
::selection {background: rgba(201, 168, 106, 0.3);}
a {color: #C9A86A;}
hr {border-color: #232830;}
::-webkit-scrollbar {width: 8px; height: 8px;}
::-webkit-scrollbar-thumb {background: #2A3038; border-radius: 4px;}
::-webkit-scrollbar-track {background: transparent;}

/* ---- 标题：衬线 + 章节自动编号 ---- */
h1, h2, h3 {font-family: Georgia, "Times New Roman", "Songti SC", "STSong", "SimSun", serif;
            letter-spacing: 0.02em; color: #EDEBE6;}
h1 {font-size: 2rem; font-weight: 700; letter-spacing: 0.05em;}
h3 {counter-increment: sd-sec; border-left: 3px solid #C9A86A; padding-left: 0.6rem;
    font-size: 1.12rem; font-weight: 600;}
h3::before {content: counter(sd-sec, decimal-leading-zero) "  "; color: #C9A86A;
            font-size: 0.82em; letter-spacing: 0.08em;}

/* ---- 顶栏与自定义类 ---- */
.sd-brand {font-family: Georgia, "Times New Roman", serif; letter-spacing: 0.3em;
           font-size: 1rem; font-weight: 700; color: #EDEBE6; white-space: nowrap;
           padding: 0.4rem 0 0.2rem 0;}
.sd-brand .accent {color: #C9A86A;}
.sd-brand-sub {font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
               letter-spacing: 0.16em; font-size: 0.72rem; color: #8B93A1;
               margin-left: 0.6em; font-weight: 400;}
.sd-user {text-align: right; color: #8B93A1; font-size: 0.85rem; padding-top: 0.45rem;
          letter-spacing: 0.04em;}
.sd-appbar-line {border-bottom: 1px solid #232830; margin: 0.2rem 0 1.2rem 0;}
.sd-section-label {font-size: 0.74rem; letter-spacing: 0.3em; color: #C9A86A;
                   text-transform: uppercase; margin: 0 0 0.6rem 0; font-weight: 600;}
.sd-hero-sub {color: #8B93A1; font-size: 0.95rem; line-height: 1.75;}

/* ---- 面板：metric / 带边容器 / expander ---- */
[data-testid="stMetric"] {background: #161A21; border: 1px solid #232830; border-radius: 8px;
                          padding: 0.9rem 1rem 0.75rem 1rem;}
[data-testid="stMetricLabel"] {color: #8B93A1; letter-spacing: 0.1em; font-size: 0.78rem;}
[data-testid="stMetricValue"] {font-family: Georgia, "Songti SC", serif; font-size: 1.5rem;
                               color: #EDEBE6;}
[data-testid="stVerticalBlockBorderWrapper"] {background: #161A21; border: 1px solid #232830;
                                              border-radius: 10px; padding: 1rem 1.1rem;}
[data-testid="stExpander"] {background: transparent; border: 1px solid #232830;
                            border-radius: 8px; overflow: hidden;}
[data-testid="stExpander"] summary {color: #D6D3CC; letter-spacing: 0.04em;}
[data-testid="stExpander"] summary:hover {color: #C9A86A;}

/* ---- 按钮：琥珀主按钮 + 幽灵次按钮 ---- */
[data-testid="stBaseButton-primary"] {background: #C9A86A; color: #12100B;
    border: 1px solid #C9A86A; font-weight: 600; letter-spacing: 0.08em; border-radius: 6px;}
[data-testid="stBaseButton-primary"]:hover {background: #D8BA7E; border-color: #D8BA7E; color: #12100B;}
[data-testid="stBaseButton-secondary"] {background: transparent; border: 1px solid #2A3038;
    color: #C9C6BE; border-radius: 6px; letter-spacing: 0.06em;}
[data-testid="stBaseButton-secondary"]:hover {border-color: #C9A86A; color: #C9A86A;}

/* ---- 表单：暗面板 + 琥珀聚焦环 ---- */
[data-testid="stTextInputRootElement"] input, textarea,
[data-baseweb="select"] > div, [data-testid="stFileUploaderDropzone"] {
    background: #161A21 !important; border-color: #2A3038; color: #E8E6E1; border-radius: 6px;}
[data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stTextAreaRootElement"]:focus-within,
[data-baseweb="select"]:focus-within {box-shadow: 0 0 0 1px #C9A86A; border-radius: 6px;}

/* ---- tabs：下划线琥珀 ---- */
[data-testid="stTabs"] [data-baseweb="tab-list"] {gap: 1.8rem; border-bottom: 1px solid #232830;}
[data-testid="stTabs"] [data-baseweb="tab"] {color: #8B93A1; letter-spacing: 0.06em;
    padding-left: 0.1rem; padding-right: 0.1rem;}
[data-testid="stTabs"] [aria-selected="true"] {color: #C9A86A;}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {background-color: #C9A86A;}

/* ---- 对话区 ---- */
[data-testid="stChatMessage"] {background: #161A21; border: 1px solid #232830;
                               border-radius: 10px; padding: 0.5rem 0.9rem;}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {background: #1A1F27;}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {border-left: 3px solid #C9A86A;}
[data-testid="stChatInput"] {background: #161A21; border: 1px solid #232830; border-radius: 10px;}
[data-testid="stChatInput"] textarea {background: transparent; color: #E8E6E1;}
blockquote {border-left: 2px solid #3A4048; color: #B8BCC4;
            background: rgba(255, 255, 255, 0.02); border-radius: 0 6px 6px 0;
            padding: 0.35rem 0.8rem; margin: 0.4rem 0;}

/* ---- 进度 / 表格 / 提示 ---- */
[data-testid="stProgress"] > div > div > div > div {background: #C9A86A;}
[data-testid="stDataFrame"] {border: 1px solid #232830; border-radius: 8px; overflow: hidden;}
[data-testid="stAlert"] {background: #161A21; border: 1px solid #2A3038; border-radius: 8px;}
[data-testid="stCaptionContainer"] {color: #8B93A1; letter-spacing: 0.02em;}

/* ---- 背景层次：左上角暖光晕 + 平滑滚动 ---- */
.stApp {background: radial-gradient(1100px 520px at 18% -8%, rgba(201, 168, 106, 0.055), transparent 62%), #0E1116;}
html {scroll-behavior: smooth;}

/* ---- 微动效：按钮悬停缩放 / 卡片浮起 / 面板呼吸 ---- */
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondary"],
[data-testid="stDownloadButton"] button, [data-testid="stDownloadButton"] a {
    transition: transform 0.16s ease, box-shadow 0.16s ease,
                background-color 0.16s ease, border-color 0.16s ease, color 0.16s ease;}
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-secondary"]:hover,
[data-testid="stDownloadButton"] button:hover, [data-testid="stDownloadButton"] a:hover {
    transform: translateY(-2px) scale(1.03);}
[data-testid="stBaseButton-primary"]:hover {box-shadow: 0 6px 18px rgba(201, 168, 106, 0.30);}
[data-testid="stBaseButton-secondary"]:hover {box-shadow: 0 4px 14px rgba(0, 0, 0, 0.45);}
[data-testid="stBaseButton-primary"]:active, [data-testid="stBaseButton-secondary"]:active {
    transform: scale(0.97); box-shadow: none;}
[data-testid="stMetric"] {transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;}
[data-testid="stMetric"]:hover {transform: translateY(-3px);
    border-color: rgba(201, 168, 106, 0.45); box-shadow: 0 10px 26px rgba(0, 0, 0, 0.5);}
[data-testid="stVerticalBlockBorderWrapper"] {transition: border-color 0.18s ease;}
[data-testid="stVerticalBlockBorderWrapper"]:hover {border-color: #2E3640;}
[data-testid="stExpander"] {transition: border-color 0.18s ease, background-color 0.18s ease;}
[data-testid="stExpander"]:hover {border-color: #2E3640; background: rgba(255, 255, 255, 0.015);}
[data-testid="stTabs"] [data-baseweb="tab"] {transition: color 0.15s ease, background-color 0.15s ease;}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {color: #D8C9A6; background: rgba(201, 168, 106, 0.06);}

/* ---- 入场动效：淡入 + 上滑（JS 在元素进入视口时补 .sd-in；
     此段放在最后，保证过渡属性覆盖上面的悬停过渡，动画结束后悬停恢复生效） ---- */
h1, h3, [data-testid="stMetric"], [data-testid="stPlotlyChart"],
[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stExpander"],
[data-testid="stDataFrame"], [data-testid="stChatMessage"], [data-testid="stAlert"] {opacity: 0;}
.sd-pre {transform: translateY(18px);
         transition: opacity 0.5s ease var(--sd-d, 0s),
                     transform 0.55s cubic-bezier(0.22, 0.61, 0.36, 1) var(--sd-d, 0s);}
.sd-in {opacity: 1; transform: translateY(0);}
@media (prefers-reduced-motion: reduce) {
  h1, h3, [data-testid="stMetric"], [data-testid="stPlotlyChart"],
  [data-testid="stVerticalBlockBorderWrapper"], [data-testid="stExpander"],
  [data-testid="stDataFrame"], [data-testid="stChatMessage"], [data-testid="stAlert"] {opacity: 1;}
  .sd-pre {transform: none; transition: none;}
}
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

# 滚动入场动效：元素进入视口时淡入上滑。
# 注意：st.markdown 注入的 <script> 不会执行（innerHTML 插入的脚本不运行），
# 必须走 components.html 的 iframe 让脚本真正运行，再通过 window.parent 操作主页面。
_JS = """
<script>
(function () {
  var w = window.parent, doc = w.document;
  var SEL = 'h1,h3,[data-testid="stMetric"],[data-testid="stPlotlyChart"],' +
            '[data-testid="stVerticalBlockBorderWrapper"],[data-testid="stExpander"],' +
            '[data-testid="stDataFrame"],[data-testid="stChatMessage"],[data-testid="stAlert"]';
  var io = w.__sdIO;
  if (!io) {
    io = new w.IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add('sd-in');
          w.setTimeout(function () { e.target.classList.remove('sd-pre'); }, 1000);
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0, rootMargin: '0px 0px -2% 0px' });
    w.__sdIO = io;
  }
  var attach = w.__sdAttach || (w.__sdAttach = function (el) {
    if (!el || el.classList.contains('sd-in')) return;
    var n = w.__sdN || 0;
    if (el.getBoundingClientRect().top < w.innerHeight * 0.98) {
      el.style.setProperty('--sd-d', ((n++ % 6) * 70) + 'ms');
    }
    w.__sdN = n;
    el.classList.add('sd-pre');
    io.observe(el);
  });
  doc.querySelectorAll(SEL).forEach(attach);
  if (!w.__sdMO && doc.body) {
    w.__sdMO = new w.MutationObserver(function (muts) {
      muts.forEach(function (m) {
        m.addedNodes.forEach(function (node) {
          if (node.nodeType !== 1) return;
          if (node.matches && node.matches(SEL)) attach(node);
          if (node.querySelectorAll) node.querySelectorAll(SEL).forEach(attach);
        });
      });
    });
    w.__sdMO.observe(doc.body, { childList: true, subtree: true });
  }
})();
</script>
"""
components.html(_JS, height=0)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEMO_SCRIPT_PATH = os.path.join(BASE_DIR, "demo_script.txt")
DEMO_REPORT_PATH = os.path.join(BASE_DIR, "demo_report.json")

try:
    import plotly.express as px

    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

SEVERITY_STYLE = {"high": "高风险", "medium": "中风险", "low": "低风险"}
VERDICT_COLOR = {"拖沓": "#B3543A", "正常": "#C9A86A", "过快": "#7A828C"}
BAR_COLOR = "#C9A86A"

# ---------------------------------------------------------------------------
# 状态初始化
# ---------------------------------------------------------------------------

if "stage" not in st.session_state:
    st.session_state["stage"] = "auth"
if "user" not in st.session_state:
    st.session_state["user"] = None
if "is_guest" not in st.session_state:
    st.session_state["is_guest"] = False
if "user_id" not in st.session_state:
    st.session_state["user_id"] = None
if "from_history" not in st.session_state:
    st.session_state["from_history"] = False
if "prev_report_id" not in st.session_state:
    st.session_state["prev_report_id"] = None
if "compare_ids" not in st.session_state:
    st.session_state["compare_ids"] = (None, None)
if "script_text" not in st.session_state:
    st.session_state["script_text"] = ""
if "report" not in st.session_state:
    st.session_state["report"] = None
if "warnings" not in st.session_state:
    st.session_state["warnings"] = []
if "modules" not in st.session_state:
    st.session_state["modules"] = list(analyzer.MODULES_R2)
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "chat_usage" not in st.session_state:
    st.session_state["chat_usage"] = {"calls": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0}


def _reset_chat():
    st.session_state["chat_history"] = []
    st.session_state["chat_usage"] = {"calls": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0}


def start_analysis(text: str, prev_report_id=None):
    st.session_state["script_text"] = text
    st.session_state["prev_report_id"] = prev_report_id
    st.session_state["from_history"] = False
    _reset_chat()  # 新报告开启新的对话
    st.session_state["stage"] = "running"
    st.rerun()


def load_offline_demo():
    with open(DEMO_REPORT_PATH, encoding="utf-8") as f:
        report = json.load(f)
    report["meta"]["is_cached_demo"] = True
    st.session_state["report"] = report
    st.session_state["warnings"] = ["离线演示模式：以下为预计算结果，未调用 API。"]
    _reset_chat()
    st.session_state["stage"] = "report"
    st.rerun()


# ---------------------------------------------------------------------------
# 页面零：登录 / 注册
# ---------------------------------------------------------------------------

def _enter_main(username: str, is_guest: bool):
    """登录/注册/游客成功后进入主界面。"""
    st.session_state["user"] = username
    st.session_state["is_guest"] = is_guest
    st.session_state["user_id"] = None if is_guest else auth.get_user_id(username)
    st.session_state["stage"] = "upload"
    # 清空登录表单残留，下次退出回来是空表单
    for k in ("login_username", "login_password", "reg_username", "reg_password", "reg_confirm"):
        st.session_state.pop(k, None)
    st.rerun()


def render_auth_page():
    _, center, _ = st.columns([1, 1.6, 1])
    with center:
        st.markdown(
            '<div class="sd-brand">SCRIPT <span class="accent">DOCTOR</span>'
            '<span class="sd-brand-sub">剧本体检</span></div>',
            unsafe_allow_html=True,
        )
        st.title("AI 剧本体检报告")
        st.markdown(
            '<p class="sd-hero-sub">给剧本做一次「体检」：角色出场分布、角色关系、情感曲线、'
            '节奏分析、逻辑漏洞与动机，以及 3 条可落笔的修改建议。</p>',
            unsafe_allow_html=True,
        )
        tab_login, tab_register = st.tabs(["登录", "注册"])

        with tab_login:
            username = st.text_input("用户名", key="login_username")
            password = st.text_input("密码", type="password", key="login_password")
            if st.button("登录", key="btn_login", type="primary", width="stretch"):
                if not username or not password:
                    st.error("请填写用户名和密码")
                elif auth.verify(username, password):
                    _enter_main(username, is_guest=False)
                else:
                    st.error("用户名或密码错误")

        with tab_register:
            new_username = st.text_input("用户名", key="reg_username",
                                         help="2~20 位字母、数字、下划线或中文")
            new_password = st.text_input("密码", type="password", key="reg_password",
                                         help="至少 6 位")
            confirm = st.text_input("确认密码", type="password", key="reg_confirm")
            if st.button("注册并登录", key="btn_register", type="primary", width="stretch"):
                if new_password != confirm:
                    st.error("两次输入的密码不一致")
                else:
                    ok, msg = auth.register(new_username, new_password)
                    if ok:
                        _enter_main(new_username, is_guest=False)
                    else:
                        st.error(msg)

        st.divider()
        if st.button("游客体验（仅可查看离线演示报告）", key="btn_guest", width="stretch"):
            _enter_main(None, is_guest=True)


# ---------------------------------------------------------------------------
# 右上角用户栏（主界面三个页面共用）
# ---------------------------------------------------------------------------

def render_user_bar():
    is_guest = st.session_state.get("is_guest", False)
    name = "游客" if is_guest else st.session_state.get("user", "?")
    brand_c, user_c, hist_c, logout_c = st.columns([4, 1.6, 1, 1])
    with brand_c:
        st.markdown(
            '<div class="sd-brand">SCRIPT <span class="accent">DOCTOR</span>'
            '<span class="sd-brand-sub">剧本体检</span></div>',
            unsafe_allow_html=True,
        )
    with user_c:
        st.markdown(f'<div class="sd-user">{name}</div>', unsafe_allow_html=True)
    with hist_c:
        if not is_guest and st.button("我的历史", key="btn_history"):
            # 清空表格选中：widget 实例化后不可改其状态，只能在这里（进入历史页之前）清
            st.session_state["hist_table"] = {"selection": {"rows": [], "columns": []}}
            st.session_state["stage"] = "history"
            st.rerun()
    with logout_c:
        if st.button("退出登录" if not is_guest else "退出游客模式", key="btn_logout"):
            st.session_state.update(
                user=None, is_guest=False, stage="auth",
                script_text="", report=None, warnings=[],
                user_id=None, from_history=False,
                prev_report_id=None, compare_ids=(None, None),
                modules=list(analyzer.MODULES_R2),
                chat_history=[], chat_usage={"calls": 0, "cost": 0.0,
                                             "input_tokens": 0, "output_tokens": 0},
            )
            for k in ("login_username", "login_password", "reg_username", "reg_password", "reg_confirm",
                      "prev_version_sel", "cmp_a", "cmp_b", "hist_table"):
                st.session_state.pop(k, None)
            for m in analyzer.MODULES_R2:
                st.session_state.pop(f"mod_{m}", None)
            st.rerun()
    st.markdown('<div class="sd-appbar-line"></div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 页面一：上传
# ---------------------------------------------------------------------------

def render_upload_page():
    st.title("上传剧本")
    if st.session_state.get("is_guest"):
        st.info("游客模式：仅可使用「一键离线演示报告」。注册登录后可使用在线 AI 分析。")
    st.markdown(
        '<p class="sd-hero-sub">给剧本做一次「体检」：角色出场分布、角色关系、情感曲线、'
        '节奏分析、逻辑漏洞与动机，以及 3 条可落笔的修改建议。</p>',
        unsafe_allow_html=True,
    )
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    key_ok = is_valid_key(os.getenv("DEEPSEEK_API_KEY"))
    st.caption(
        f"当前模型：{model} · API Key：{'已设置' if key_ok else '未设置有效 Key（仅可离线演示，设置方法见 README）'}"
    )

    # 左编辑区 + 右控制面板（改稿对比模式 / 分析模块）；游客无面板
    is_guest = st.session_state.get("is_guest", False)
    if is_guest:
        editor_col = st.container()
        panel_col = None
    else:
        editor_col, panel_col = st.columns([2, 1.15], gap="large")

    # 改稿对比模式：登录用户可选「上一版」，分析时把其建议交给 AI 判断是否已落实
    prev_id = None
    if panel_col is not None:
        with panel_col:
            prev_options = {0: "全新分析（不对比上一版）"}
            for r in history.list_reports(st.session_state.get("user_id")):
                prev_options[r["id"]] = f"{r['title']}（{r['created_at']}）"
            prev_id = st.selectbox(
                "改稿对比模式",
                options=list(prev_options.keys()),
                format_func=lambda k: prev_options[k],
                key="prev_version_sel",
            )
            # 分析模块勾选（默认全选；0 个 AI 模块 = 纯免费硬检查）
            with st.container(border=True):
                st.markdown('<div class="sd-section-label">分析模块</div>', unsafe_allow_html=True)
                order = [("characters", "角色分布"), ("relationships", "角色关系"),
                         ("emotion", "情感曲线"), ("pacing", "节奏分析"),
                         ("logic", "逻辑漏洞"), ("commercial", "商业潜力")]
                cols = st.columns(2)
                selected = []
                for i, (mod, label) in enumerate(order):
                    with cols[i % 2]:
                        if st.checkbox(label, value=mod in st.session_state["modules"],
                                       key=f"mod_{mod}"):
                            selected.append(mod)
                st.session_state["modules"] = selected
                st.caption("规则硬检查（对白占比 / 每场字数 / 页数时长）始终免费运行，不占勾选")

    with editor_col:
        tab_paste, tab_file, tab_demo = st.tabs(["粘贴文本", "上传文件", "示例剧本"])

        with tab_paste:
            text = st.text_area("粘贴剧本文本（txt 内容直接粘贴到这里）", height=240, key="paste_area")
            _render_submit(text, "paste", prev_id)

        with tab_file:
            up = st.file_uploader("上传剧本文件（txt / pdf / docx）", type=["txt", "pdf", "docx"])
            ftext = ""
            if up is not None:
                try:
                    ftext = analyzer.load_text(up.getvalue(), up.name)
                    st.success(f"已读取：{up.name}（{len(ftext)} 字）")
                except Exception as e:
                    st.error(f"文件解析失败：{e}")
            _render_submit(ftext, "file", prev_id)

        with tab_demo:
            with open(DEMO_SCRIPT_PATH, encoding="utf-8") as f:
                demo_text = f.read()
            demo_val = st.text_area("内置示例剧本《深夜便利店》（可编辑后再分析）", demo_text, height=240, key="demo_area")
            c1, c2 = st.columns(2)
            if c1.button("用示例剧本在线分析", width="stretch",
                         disabled=st.session_state.get("is_guest", False)):
                start_analysis(demo_val, prev_id)
            if c2.button("一键离线演示报告", width="stretch"):
                load_offline_demo()


def _render_submit(text: str, key_prefix: str, prev_id=None):
    is_guest = st.session_state.get("is_guest", False)
    n = len(text)
    if n > analyzer.CHUNK_THRESHOLD_CHARS:
        st.info(f"文本 {n} 字，超过 2 万字：将启用分块分析模式（长线跨块逻辑检测能力有限）。")
    else:
        st.caption(f"字数：{n}（单次上下文内分析）")
    if not is_guest:
        est = analyzer.estimate_run_cost(text, st.session_state.get("modules", []))
        if est["calls"] == 0:
            st.caption("预估成本：0 次调用 · $0.00（仅运行免费硬检查）")
        else:
            st.caption(
                f"预估成本：{est['calls']} 次调用 · ≈${est['est_cost_usd']:.4f}"
                "（按闲时价估算，实际以账单为准）"
            )
    if st.button(
        "开始分析",
        key=f"btn_{key_prefix}",
        disabled=not text.strip() or is_guest,
        type="primary",
        width="stretch",
    ):
        start_analysis(text, prev_id)


# ---------------------------------------------------------------------------
# 页面二：分析中
# ---------------------------------------------------------------------------

def render_running_page():
    if st.session_state.get("is_guest"):
        # 兜底：游客不应进入分析页（在线分析按钮已禁用），直接送回上传页
        st.session_state["stage"] = "upload"
        st.rerun()
    modules = st.session_state.get("modules", [])
    est = analyzer.estimate_run_cost(st.session_state["script_text"], modules)
    if modules:
        st.subheader(f"分析中（{est['calls']} 次调用：解析 → 并行 {len(modules)} 模块 → 评分建议）")
    else:
        st.subheader("本地硬检查中（不调用 LLM）")
    with st.container(border=True):
        st.markdown('<div class="sd-section-label">分析进度</div>', unsafe_allow_html=True)
        bar = st.progress(0.0)
        status = st.empty()

    def progress_cb(fraction: float, label: str):
        bar.progress(min(max(fraction, 0.0), 1.0))
        status.text(label)

    try:
        client = get_client()
        prev_suggestions = None
        prev_id = st.session_state.get("prev_report_id")
        if prev_id:
            prev_report = history.get_report(st.session_state.get("user_id"), prev_id)
            if prev_report:
                prev_suggestions = prev_report.get("suggestions") or []
        report, warnings = analyzer.run_pipeline(
            st.session_state["script_text"], client, progress_cb,
            prev_suggestions=prev_suggestions, modules=modules,
        )
        if st.session_state.get("user_id") is not None:
            try:
                history.save_report(
                    st.session_state["user_id"],
                    script_excerpt=st.session_state["script_text"],
                    report=report,
                )
            except Exception as e:
                warnings.append(f"历史保存失败：{e}")
        st.session_state["report"] = report
        st.session_state["warnings"] = warnings
        st.session_state["stage"] = "report"
        st.rerun()
    except Exception as e:
        bar.progress(1.0)
        status.empty()
        st.error(f"分析失败：{e}")
        st.info("请检查 DEEPSEEK_API_KEY 与网络后重试；也可以返回使用「一键离线演示报告」。")
        c1, c2 = st.columns(2)
        if c1.button("重试"):
            st.rerun()
        if c2.button("返回上传页"):
            st.session_state["stage"] = "upload"
            st.rerun()


# ---------------------------------------------------------------------------
# 页面三：报告
# ---------------------------------------------------------------------------

def _module_selected(report, module):
    """模块勾选判断：老报告无 modules_selected 字段 → 视同全选。"""
    sel = (report.get("meta") or {}).get("modules_selected")
    if sel is None:
        return True
    return module in sel


def _chart_characters(report):
    if not _module_selected(report, "characters"):
        st.caption("本次未分析该模块（角色分布）")
        return
    st.subheader("角色出场分布")
    cast = report.get("characters", {}).get("cast", [])
    if not cast:
        st.caption("无数据")
        return
    df = pd.DataFrame({
        "角色": [c.get("name") for c in cast],
        "出场场次": [c.get("scene_count", 0) for c in cast],
    })
    if HAS_PLOTLY:
        fig = px.bar(
            df, x="角色", y="出场场次", text="出场场次",
            color_discrete_sequence=[BAR_COLOR],
        )
        fig.update_traces(marker_line_width=0)
        fig.update_layout(height=320, margin=dict(t=10, b=10), showlegend=False,
                          xaxis_title=None, yaxis_title="场次数")
        charts.style_fig(fig)
        st.plotly_chart(fig, width="stretch")
    else:
        st.bar_chart(df.set_index("角色"))


def _chart_emotion(report):
    if not _module_selected(report, "emotion"):
        st.caption("本次未分析该模块（情感曲线）")
        return
    st.subheader("情感曲线")
    fig = charts.emotion_curves(report.get("emotion_curve", {}),
                                report.get("characters", {}).get("cast", []))
    if fig is None:
        st.caption("无数据")
        return
    st.plotly_chart(fig, width="stretch")
    st.caption("情感值：-2 低谷 / -1 低落 / 0 中性 / +1 上扬 / +2 高涨")


def _render_hard_checks(report):
    """报告页：规则硬检查（本地计算，0 成本）。老报告无此节 → 显示无数据。"""
    st.subheader("规则硬检查（本地计算 · 0 成本）")
    hc = report.get("hard_checks")
    if not hc:
        st.caption("无数据（旧版报告未包含硬检查）")
        return
    dia = hc.get("dialogue") or {}
    pt = hc.get("page_time") or {}
    scn = hc.get("scenes") or {}

    c0, c1, c2 = st.columns(3)
    ratio = float(dia.get("ratio", 0) or 0)
    c0.metric("对白占比", f"{ratio * 100:.0f}%")
    c1.metric("预计页数", f"≈ {pt.get('pages', 0)} 页")
    c2.metric("预计片长", f"≈ {pt.get('minutes', 0)} 分钟")
    st.progress(min(max(ratio, 0.0), 1.0))
    st.caption(
        f"对白 {dia.get('chars', 0)} 字 / 全文 {pt.get('chars', 0)} 字（不含空白）"
        f" · 判定：{dia.get('verdict', '—')}"
    )
    st.caption(
        f"页数↔时长：按 {pt.get('page_chars', hardcheck.PAGE_CHARS)} 字/页、1 页 ≈ 1 分钟估算，仅供参考"
    )

    lengths = scn.get("lengths") or []
    if lengths:
        lng = scn.get("longest") or {}
        srt = scn.get("shortest") or {}
        st.markdown(
            f"**每场字数**：{scn.get('count', 0)} 场 · 均值 {scn.get('avg', 0):.0f} 字 · "
            f"中位数 {scn.get('median', 0):.0f} 字 · "
            f"最长 第{lng.get('scene', '—')}场 {lng.get('chars', 0)} 字 · "
            f"最短 第{srt.get('scene', '—')}场 {srt.get('chars', 0)} 字"
        )
        fig = charts.scene_length_chart(lengths)
        if fig is not None:
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        else:
            st.bar_chart(pd.DataFrame({"每场字数": lengths}))
        st.caption(
            f"场次分布判定：{scn.get('verdict', '—')}"
            f"（过长 > {hardcheck.SCENE_TOO_LONG_CHARS} 字 ≈ 3 分钟 · "
            f"过短 ≤ {hardcheck.SCENE_TOO_SHORT_CHARS} 字）"
        )
    for item in scn.get("too_long") or []:
        st.warning(f"第{item.get('scene')}场过长：{item.get('chars')} 字（≈ {item.get('minutes')} 分钟）")
    for item in scn.get("too_short") or []:
        st.warning(f"第{item.get('scene')}场过短：{item.get('chars')} 字")


def _render_chat(report):
    """报告页：剧本医生对话。每问 1 次 LLM 调用，结构化回答 + 引用逐字硬校验。

    不可用场景（不渲染输入框）：游客 / 离线演示 / 从历史打开的旧报告（未存全文）。
    """
    st.divider()
    st.subheader("剧本医生对话")
    if st.session_state.get("is_guest"):
        st.info("游客模式不支持对话（离线演示无 API）。注册登录并在线分析后即可追问。")
        return
    if (report.get("meta") or {}).get("is_cached_demo"):
        st.info("离线演示报告不支持对话（无剧本全文上下文）。在线分析后即可追问。")
        return
    if st.session_state.get("from_history"):
        st.info("旧报告未存全文，暂不支持对话。重新分析该剧本后即可追问。")
        return

    est = analyzer.estimate_chat_cost(
        st.session_state.get("script_text", ""), report, st.session_state["chat_history"], "")
    cu = st.session_state["chat_usage"]
    if cu["calls"]:
        st.caption(f"单问预估 ≈${est['est_cost_usd']:.4f}（按当前上下文） · "
                   f"已问 {cu['calls']} 次 · 累计 ≈${cu['cost']:.4f}（按实际用量）")
    else:
        st.caption(f"单问预估 ≈${est['est_cost_usd']:.4f}"
                   "（按当前上下文与闲时价估算，实际以账单为准）")

    for m in st.session_state["chat_history"]:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            for q in m.get("quotes") or []:
                st.markdown(f"> 引用 · 第 {q.get('scene')} 场：“{q.get('text')}”")
            if m.get("confidence") is not None:
                conf = float(m["confidence"])
                if conf >= 0.8:
                    dot, label = "#8FBC94", "高"
                elif conf >= 0.5:
                    dot, label = "#C9A86A", "中"
                else:
                    dot, label = "#B3543A", "低"
                st.caption(
                    f'置信度 <span style="color:{dot}">●</span> {label} · {conf * 100:.0f}%',
                    unsafe_allow_html=True,
                )
            if m.get("note"):
                st.caption(f"{m['note']}")

    q = st.chat_input("追问剧本相关问题，如：主角的动机在哪一场立起来？")
    if q:
        st.session_state["chat_history"].append({"role": "user", "content": q})
        warn = []
        try:
            data, usage = analyzer.ask_doctor(
                get_client(), st.session_state.get("script_text", ""),
                report, st.session_state["chat_history"], q, warn,
            )
        except Exception as e:
            data, usage = None, None
            warn.append(f"[剧本医生] 调用失败：{e}")
        if usage:
            cost = round(analyzer.DeepSeekClient.estimate_cost(usage), 4)
            st.session_state["chat_usage"]["calls"] += 1
            st.session_state["chat_usage"]["input_tokens"] += usage.get("input_tokens", 0)
            st.session_state["chat_usage"]["output_tokens"] += usage.get("output_tokens", 0)
            st.session_state["chat_usage"]["cost"] = round(
                st.session_state["chat_usage"]["cost"] + cost, 4)
        if data:
            st.session_state["chat_history"].append({
                "role": "assistant",
                "content": data.get("answer") or "（未生成回答）",
                "quotes": data.get("evidence_quotes") or [],
                "confidence": data.get("confidence"),
                "note": "；".join(warn) if warn else "",
            })
        else:
            st.session_state["chat_history"].append({
                "role": "assistant",
                "content": "抱歉，这次回答没有生成成功（调用或校验失败）。请换个问法再试。",
                "quotes": [],
                "confidence": None,
                "note": "；".join(warn) if warn else "",
            })
        st.rerun()


def _chart_pacing(report):
    if not _module_selected(report, "pacing"):
        st.caption("本次未分析该模块（节奏分析）")
        return
    st.subheader("节奏张力（按幕）")
    per_act = report.get("pacing", {}).get("per_act", [])
    if not per_act:
        st.caption("无数据")
        return
    df = pd.DataFrame({
        "幕": [f"第{a.get('act')}幕" for a in per_act],
        "张力": [a.get("tension", 0) for a in per_act],
        "判定": [a.get("verdict", "") for a in per_act],
    })
    if HAS_PLOTLY:
        fig = px.bar(
            df, x="幕", y="张力", color="判定", text="张力",
            color_discrete_map=VERDICT_COLOR,
            category_orders={"判定": ["拖沓", "正常", "过快"]},
        )
        fig.update_traces(marker_line_width=0)
        fig.update_layout(height=320, margin=dict(t=10, b=10),
                          xaxis_title=None, yaxis_title="张力（0~10）")
        charts.style_fig(fig)
        st.plotly_chart(fig, width="stretch")
    else:
        st.bar_chart(df.set_index("幕")["张力"])
    st.caption("拖沓 · 正常 · 过快（判定依据见下方表格）")


def render_report_page():
    report = st.session_state["report"]
    meta = report.get("meta", {})
    if meta.get("is_cached_demo"):
        st.info("离线演示模式：本报告为内置示例剧本的预计算结果，未调用 API。")

    if st.session_state["warnings"]:
        with st.expander(f"{len(st.session_state['warnings'])} 条处理提示 / 校验警告"):
            for w in st.session_state["warnings"]:
                st.caption(str(w))

    sc = report.get("score") or {}
    dims = sc.get("dimensions") or {}
    sm = report.get("script_meta") or {}

    def _dim(v):
        return v if v is not None else "—"

    st.title(f"剧本体检报告 · {sm.get('title', '未命名')}")
    st.caption(
        f"{sm.get('word_count', 0)} 字 · {sm.get('scene_count', 0)} 场 · "
        f"{meta.get('generated_at', '—')} · 模型 {meta.get('model', '—')}"
    )
    hero_col, digest_col = st.columns([1, 2.1], gap="large")
    with hero_col:
        ov = sc.get("overall")
        st.metric("综合评分", f"{ov}/100" if ov is not None else "—",
                  help="AI 参考分，非行业标准评价")
    with digest_col:
        with st.container(border=True):
            st.markdown('<div class="sd-section-label">诊断摘要</div>', unsafe_allow_html=True)
            st.markdown(analyzer.report_digest(report))
    dim_cols = st.columns(5)
    dim_cols[0].metric("角色", _dim(dims.get("character")))
    dim_cols[1].metric("情感", _dim(dims.get("emotion")))
    dim_cols[2].metric("节奏", _dim(dims.get("pacing")))
    dim_cols[3].metric("逻辑", _dim(dims.get("logic")))
    dim_cols[4].metric("商业", _dim(dims.get("commercial")))
    st.caption("评分为 AI 参考意见，非行业标准评价（未勾选的模块不评分）")

    # ---- 图表：两两并排，缩短页长 ----
    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        _chart_characters(report)
    with col_b:
        _chart_emotion(report)
    col_c, col_d = st.columns(2, gap="large")
    with col_c:
        _chart_pacing(report)
    with col_d:
        st.subheader("评分雷达")
        radar = charts.score_radar(dims)
        if radar is not None:
            st.plotly_chart(radar, width="stretch", config={"displayModeBar": False})
        else:
            st.caption("无评分数据")

    # ---- 规则硬检查（本地计算，不调 LLM）----
    _render_hard_checks(report)

    # ---- 角色详情 | 角色关系 ----
    col_cast, col_rel = st.columns(2, gap="large")
    with col_cast:
        with st.expander("角色详情与分布问题", expanded=True):
            if not _module_selected(report, "characters"):
                st.caption("本次未分析该模块")
            else:
                cast = report.get("characters", {}).get("cast", [])
                if cast:
                    rows = [{
                        "角色": c.get("name"),
                        "类型": ROLE_LABEL.get(c.get("role", ""), c.get("role", "")),
                        "出场场次": c.get("scene_count", 0),
                        "叙事功能": c.get("function", ""),
                        "分析": c.get("analysis", ""),
                    } for c in cast]
                    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
                for issue in report.get("characters", {}).get("distribution_issues", []):
                    st.warning(issue)

    with col_rel:
        with st.expander("角色关系"):
            if not _module_selected(report, "relationships"):
                st.caption("本次未分析该模块")
            else:
                rels = report.get("relationships", [])
                if not rels:
                    st.caption("无数据")
                fig = charts.relationship_network(report)
                if fig is not None:
                    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                    st.caption("主角 · 反派 · 其他角色｜圆点大小 = 出场场次｜问题关系为虚线（悬停看详情）")
                for r in rels:
                    pair = r.get("pair", ["?", "?"])
                    st.markdown(f"**{pair[0]} ↔ {pair[1]}**（{r.get('type', '')}）")
                    st.write(f"关系走向：{r.get('trajectory', '')}")
                    for q in r.get("turning_points", []):
                        st.caption(f"第{q.get('scene')}场 · “{q.get('text')}”")
                    if r.get("issues"):
                        st.caption(f"{r['issues']}")
                    st.divider()

    # ---- 逻辑漏洞 ----
    st.subheader("逻辑漏洞与动机问题")
    if not _module_selected(report, "logic"):
        st.caption("本次未分析该模块")
    else:
        holes = report.get("logic", {}).get("holes", [])
        if not holes:
            st.success("未检出明显逻辑问题。")
        for h in holes:
            label = SEVERITY_STYLE.get(h.get("severity"), h.get("severity"))
            with st.expander(f"{label} [{h.get('type')}] {str(h.get('description', ''))[:60]}"):
                st.write(h.get("description"))
                for q in h.get("evidence_quotes", []):
                    st.caption(f"第{q.get('scene')}场 · “{q.get('text')}”")
                conf = float(h.get("confidence", 0))
                st.progress(conf)
                st.caption(f"置信度 {conf} · 依据：{h.get('basis', '')}")
                if h.get("suggestion_hint"):
                    st.caption(f"修复方向：{h['suggestion_hint']}")

    # ---- 修改建议 ----
    st.subheader("3 条可执行修改建议")
    for s in report.get("suggestions", []):
        a = s.get("action") or {}
        with st.container(border=True):
            st.markdown(f"**建议 {s.get('rank')}：{s.get('problem', '')}**")
            st.markdown(f"落点：第 {a.get('scene')} 场 → {a.get('concrete', '')}")
            if s.get("expected_effect"):
                st.caption(f"预期效果：{s['expected_effect']}")
            if s.get("references"):
                st.caption(f"关联：{'、'.join(map(str, s['references']))}")

    # ---- 节奏明细 | 商业潜力 ----
    col_pace, col_mkt = st.columns(2, gap="large")
    with col_pace:
        with st.expander("节奏明细"):
            if not _module_selected(report, "pacing"):
                st.caption("本次未分析该模块")
            else:
                per_act = report.get("pacing", {}).get("per_act", [])
                if per_act:
                    rows = [{
                        "幕": a.get("act"),
                        "张力": a.get("tension"),
                        "判定": a.get("verdict"),
                        "理由": a.get("reason", ""),
                    } for a in per_act]
                    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
                if report.get("pacing", {}).get("overall_verdict"):
                    st.markdown(f"**总体判定：{report['pacing']['overall_verdict']}**")
                for label, key in (("拖沓场次", "dragging_scenes"), ("过快场次", "rushed_scenes")):
                    items = report.get("pacing", {}).get(key, [])
                    for x in items:
                        st.caption(f"{label} · 第{x.get('scene')}场（{x.get('label', '')}）")

    with col_mkt:
        with st.expander("商业潜力与类型元素"):
            if not _module_selected(report, "commercial"):
                st.caption("本次未分析该模块")
            else:
                com = report.get("commercial", {})
                st.markdown(f"**类型元素：**{'、'.join(com.get('genre_elements', [])) or '—'}")
                st.markdown(f"**目标受众：**{com.get('target_audience', '—')}")
                st.markdown(f"**优势：**{'；'.join(com.get('strengths', [])) or '—'}")
                st.markdown(f"**风险：**{'；'.join(com.get('risks', [])) or '—'}")
                if com.get("benchmarks"):
                    st.markdown(f"**风格参考：**{'；'.join(com['benchmarks'])}（仅供参考）")
                conf = float(com.get("confidence", 0))
                st.progress(conf)
                st.caption(f"市场判断置信度：{conf}（无市场数据支撑时上限 0.5）")

    # ---- 导出 ----
    st.divider()
    ec1, ec2, ec3 = st.columns(3)
    ec1.download_button(
        "下载 JSON 报告",
        json.dumps(report, ensure_ascii=False, indent=2),
        file_name="script_report.json",
        mime="application/json",
        width="stretch",
    )
    ec2.download_button(
        "下载 Markdown 报告",
        report_to_markdown(report),
        file_name="script_report.md",
        mime="text/markdown",
        width="stretch",
    )
    if st.session_state.get("from_history"):
        if ec3.button("返回历史", key="btn_back_history", width="stretch"):
            # 清空表格选中：否则回到历史页会被上次的选中再次触发打开
            st.session_state["hist_table"] = {"selection": {"rows": [], "columns": []}}
            st.session_state["stage"] = "history"
            st.rerun()
    else:
        if ec3.button("重新分析其他剧本", width="stretch"):
            st.session_state.update(stage="upload", script_text="", report=None, warnings=[],
                                    from_history=False)
            st.rerun()

    # ---- 运行信息 | 原始 JSON ----
    col_run, col_raw = st.columns(2, gap="large")
    with col_run:
        with st.expander("运行信息（模型 / 耗时 / token / 成本）"):
            st.json({
                "模型": meta.get("model"),
                "分块模式": meta.get("chunked", False),
                "模块勾选": meta.get("modules_selected", "全部（旧版报告）"),
                "预估成本(USD)": (meta.get("est_run") or {}).get("est_cost_usd", "—"),
                "实际成本(USD)": meta.get("est_cost_usd"),
                "总耗时(秒)": meta.get("total_elapsed_sec"),
                "各步耗时(秒)": meta.get("timings", {}),
                "token 统计": meta.get("tokens", {}),
            })
    with col_raw:
        with st.expander("原始 JSON"):
            st.json(report)

    # ---- 剧本医生对话（每问 1 次 LLM 调用，置于页面最底部）----
    _render_chat(report)


def report_to_markdown(report: dict) -> str:
    """把报告转为 Markdown 文本（导出用）。"""
    sm = report.get("script_meta", {})
    sc = report.get("score", {})
    dims = sc.get("dimensions", {})
    L = [f"# 剧本体检报告 · {sm.get('title', '未命名')}", ""]
    ov = sc.get("overall")
    L.append(f"- 综合评分：**{ov}/100**" if ov is not None else "- 综合评分：**—（未评分）**")
    L.append(f"- 篇幅：{sm.get('word_count', 0)} 字 / {sm.get('scene_count', 0)} 场")
    L.append("")
    L.append("## 评分维度")
    L.append("| 维度 | 分数 |\n|---|---|")
    for k, v in dims.items():
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append("## 角色出场分布")
    if not _module_selected(report, "characters"):
        L.append("- 本次未分析该模块")
    else:
        for c in report.get("characters", {}).get("cast", []):
            L.append(f"- **{c.get('name')}**（{c.get('role', '')}）：出场 {c.get('scene_count', 0)} 场 —— {c.get('analysis', '')}")
        for i in report.get("characters", {}).get("distribution_issues", []):
            L.append(f"-{i}")
    L.append("")
    L.append("## 角色关系")
    if not _module_selected(report, "relationships"):
        L.append("- 本次未分析该模块")
    else:
        for r in report.get("relationships", []):
            pair = r.get("pair", ["?", "?"])
            L.append(f"- {pair[0]} ↔ {pair[1]}（{r.get('type', '')}）：{r.get('trajectory', '')}")
            if r.get("issues"):
                L.append(f"  - 问题：{r['issues']}")
    L.append("")
    emo = report.get("emotion_curve", {})
    L.append("## 情感曲线")
    if not _module_selected(report, "emotion"):
        L.append("- 本次未分析该模块")
    else:
        L.append(f"- 判定粒度：{emo.get('granularity', '')}")
        tracks = {}
        for p in emo.get("points", []):
            tracks.setdefault((p.get("character") or "").strip() or "主角", []).append(p)
        for name, pts in tracks.items():
            seq = " → ".join(f"第{p.get('scene')}场 {p.get('value')}（{p.get('label', '')}）" for p in pts)
            L.append(f"- **{name}**：{seq}")
        if emo.get("summary"):
            L.append(f"- 小结：{emo['summary']}")
        for i in emo.get("flatness_issues", []):
            L.append(f"-{i}")
    L.append("")
    pacing = report.get("pacing", {})
    L.append("## 节奏分析")
    if not _module_selected(report, "pacing"):
        L.append("- 本次未分析该模块")
    else:
        L.append("| 幕 | 张力 | 判定 | 理由 |\n|---|---|---|---|")
        for a in pacing.get("per_act", []):
            L.append(f"| 第{a.get('act')}幕 | {a.get('tension')} | {a.get('verdict')} | {a.get('reason', '')} |")
        if pacing.get("overall_verdict"):
            L.append(f"- 总体判定：**{pacing['overall_verdict']}**")
    L.append("")
    hc = report.get("hard_checks")
    if hc:
        dia = hc.get("dialogue") or {}
        pt = hc.get("page_time") or {}
        scn = hc.get("scenes") or {}
        lng, srt = scn.get("longest") or {}, scn.get("shortest") or {}
        L.append("## 规则硬检查（本地计算 · 0 成本）")
        L.append(
            f"- 对白占比：{float(dia.get('ratio', 0) or 0) * 100:.0f}%"
            f"（对白 {dia.get('chars', 0)} 字 / 全文 {pt.get('chars', 0)} 字，不含空白）"
            f"—— 判定：{dia.get('verdict', '')}"
        )
        L.append(
            f"- 每场字数：{scn.get('count', 0)} 场 · 均值 {scn.get('avg', 0):.0f} · "
            f"中位数 {scn.get('median', 0):.0f} · 最长 第{lng.get('scene', '—')}场 {lng.get('chars', 0)} 字 · "
            f"最短 第{srt.get('scene', '—')}场 {srt.get('chars', 0)} 字—— 判定：{scn.get('verdict', '')}"
        )
        for item in scn.get("too_long") or []:
            L.append(f"-第{item.get('scene')}场过长：{item.get('chars')} 字（≈ {item.get('minutes')} 分钟）")
        for item in scn.get("too_short") or []:
            L.append(f"-第{item.get('scene')}场过短：{item.get('chars')} 字")
        L.append(
            f"- 页数↔时长：≈ {pt.get('pages', 0)} 页 / ≈ {pt.get('minutes', 0)} 分钟"
            f"（按 {pt.get('page_chars', 600)} 字/页、1 页 ≈ 1 分钟估算）"
        )
        L.append("")
    L.append("## 逻辑漏洞与动机问题")
    if not _module_selected(report, "logic"):
        L.append("- 本次未分析该模块")
    else:
        holes = report.get("logic", {}).get("holes", [])
        if not holes:
            L.append("未检出明显逻辑问题。")
        for h in holes:
            L.append(f"### [{h.get('severity', '')}] {h.get('id')} · {h.get('type')}（置信度 {h.get('confidence')}）")
            L.append(h.get("description", ""))
            for q in h.get("evidence_quotes", []):
                L.append(f"> 第{q.get('scene')}场：“{q.get('text')}”")
            if h.get("suggestion_hint"):
                L.append(f"建议方向：{h['suggestion_hint']}")
    L.append("")
    L.append("## 3 条可执行修改建议")
    for s in report.get("suggestions", []):
        a = s.get("action") or {}
        L.append(f"### 建议 {s.get('rank')}：{s.get('problem', '')}")
        L.append(f"- 落点：第 {a.get('scene')} 场 → {a.get('concrete', '')}")
        if s.get("expected_effect"):
            L.append(f"- 预期效果：{s['expected_effect']}")
        if s.get("references"):
            L.append(f"- 关联：{'、'.join(map(str, s['references']))}")
    L.append("")
    com = report.get("commercial", {})
    L.append("## 商业潜力")
    if not _module_selected(report, "commercial"):
        L.append("- 本次未分析该模块")
    else:
        L.append(f"- 类型元素：{'、'.join(com.get('genre_elements', [])) or '—'}")
        L.append(f"- 目标受众：{com.get('target_audience', '—')}")
        L.append(f"- 优势：{'；'.join(com.get('strengths', [])) or '—'}")
        L.append(f"- 风险：{'；'.join(com.get('risks', [])) or '—'}")
    L.append("")
    meta = report.get("meta", {})
    L.append("---")
    L.append(f"*模型 {meta.get('model')} · 生成时间 {meta.get('generated_at')} · AI 参考分析，非行业标准评价*")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# 页面四：我的历史
# ---------------------------------------------------------------------------

def render_history_page():
    st.title("我的历史")
    user_id = st.session_state.get("user_id")
    if user_id is None:
        # 兜底：游客不应进入历史页（入口按钮已隐藏），直接送回上传页
        st.session_state["stage"] = "upload"
        st.rerun()
    if st.button("返回上传页", key="btn_hist_back"):
        st.session_state["stage"] = "upload"
        st.rerun()
    records = history.list_reports(user_id)
    if not records:
        st.info("还没有分析记录。去分析一个剧本吧。")
        return
    st.caption(f"共 {len(records)} 条，点击表格行查看完整报告")
    df = pd.DataFrame([{
        "时间": r["created_at"],
        "标题": r["title"],
        "评分": str(r["score"]) if r["score"] is not None else "—",
        "字数": r["word_count"],
        "场次": r["scene_count"],
        "剧本开头": r["script_excerpt"],
    } for r in records])
    event = st.dataframe(
        df, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row", key="hist_table",
    )
    rows = event.selection.get("rows", []) if event is not None else []
    if rows:
        rec = records[rows[0]]
        report = history.get_report(user_id, rec["id"])
        if report is None:
            st.error("该记录已不存在或无法读取")
            return
        # 选中状态的清空在两个「进入历史页」的入口处理
        st.session_state["report"] = report
        st.session_state["warnings"] = []
        st.session_state["from_history"] = True
        _reset_chat()  # 旧报告未存全文，不支持对话
        st.session_state["stage"] = "report"
        st.rerun()

    # ---- 版本对比区 ----
    st.divider()
    st.subheader("版本对比")
    if len(records) < 2:
        st.caption("至少需要 2 条分析记录才能对比")
    else:
        labels = {r["id"]: f"{r['title']}（{r['created_at']}）" for r in records}
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            a_id = st.selectbox("v1（修改前）", options=list(labels.keys()),
                                format_func=lambda k: labels[k], key="cmp_a")
        with c2:
            b_id = st.selectbox("v2（修改后）", options=list(labels.keys()),
                                format_func=lambda k: labels[k], key="cmp_b")
        with c3:
            st.write("")
            if st.button("开始对比", key="btn_compare", width="stretch"):
                if a_id == b_id:
                    st.error("请选择两条不同的记录")
                else:
                    st.session_state["compare_ids"] = (a_id, b_id)
                    st.session_state["stage"] = "compare"
                    st.rerun()


# ---------------------------------------------------------------------------
# 页面五：改稿前后对比
# ---------------------------------------------------------------------------

def _chart_radar(sc1: dict, sc2: dict):
    st.subheader("5 维评分对比")
    labels = ["角色", "情感", "节奏", "逻辑", "商业"]
    keys = ["character", "emotion", "pacing", "logic", "commercial"]
    dims1, dims2 = sc1.get("dimensions") or {}, sc2.get("dimensions") or {}
    rows = [{"维度": lab, "v1": dims1.get(k, 0), "v2": dims2.get(k, 0)} for lab, k in zip(labels, keys)]
    if HAS_PLOTLY:
        import plotly.graph_objects as go

        fig = go.Figure()
        for name, color, vals in (
            ("v1", "#5C6672", [r["v1"] for r in rows]),
            ("v2", BAR_COLOR, [r["v2"] for r in rows]),
        ):
            fig.add_trace(go.Scatterpolar(
                r=vals + [vals[0]], theta=labels + [labels[0]],
                fill="toself", name=name, line_color=color, opacity=0.7,
            ))
        fig.update_layout(
            height=360, margin=dict(t=30, b=30, l=60, r=60),
            polar=dict(radialaxis=dict(range=[0, 100])),
        )
        charts.style_fig(fig)
        st.plotly_chart(fig, width="stretch")
    else:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _render_hole_compare(rep1: dict, rep2: dict):
    st.subheader("漏洞对照")
    h1 = (rep1.get("logic") or {}).get("holes", [])
    h2 = (rep2.get("logic") or {}).get("holes", [])
    result = compare.match_holes(h1, h2)
    status_labels = {"open": "仍存在", "gone": "未检出（可能已修复）", "unknown": "无法判定"}
    rows = []
    for p in result["pairs"]:
        hole = p["v1"]
        rows.append({
            "漏洞": f"{hole.get('id')} · {str(hole.get('description', ''))[:40]}",
            "类型": hole.get("type", ""),
            "严重度": hole.get("severity", ""),
            "状态": status_labels[p["status"]],
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.caption("v1 无漏洞记录")
    if result["new_in_v2"]:
        st.markdown(f"**v2 新增 {len(result['new_in_v2'])} 个漏洞**")
        for h in result["new_in_v2"]:
            st.warning(f"{h.get('id')} · {h.get('type')} · {h.get('description', '')}")
    st.caption("对齐规则：逐字引用共享 ≥1 条 → 同一漏洞；v1 引用在 v2 中消失 → 疑似已修复（模型漏检也会如此，仅供参考）")


def _render_adoption(rep1: dict, rep2: dict):
    st.subheader("v1 建议采纳情况")
    suggs = rep1.get("suggestions") or []
    review_map = {r.get("rank"): r for r in (rep2.get("prev_suggestions_review") or [])}
    if not suggs:
        st.caption("v1 无建议记录")
        return
    for s in suggs:
        a = s.get("action") or {}
        rv = review_map.get(s.get("rank"))
        if rv is None:
            status, note = "无法判定", "v2 分析时未携带 v1 建议"
        else:
            status = "已落实" if rv.get("adopted") else "未落实"
            note = rv.get("note", "")
        st.markdown(f"**{status} 建议 {s.get('rank')}：{s.get('problem', '')}**（落点：第 {a.get('scene')} 场）")
        if note:
            st.caption(f"判断依据：{note}")
        ev = (rv or {}).get("evidence")
        if ev:
            st.caption(f"第{ev.get('scene')}场 · “{ev.get('text')}”")
    if not review_map:
        st.caption("提示：要判断采纳情况，分析 v2 时需在上传页「改稿对比模式」选择上一版。")


def render_compare_page():
    st.title("改稿前后对比")
    if st.button("返回历史", key="btn_cmp_back"):
        st.session_state["stage"] = "history"
        st.rerun()
    user_id = st.session_state.get("user_id")
    a_id, b_id = st.session_state.get("compare_ids", (None, None))
    rep1 = history.get_report(user_id, a_id) if a_id else None
    rep2 = history.get_report(user_id, b_id) if b_id else None
    if rep1 is None or rep2 is None:
        st.error("对比记录不存在或无法读取，请回历史页重新选择")
        return
    sm1, sm2 = rep1.get("script_meta") or {}, rep2.get("script_meta") or {}
    sc1, sc2 = rep1.get("score") or {}, rep2.get("score") or {}
    st.markdown(
        f"**v1**《{sm1.get('title', '未命名')}》（{sm1.get('word_count', 0)} 字）→ "
        f"**v2**《{sm2.get('title', '未命名')}》（{sm2.get('word_count', 0)} 字）"
    )
    ov1, ov2 = sc1.get("overall") or 0, sc2.get("overall") or 0
    c0, c1, c2 = st.columns(3)
    c0.metric("v1 总分", f"{ov1}/100")
    c1.metric("v2 总分", f"{ov2}/100")
    c2.metric("变化", f"{ov2 - ov1:+d}")
    col_radar, col_adopt = st.columns([1.3, 1], gap="large")
    with col_radar:
        _chart_radar(sc1, sc2)
    with col_adopt:
        _render_adoption(rep1, rep2)
    _render_hole_compare(rep1, rep2)
    st.caption("对比为 AI 参考分析；漏洞状态基于引用锚点的规则对齐")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

auth.init_db()
history.init_db()

stage = st.session_state["stage"]
if stage == "auth":
    render_auth_page()
else:
    render_user_bar()
    if stage == "upload":
        render_upload_page()
    elif stage == "running":
        render_running_page()
    elif stage == "report":
        render_report_page()
    elif stage == "history":
        render_history_page()
    elif stage == "compare":
        render_compare_page()
