"""AI 剧本体检报告 —— Streamlit 演示应用。

运行：streamlit run app.py
六阶段页面：auth（登录/注册）→ upload（上传）→ running（分析中，带进度）→ report（报告+图表+导出）→ history（我的历史）→ compare（改稿前后对比）。
登录后主界面右上角显示用户名与退出按钮；游客仅可离线演示。

视觉：苹果官网风双主题（浅色默认 / 深色可切，见 .streamlit/config.toml，切换入口在右上角 ⋮ → Settings → Theme）。
氛围动效：极光流动背景 + 漂浮粒子 + 进度条流光 + 评分卡呼吸光晕 + 品牌字流光 + 滚动入场淡入上滑。
自定义 CSS 的颜色变量与 config.toml 保持一致，JS 通过读取计算背景色感知明暗主题（Streamlit 主题无公开 DOM 标记）。
"""
import json
import os

import pandas as pd
import streamlit as st

import analyzer
import auth
import charts
import compare
import hardcheck
import history
from charts import ROLE_LABEL
from llm import get_client, is_valid_key

st.set_page_config(page_title="AI 剧本体检报告", page_icon=":material/movie:", layout="wide")

# ---------------------------------------------------------------------------
# 自定义 CSS：苹果官网风双主题 + 氛围动效。
# 颜色一律走上方 CSS 变量（默认浅色，JS 检测实际主题后切换 data-sd-theme），
# 变量值与 .streamlit/config.toml 保持一致；原生主题色由 config.toml 管理。
# ---------------------------------------------------------------------------
_CSS = """
<style>
/* ============================================================
   主题变量（默认浅色；:root[data-sd-theme="dark"] 为深色，由下方 JS 同步）
   ============================================================ */
:root {
  --sd-text: #1D1D1F; --sd-text-2: #6E6E73;
  --sd-card: #FFFFFF; --sd-bg: #F5F5F7;
  --sd-accent: #0071E3; --sd-accent-2: #AF52DE; --sd-accent-3: #5AC8FA;
  --sd-accent-soft: rgba(0, 113, 227, 0.12);
  --sd-border: #D2D2D7; --sd-hairline: rgba(0, 0, 0, 0.06);
  --sd-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
  --sd-shadow-hover: 0 14px 34px rgba(0, 0, 0, 0.10);
  --sd-glow: 0 10px 30px rgba(0, 113, 227, 0.22);
  --sd-aurora-1: rgba(0, 113, 227, 0.20); --sd-aurora-2: rgba(175, 82, 222, 0.15);
  --sd-aurora-3: rgba(255, 45, 85, 0.10); --sd-aurora-4: rgba(90, 200, 250, 0.16);
  --sd-particle: rgba(0, 113, 227, 0.45);
  --sd-scrollbar: #C7C7CC;
}
:root[data-sd-theme="dark"] {
  --sd-text: #F5F5F7; --sd-text-2: #AEAEB2;
  --sd-card: #1D1D1F; --sd-bg: #0D0D0F;
  --sd-accent: #2997FF; --sd-accent-2: #BF5AF2; --sd-accent-3: #64D2FF;
  --sd-accent-soft: rgba(41, 151, 255, 0.16);
  --sd-border: #424245; --sd-hairline: rgba(255, 255, 255, 0.09);
  --sd-shadow: 0 2px 10px rgba(0, 0, 0, 0.45);
  --sd-shadow-hover: 0 16px 38px rgba(0, 0, 0, 0.60);
  --sd-glow: 0 10px 32px rgba(41, 151, 255, 0.30);
  --sd-aurora-1: rgba(10, 132, 255, 0.18); --sd-aurora-2: rgba(191, 90, 242, 0.14);
  --sd-aurora-3: rgba(255, 55, 95, 0.10); --sd-aurora-4: rgba(100, 210, 255, 0.12);
  --sd-particle: rgba(41, 151, 255, 0.50);
  --sd-scrollbar: #48484A;
}

/* ---------- 去原生 chrome（保留右上角 ⋮ 菜单：双主题切换入口在 Settings） ---------- */
footer, [data-testid="stDecoration"], [data-testid="stStatusWidget"] {display: none;}
.stApp {isolation: isolate;  /* 建立层叠上下文：极光/粒子伪元素（负 z-index）画在
                              主题底色之上、内容之下。不覆盖 .stApp 颜色与背景：
                              文字色用 Streamlit 主题色（永远与主题一致、可读），
                              背景色是 JS 明暗检测源 */}
[data-testid="stAppViewContainer"] {background: transparent;}
.block-container {max-width: 1100px; padding-top: 1.6rem; padding-bottom: 6rem; counter-reset: sd-sec;}
::selection {background: var(--sd-accent-soft);}
a {color: var(--sd-accent);}
hr {border-color: var(--sd-hairline);}
::-webkit-scrollbar {width: 8px; height: 8px;}
::-webkit-scrollbar-thumb {background: var(--sd-scrollbar); border-radius: 4px;}
::-webkit-scrollbar-track {background: transparent;}

/* ---------- 标题：无衬线 + 章节自动编号 ---------- */
h1, h2, h3 {color: var(--sd-text); letter-spacing: -0.01em;}
h1 {font-size: 2.4rem; font-weight: 700; letter-spacing: -0.02em;}
h3 {counter-increment: sd-sec; font-size: 1.15rem; font-weight: 600; letter-spacing: -0.005em;}
h3::before {content: counter(sd-sec, decimal-leading-zero); color: var(--sd-accent);
            font-size: 0.8em; letter-spacing: 0.06em; margin-right: 0.45rem; font-weight: 700;}

/* ---------- 品牌栏：流光渐变字 ---------- */
.sd-brand {font-weight: 800; letter-spacing: 0.14em; font-size: 1.05rem; white-space: nowrap;
           padding: 0.4rem 0 0.2rem 0;
           background: linear-gradient(92deg, var(--sd-accent), var(--sd-accent-2) 45%,
                                       var(--sd-accent-3) 70%, var(--sd-accent));
           background-size: 220% auto;
           -webkit-background-clip: text; background-clip: text; color: transparent;
           animation: sd-sheen 7s linear infinite;}
@keyframes sd-sheen {to {background-position: 220% center;}}
.sd-brand-sub {letter-spacing: 0.18em; font-size: 0.72rem; color: var(--sd-text-2);
               margin-left: 0.6em; font-weight: 400;}
@supports not ((-webkit-background-clip: text) or (background-clip: text)) {
  .sd-brand {background: none; color: var(--sd-accent);}  /* 兜底：不支持渐变字时用纯色 */
}
.sd-user {text-align: right; color: var(--sd-text-2); font-size: 0.85rem; padding-top: 0.45rem;}
.sd-appbar-line {border-bottom: 1px solid var(--sd-hairline); margin: 0.2rem 0 1.4rem 0;}
.sd-section-label {font-size: 0.72rem; letter-spacing: 0.28em; color: var(--sd-accent);
                   text-transform: uppercase; margin: 0 0 0.6rem 0; font-weight: 700;}
.sd-hero-sub {color: var(--sd-text-2); font-size: 0.95rem; line-height: 1.8;}

/* ---------- 卡片：白底（深色下深灰底）+ 轻阴影 ---------- */
[data-testid="stMetric"] {background: var(--sd-card); color: var(--sd-text);
                          border: 1px solid var(--sd-border);
                          border-radius: 14px; padding: 1rem 1.1rem 0.9rem;
                          box-shadow: var(--sd-shadow);}
[data-testid="stMetricLabel"] {color: var(--sd-text-2); letter-spacing: 0.06em; font-size: 0.8rem;}
[data-testid="stMetricValue"] {color: var(--sd-text); font-weight: 700;}
/* 卡片容器：st.container(border=True) 在 1.63 渲染为 [data-testid="stColumn"]（无独立
   testid，且与 st.columns 共用），因此按容器 key 定位——app.py 中所有带边框容器
   统一 key="sd-card-*"，st-key 类可能落在容器包装层或卡片层，两个选择器都覆盖 */
[class*="st-key-sd-card"] [data-testid="stColumn"],
[data-testid="stColumn"][class*="st-key-sd-card"] {
    background: var(--sd-card); color: var(--sd-text);
    border: 1px solid var(--sd-border); border-radius: 14px;
    padding: 1.1rem 1.2rem; box-shadow: var(--sd-shadow);
    transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;}
[data-testid="stExpander"] {background: transparent; border: 1px solid var(--sd-border);
                            border-radius: 12px; overflow: hidden;}
[data-testid="stExpander"] summary {color: var(--sd-text);}
[data-testid="stExpander"] summary:hover {color: var(--sd-accent);}

/* 综合评分主卡：呼吸光晕（st.container(key="sd-card-score")） */
.st-key-sd-card-score [data-testid="stColumn"] {animation: sd-breathe 4.5s ease-in-out infinite;}
.st-key-sd-card-score [data-testid="stMetric"] {background: transparent; border: none;
                                                box-shadow: none; padding: 0.5rem 0.2rem 0.6rem;}
@keyframes sd-breathe {
  0%, 100% {box-shadow: var(--sd-shadow);}
  50% {box-shadow: var(--sd-glow);}
}

/* ---------- 按钮：1.63 统一为 [data-testid="stButton"]（主/次配色与胶囊形由
   config.toml 主题 primaryColor + buttonRadius 呈现），这里只补字重与微交互 ---------- */
[data-testid="stButton"] button {font-weight: 600; letter-spacing: 0.02em;}
[data-testid="stButton"], [data-testid="stDownloadButton"] {
    transition: transform 0.18s ease, filter 0.18s ease;}
[data-testid="stButton"]:hover, [data-testid="stDownloadButton"]:hover {
    transform: translateY(-2px) scale(1.02); filter: brightness(1.06);}
[data-testid="stButton"]:active, [data-testid="stDownloadButton"]:active {transform: scale(0.97);}

/* ---------- 表单：卡片底 + 柔和聚焦环（1.63 已无 data-baseweb，全部按 testid 定位；
   下拉框配色由主题原生呈现） ---------- */
[data-testid="stTextInputRootElement"] input,
[data-testid="stTextAreaRootElement"] textarea,
[data-testid="stFileUploaderDropzone"] {
    background: var(--sd-card) !important; border-color: var(--sd-border);
    color: var(--sd-text); border-radius: 10px;}
[data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stTextAreaRootElement"]:focus-within,
[data-testid="stSelectbox"]:focus-within {box-shadow: 0 0 0 3px var(--sd-accent-soft); border-radius: 10px;}

/* ---------- tabs：1.63 自研实现（无 data-baseweb），选中态走 aria-selected，
   下划线高亮由主题 primaryColor 自动呈现 ---------- */
[data-testid="stTab"] {color: var(--sd-text-2); transition: color 0.15s ease;}
[data-testid="stTab"]:hover {color: var(--sd-accent);}
[data-testid="stTabs"] [aria-selected="true"] {color: var(--sd-accent);}

/* ---------- 对话区 ---------- */
[data-testid="stChatMessage"] {background: var(--sd-card); color: var(--sd-text);
                               border: 1px solid var(--sd-border);
                               border-radius: 14px; padding: 0.5rem 0.9rem;
                               box-shadow: var(--sd-shadow);}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {border-color: var(--sd-accent-soft);}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {border-left: 3px solid var(--sd-accent);}
[data-testid="stChatInput"] {background: var(--sd-card); border: 1px solid var(--sd-border); border-radius: 14px;}
[data-testid="stChatInput"] textarea {background: transparent; color: var(--sd-text);}
blockquote {border-left: 2px solid var(--sd-accent-soft); color: var(--sd-text-2);
            background: var(--sd-hairline); border-radius: 0 8px 8px 0;
            padding: 0.35rem 0.8rem; margin: 0.4rem 0;}

/* ---------- 进度条：渐变流光（1.63 填充层 = stProgressBarTrack 的子 div） ---------- */
[data-testid="stProgressBarTrack"] > div {
    background: linear-gradient(90deg, var(--sd-accent), var(--sd-accent-3), var(--sd-accent));
    background-size: 200% 100%;
    animation: sd-shimmer 2.4s linear infinite;}
@keyframes sd-shimmer {to {background-position: -200% 0;}}

/* ---------- 表格 / 提示 ---------- */
[data-testid="stDataFrame"] {border: 1px solid var(--sd-border); border-radius: 12px; overflow: hidden;}
[data-testid="stAlert"] {background: var(--sd-card); color: var(--sd-text);
                         border: 1px solid var(--sd-border);
                         border-radius: 12px; box-shadow: var(--sd-shadow);}
[data-testid="stCaptionContainer"] {color: var(--sd-text-2);}

/* ---------- 氛围背景：纯 CSS 伪元素（不依赖任何 JS 注入，必然生效）。
     .stApp 的 isolation 使负 z-index 层画在主题底色之上、内容之下 ---------- */
.stApp::before {  /* 极光光晕：4 团柔光缓慢漂移 */
  content: ""; position: fixed; inset: 0; z-index: -2; pointer-events: none;
  background:
    radial-gradient(640px 640px at 10% -10%, var(--sd-aurora-1), transparent 65%),
    radial-gradient(520px 520px at 94% 22%, var(--sd-aurora-2), transparent 65%),
    radial-gradient(580px 580px at 24% 108%, var(--sd-aurora-3), transparent 65%),
    radial-gradient(480px 480px at 60% -8%, var(--sd-aurora-4), transparent 65%);
  background-size: 150% 150%;
  background-position: 0% 0%, 100% 100%, 20% 0%, 0% 100%;
  animation: sd-aurora-pan 34s ease-in-out infinite alternate;
  will-change: background-position;
}
@keyframes sd-aurora-pan {
  to {background-position: 100% 100%, 0% 0%, 80% 100%, 100% 0%;}
}
.stApp::after {  /* 漂浮粒子：box-shadow 星点整体上浮淡隐 */
  content: ""; position: fixed; top: 0; left: 0; width: 6px; height: 6px;
  z-index: -1; pointer-events: none; border-radius: 50%;
  background: transparent;
  box-shadow:
    6vw 18vh 0 1px var(--sd-particle), 14vw 64vh 0 0 var(--sd-particle),
    23vw 34vh 0 2px var(--sd-particle), 33vw 78vh 0 0 var(--sd-particle),
    42vw 12vh 0 0 var(--sd-particle), 52vw 55vh 0 1px var(--sd-particle),
    61vw 26vh 0 0 var(--sd-particle), 70vw 70vh 0 2px var(--sd-particle),
    78vw 40vh 0 0 var(--sd-particle), 86vw 14vh 0 1px var(--sd-particle),
    93vw 58vh 0 0 var(--sd-particle), 10vw 88vh 0 1px var(--sd-particle);
  opacity: 0.55;
  animation: sd-particles 26s ease-in-out infinite alternate;
}
@keyframes sd-particles {to {transform: translateY(-42px); opacity: 0.18;}}

html {scroll-behavior: smooth;}

/* ---------- 微动效：卡片浮起 / 面板 hover（按钮 hover 见上方按钮区） ---------- */
[class*="st-key-sd-card"] [data-testid="stColumn"]:hover,
[data-testid="stColumn"][class*="st-key-sd-card"]:hover {
    transform: translateY(-2px); box-shadow: var(--sd-shadow-hover);}
[data-testid="stMetric"] {transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;}
[data-testid="stMetric"]:hover {transform: translateY(-3px); border-color: var(--sd-accent-soft);
    box-shadow: var(--sd-shadow-hover);}
[data-testid="stExpander"] {transition: border-color 0.18s ease, box-shadow 0.18s ease;}
[data-testid="stExpander"]:hover {border-color: var(--sd-accent-soft);}

/* ---------- 入场动效：淡入 + 上滑（JS 在元素进入视口时补 .sd-in；
     此段放在最后，保证过渡属性覆盖上面的悬停过渡，动画结束后悬停恢复生效）
     保险丝：JS 万一失效（任何原因），2.5 秒后动画兜底恢复可见——内容永不永久隐藏 ---------- */
@keyframes sd-failsafe {to {opacity: 1;}}
h1:not(.sd-in), h3:not(.sd-in), [data-testid="stMetric"]:not(.sd-in),
[data-testid="stPlotlyChart"]:not(.sd-in),
[class*="st-key-sd-card"]:not(.sd-in),
[data-testid="stExpander"]:not(.sd-in), [data-testid="stDataFrame"]:not(.sd-in),
[data-testid="stChatMessage"]:not(.sd-in), [data-testid="stAlert"]:not(.sd-in) {
  opacity: 0;
  animation: sd-failsafe 0.4s ease 2.5s forwards;}
.sd-pre {transform: translateY(18px);
         transition: opacity 0.55s ease var(--sd-d, 0s),
                     transform 0.6s cubic-bezier(0.22, 0.61, 0.36, 1) var(--sd-d, 0s);
         animation: none !important;}
.sd-in {opacity: 1; transform: translateY(0);}

/* ---------- 减弱动态效果偏好：动效全部冻结，但氛围背景保持可见（静态） ---------- */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {animation-duration: 0.01ms !important;
                          animation-iteration-count: 1 !important;
                          transition-duration: 0.01ms !important;
                          scroll-behavior: auto !important;}
  h1, h3, [data-testid="stMetric"], [data-testid="stPlotlyChart"],
  [class*="st-key-sd-card"], [data-testid="stExpander"],
  [data-testid="stDataFrame"], [data-testid="stChatMessage"], [data-testid="stAlert"] {
      opacity: 1; animation: none;}
  .sd-pre {transform: none; transition: none; animation: none;}
}
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

# 页面脚本（st.html 直接在主文档执行，不再是 iframe）：
# 1) 主题同步：Streamlit 主题无公开 DOM 标记/事件。优先读 .stApp 计算背景色亮度
#    （透明/未知时退回 CSS color-scheme，再退回浅色），设置 <html data-sd-theme>
#    切换变量；在 class/style 变化、head 插入样式时重测；
# 2) 入场动效：元素进入视口时淡入上滑（window 守卫避免重复观察器）。
# 氛围背景（极光/粒子）已改为纯 CSS 伪元素，不依赖 JS。
_JS = """
<script>
(function () {
  /* ---- 主题同步 ---- */
  function lumOf(el) {
    var c = getComputedStyle(el).backgroundColor || '';
    if (c === 'transparent' || c.indexOf('rgba(0, 0, 0, 0)') >= 0) return null;
    var m = c.match(/[\\d.]+/g);
    if (!m || m.length < 3) return null;
    return 0.2126 * (+m[0]) + 0.7152 * (+m[1]) + 0.0722 * (+m[2]);
  }
  function readTheme() {
    var el = document.querySelector('.stApp') || document.body;
    var lum = lumOf(el);
    if (lum !== null) return lum < 110 ? 'dark' : 'light';
    var cs = (getComputedStyle(el).colorScheme || 'normal').toLowerCase();
    return (cs === 'dark' || cs === 'light') ? cs : 'light';
  }
  function syncTheme() {
    document.documentElement.dataset.sdTheme = readTheme();
  }
  syncTheme();
  setTimeout(syncTheme, 350);   // 首帧样式就绪后再测
  setTimeout(syncTheme, 1200);  // 慢加载兜底再测
  window.addEventListener('load', syncTheme);

  /* ---- 滚动入场动效（每个重渲染只创建一次观察器，由它接管后续新增元素） ---- */
  if (!window.__sdAnims) {
    window.__sdAnims = true;
    var SEL = 'h1,h3,[data-testid="stMetric"],[data-testid="stPlotlyChart"],' +
              '[class*="st-key-sd-card"],[data-testid="stExpander"],' +
              '[data-testid="stDataFrame"],[data-testid="stChatMessage"],[data-testid="stAlert"]';
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add('sd-in');
          setTimeout(function () { e.target.classList.remove('sd-pre'); }, 1000);
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0, rootMargin: '0px 0px -2% 0px' });
    function attach(el) {
      if (!el || el.classList.contains('sd-in') || el.classList.contains('sd-pre')) return;
      var n = window.__sdN || 0;
      if (el.getBoundingClientRect().top < window.innerHeight * 0.98) {
        el.style.setProperty('--sd-d', ((n++ % 6) * 70) + 'ms');
      }
      window.__sdN = n;
      el.classList.add('sd-pre');
      io.observe(el);
    }
    document.querySelectorAll(SEL).forEach(attach);
    var mo = new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        m.addedNodes.forEach(function (node) {
          if (node.nodeType !== 1) return;
          if (node.matches && node.matches(SEL)) attach(node);
          if (node.querySelectorAll) node.querySelectorAll(SEL).forEach(attach);
        });
      });
    });
    mo.observe(document.body, { childList: true, subtree: true });
  }

  /* ---- 主题切换监听：class/style 变化与 head 插入样式时重测 ---- */
  var obs = new MutationObserver(syncTheme);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style'] });
  obs.observe(document.body, { attributes: true, attributeFilter: ['class', 'style'] });
  obs.observe(document.head, { childList: true });
})();
</script>
"""
st.html(_JS, unsafe_allow_javascript=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEMO_SCRIPT_PATH = os.path.join(BASE_DIR, "demo_script.txt")
DEMO_SCRIPT_V2_PATH = os.path.join(BASE_DIR, "demo_script_v2.txt")
DEMO_REPORT_PATH = os.path.join(BASE_DIR, "demo_report.json")
DEMO_REPORT_V2_PATH = os.path.join(BASE_DIR, "demo_report_v2.json")

try:
    import plotly.express as px

    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

SEVERITY_STYLE = {"high": "高风险", "medium": "中风险", "low": "低风险"}
# 图表语义色：随 Streamlit 明暗主题自动切换（charts.py 调色板，与 config.toml 一致）
_PAL = charts.get_palette()
VERDICT_COLOR = {"拖沓": _PAL["antagonist"], "正常": _PAL["good"], "过快": _PAL["other"]}
BAR_COLOR = _PAL["protagonist"]

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


def load_offline_demo(version: int = 1):
    """加载离线演示报告。version=1 修改前；version=2 修改后（改稿闭环演示）。"""
    path = DEMO_REPORT_PATH if version == 1 else DEMO_REPORT_V2_PATH
    with open(path, encoding="utf-8") as f:
        report = json.load(f)
    report["meta"]["is_cached_demo"] = True
    st.session_state["report"] = report
    st.session_state["demo_version"] = version
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
            '<div class="sd-brand" style="text-align:center">SCRIPT DOCTOR'
            '<span class="sd-brand-sub">剧本体检</span></div>',
            unsafe_allow_html=True,
        )
        st.title("AI 剧本体检报告", icon=":material/movie:", text_alignment="center")
        st.markdown(
            '<p class="sd-hero-sub" style="text-align:center">给剧本做一次「体检」：角色出场分布、角色关系、情感曲线、'
            '节奏分析、逻辑漏洞与动机，以及 3 条可落笔的修改建议。</p>',
            unsafe_allow_html=True,
        )
        tab_login, tab_register = st.tabs(["登录", "注册"])

        with tab_login:
            username = st.text_input("用户名", key="login_username")
            password = st.text_input("密码", type="password", key="login_password")
            if st.button("登录", key="btn_login", type="primary", width="stretch",
                         icon=":material/login:"):
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
            if st.button("注册并登录", key="btn_register", type="primary", width="stretch",
                         icon=":material/person_add:"):
                if new_password != confirm:
                    st.error("两次输入的密码不一致")
                else:
                    ok, msg = auth.register(new_username, new_password)
                    if ok:
                        _enter_main(new_username, is_guest=False)
                    else:
                        st.error(msg)

        st.divider()
        if st.button("游客体验（仅可查看离线演示报告）", key="btn_guest", width="stretch",
                     icon=":material/visibility:"):
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
            '<div class="sd-brand">SCRIPT DOCTOR'
            '<span class="sd-brand-sub">剧本体检</span></div>',
            unsafe_allow_html=True,
        )
    with user_c:
        st.markdown(f'<div class="sd-user">{name}</div>', unsafe_allow_html=True)
    with hist_c:
        if not is_guest and st.button("我的历史", key="btn_history", icon=":material/history:"):
            # 清空表格选中：widget 实例化后不可改其状态，只能在这里（进入历史页之前）清
            st.session_state["hist_table"] = {"selection": {"rows": [], "columns": []}}
            st.session_state["stage"] = "history"
            st.rerun()
    with logout_c:
        if st.button("退出登录" if not is_guest else "退出游客模式", key="btn_logout",
                     icon=":material/logout:"):
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
    st.title("上传剧本", icon=":material/edit_note:")
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
            with st.container(border=True, key="sd-card-modules"):
                st.markdown('<div class="sd-section-label">分析模块</div>', unsafe_allow_html=True)
                order = [("characters", "角色分布"), ("relationships", "角色关系"),
                         ("emotion", "情感曲线"), ("pacing", "节奏分析"),
                         ("logic", "逻辑漏洞"), ("structure", "结构体检"),
                         ("commercial", "商业潜力")]
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
            if c1.button("用示例剧本在线分析", width="stretch", icon=":material/auto_awesome:",
                         disabled=st.session_state.get("is_guest", False)):
                start_analysis(demo_val, prev_id)
            if c2.button("一键离线演示报告", width="stretch", icon=":material/offline_bolt:"):
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
        icon=":material/play_arrow:",
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
    with st.container(border=True, key="sd-card-progress"):
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
        if c1.button("重试", icon=":material/refresh:"):
            st.rerun()
        if c2.button("返回上传页", icon=":material/arrow_back:"):
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
                    dot, label = _PAL["good"], "高"
                elif conf >= 0.5:
                    dot, label = _PAL["warn"], "中"
                else:
                    dot, label = _PAL["antagonist"], "低"
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
        # 改稿闭环演示：v1（修改前）↔ v2（修改后）一键切换（仅离线演示用）
        if st.session_state.get("demo_version", 1) == 1:
            st.info("离线演示模式：本报告为内置示例剧本《深夜便利店》的预计算结果，未调用 API。")
            if st.button("演示改稿闭环：加载修改后报告（v2）", width="stretch",
                         icon=":material/arrow_forward:"):
                load_offline_demo(2)
        else:
            st.info("离线演示模式：修改后（v2）报告 —— 已按 v1 的 3 条建议改稿，未调用 API。")
            if st.button("返回修改前报告（v1）", width="stretch", icon=":material/arrow_back:"):
                load_offline_demo(1)
            # 闭环摘要（演示专用硬编码：v1 总分 68 / 漏洞 2 → v2 总分 78 / 漏洞 0）
            d1, d2, d3 = st.columns(3)
            d1.metric("总分", "78/100", "+10 vs v1")
            d2.metric("逻辑漏洞", "0 条", "-2 vs v1")
            d3.metric("建议采纳", "3/3")
            with st.expander("修改后剧本全文（demo_script_v2.txt）"):
                with open(DEMO_SCRIPT_V2_PATH, encoding="utf-8") as f:
                    st.text(f.read())

    if st.session_state["warnings"]:
        with st.expander(f"{len(st.session_state['warnings'])} 条处理提示 / 校验警告"):
            for w in st.session_state["warnings"]:
                st.caption(str(w))

    sc = report.get("score") or {}
    dims = sc.get("dimensions") or {}
    sm = report.get("script_meta") or {}

    def _dim(v):
        return v if v is not None else "—"

    st.title(f"剧本体检报告 · {sm.get('title', '未命名')}", icon=":material/summarize:")
    st.caption(
        f"{sm.get('word_count', 0)} 字 · {sm.get('scene_count', 0)} 场 · "
        f"{meta.get('generated_at', '—')} · 模型 {meta.get('model', '—')}"
    )
    hero_col, digest_col = st.columns([1, 2.1], gap="large")
    with hero_col:
        ov = sc.get("overall")
        # key 定位评分主卡：CSS 对其做呼吸光晕（见 _CSS .st-key-sd-card-score）
        with st.container(border=True, key="sd-card-score"):
            st.metric("综合评分", f"{ov}/100" if ov is not None else "—",
                      icon=":material/workspace_premium:",
                      help="AI 参考分，非行业标准评价")
    with digest_col:
        with st.container(border=True, key="sd-card-digest"):
            st.markdown('<div class="sd-section-label">诊断摘要</div>', unsafe_allow_html=True)
            st.markdown(analyzer.report_digest(report))
    dim_cols = st.columns(6)
    dim_cols[0].metric("角色", _dim(dims.get("character")))
    dim_cols[1].metric("情感", _dim(dims.get("emotion")))
    dim_cols[2].metric("节奏", _dim(dims.get("pacing")))
    dim_cols[3].metric("逻辑", _dim(dims.get("logic")))
    dim_cols[4].metric("结构", _dim(dims.get("structure")))
    dim_cols[5].metric("商业", _dim(dims.get("commercial")))
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

    # ---- 结构体检 ----
    st.subheader("结构体检")
    if not _module_selected(report, "structure"):
        st.caption("本次未分析该模块（旧版报告未包含结构体检）")
    else:
        struct = report.get("structure") or {}
        if not any(struct.get(k) for k in ("acts", "beats", "foreshadows", "arcs")):
            st.caption("旧版报告未包含结构体检")
        else:
            fig = charts.structure_act_chart(report)
            if fig is not None:
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                st.caption("三幕色带：蓝=第一幕 · 绿=第二幕 · 橙=第三幕｜菱形 = 关键节拍（悬停看详情）")
            col_beat, col_fs = st.columns(2, gap="large")
            with col_beat:
                with st.expander("关键节拍"):
                    beats = struct.get("beats") or []
                    if not beats:
                        st.caption("无数据")
                    for b in beats:
                        st.markdown(f"**{b.get('name', '')}** · 第{b.get('scene', '?')}场")
                        st.write(b.get("description", ""))
                        ev = b.get("evidence") or {}
                        if ev.get("text"):
                            st.caption(f"“{ev['text']}”")
                with st.expander("人物弧光"):
                    arcs = struct.get("arcs") or []
                    if not arcs:
                        st.caption("无数据")
                    for a in arcs:
                        st.markdown(
                            f"**{a.get('character', '')}**：{a.get('start_state', '—')} → "
                            f"第{a.get('turning_scene', '?')}场 {a.get('turning_event', '—')} → "
                            f"{a.get('end_state', '—')}"
                        )
            with col_fs:
                with st.expander("伏笔回收清单"):
                    fs = struct.get("foreshadows") or []
                    if not fs:
                        st.caption("未检出伏笔")
                    for f in fs:
                        st.markdown(f"**第{f.get('setup_scene', '?')}场埋点**：{f.get('setup', '')}")
                        if f.get("status") == "resolved":
                            st.caption(f"↳ 第{f.get('payoff_scene') or '?'}场回收：{f.get('payoff', '')}")
                        else:
                            st.caption("↳ 未回收")
                        st.divider()

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

    # ---- 修改建议（附改写示例：R4 独立调用生成，原文过防幻觉硬校验）----
    st.subheader("3 条可执行修改建议")
    rw_map = {r.get("rank"): r for r in (report.get("rewrites") or [])}
    for s in report.get("suggestions", []):
        a = s.get("action") or {}
        with st.container(border=True, key=f"sd-card-sug-{s.get('rank')}"):
            st.markdown(f"**建议 {s.get('rank')}：{s.get('problem', '')}**")
            st.markdown(f"落点：第 {a.get('scene')} 场 → {a.get('concrete', '')}")
            if s.get("expected_effect"):
                st.caption(f"预期效果：{s['expected_effect']}")
            if s.get("references"):
                st.caption(f"关联：{'、'.join(map(str, s['references']))}")
            rw = rw_map.get(s.get("rank"))
            if rw:
                st.markdown("**改写示例（可直接替换）**")
                orig = rw.get("original") or {}
                st.caption(f"原文 · 第{orig.get('scene', '?')}场：“{orig.get('text', '')}”")
                st.code(rw.get("rewritten", ""), language=None)
                if rw.get("note"):
                    st.caption(f"改写理由：{rw['note']}")

    # ---- 上一版建议采纳情况（改稿对比模式 / 离线闭环演示）----
    review = report.get("prev_suggestions_review") or []
    if review:
        st.subheader("上一版建议采纳情况")
        for r in review:
            status = "已落实" if r.get("adopted") else "未落实"
            note = f"：{r['note']}" if r.get("note") else ""
            st.markdown(f"**{status} 建议 {r.get('rank')}**{note}")
            ev = r.get("evidence")
            if ev:
                st.caption(f"第{ev.get('scene')}场 · “{ev.get('text')}”")

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
        icon=":material/download:",
    )
    ec2.download_button(
        "下载 Markdown 报告",
        report_to_markdown(report),
        file_name="script_report.md",
        mime="text/markdown",
        width="stretch",
        icon=":material/download:",
    )
    if st.session_state.get("from_history"):
        if ec3.button("返回历史", key="btn_back_history", width="stretch",
                      icon=":material/arrow_back:"):
            # 清空表格选中：否则回到历史页会被上次的选中再次触发打开
            st.session_state["hist_table"] = {"selection": {"rows": [], "columns": []}}
            st.session_state["stage"] = "history"
            st.rerun()
    else:
        if ec3.button("重新分析其他剧本", width="stretch", icon=":material/restart_alt:"):
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
    st2 = report.get("structure") or {}
    L.append("## 结构体检")
    if not _module_selected(report, "structure"):
        L.append("- 本次未分析该模块（旧版报告未包含结构体检）")
    else:
        for a in st2.get("acts", []):
            L.append(f"- {a.get('name', '')}：第{a.get('scene_start', '?')}-{a.get('scene_end', '?')}场 —— {a.get('summary', '')}")
        for b in st2.get("beats", []):
            L.append(f"- 节拍「{b.get('name', '')}」第{b.get('scene', '?')}场：{b.get('description', '')}")
        for f in st2.get("foreshadows", []):
            if f.get("status") == "resolved":
                L.append(f"- 伏笔：第{f.get('setup_scene', '?')}场埋「{f.get('setup', '')}」"
                         f"→ 第{f.get('payoff_scene') or '?'}场收「{f.get('payoff', '')}」")
            else:
                L.append(f"- 伏笔（未回收）：第{f.get('setup_scene', '?')}场埋「{f.get('setup', '')}」")
        for a in st2.get("arcs", []):
            L.append(f"- 弧光 **{a.get('character', '')}**：{a.get('start_state', '—')}"
                     f" →（第{a.get('turning_scene', '?')}场 {a.get('turning_event', '')}）"
                     f"→ {a.get('end_state', '—')}")
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
    rw_map = {r.get("rank"): r for r in (report.get("rewrites") or [])}
    L.append("## 3 条可执行修改建议")
    for s in report.get("suggestions", []):
        a = s.get("action") or {}
        L.append(f"### 建议 {s.get('rank')}：{s.get('problem', '')}")
        L.append(f"- 落点：第 {a.get('scene')} 场 → {a.get('concrete', '')}")
        if s.get("expected_effect"):
            L.append(f"- 预期效果：{s['expected_effect']}")
        if s.get("references"):
            L.append(f"- 关联：{'、'.join(map(str, s['references']))}")
        rw = rw_map.get(s.get("rank"))
        if rw:
            orig = rw.get("original") or {}
            L.append(f"- 改写示例（原文 · 第{orig.get('scene', '?')}场：“{orig.get('text', '')}”）：")
            L.append("```")
            L.append(rw.get("rewritten", ""))
            L.append("```")
            if rw.get("note"):
                L.append(f"  - 改写理由：{rw['note']}")
    L.append("")
    review = report.get("prev_suggestions_review") or []
    if review:
        L.append("## 上一版建议采纳情况")
        for r in review:
            status = "已落实" if r.get("adopted") else "未落实"
            L.append(f"- {status} 建议 {r.get('rank')}：{r.get('note', '')}")
            ev = r.get("evidence")
            if ev:
                L.append(f"  > 第{ev.get('scene')}场：“{ev.get('text')}”")
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
    st.title("我的历史", icon=":material/history:")
    user_id = st.session_state.get("user_id")
    if user_id is None:
        # 兜底：游客不应进入历史页（入口按钮已隐藏），直接送回上传页
        st.session_state["stage"] = "upload"
        st.rerun()
    if st.button("返回上传页", key="btn_hist_back", icon=":material/arrow_back:"):
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
            if st.button("开始对比", key="btn_compare", width="stretch",
                         icon=":material/compare_arrows:"):
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
    st.subheader("分项评分对比")
    labels = ["角色", "情感", "节奏", "逻辑", "结构", "商业"]
    keys = ["character", "emotion", "pacing", "logic", "structure", "commercial"]
    dims1, dims2 = sc1.get("dimensions") or {}, sc2.get("dimensions") or {}
    rows = [{"维度": lab, "v1": dims1.get(k, 0), "v2": dims2.get(k, 0)} for lab, k in zip(labels, keys)]
    if HAS_PLOTLY:
        import plotly.graph_objects as go

        fig = go.Figure()
        for name, color, vals in (
            ("v1", _PAL["other"], [r["v1"] for r in rows]),
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
    st.title("改稿前后对比", icon=":material/compare_arrows:")
    if st.button("返回历史", key="btn_cmp_back", icon=":material/arrow_back:"):
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
