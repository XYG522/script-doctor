"""用户系统端到端回归测试：注册 → 游客 → 退出 → 登录（错/对密码）。

运行：py tests/test_auth_flow.py（在 script-doctor 目录下）
使用临时数据库，不污染真实 users.db，可反复运行。
"""
import os
import sys
import tempfile

# 必须在 AppTest 之前打补丁：app.py 里的 auth.init_db() 会用到 DB_PATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

auth.DB_PATH = os.path.join(tempfile.mkdtemp(), "users.db")
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
failures = []


def check(cond, msg):
    print(("PASS" if cond else "FAIL") + ": " + msg)
    if not cond:
        failures.append(msg)


at = AppTest.from_file(APP, default_timeout=60)
at.run()
check(not at.exception, "首次加载无异常（auth 页）")

# 1. 游客流程
at.button(key="btn_guest").click().run()
check(not at.exception, "游客进入无异常")
check(at.session_state["stage"] == "upload", f"游客 stage=upload（实际 {at.session_state['stage']}）")
check(at.session_state["is_guest"] is True, "is_guest=True")
check(any("游客" in m.value for m in at.markdown), "右上角显示「游客」")
btns = [b for b in at.button if b.label == "开始分析"]
check(btns and all(b.disabled for b in btns), "游客的「开始分析」按钮禁用")

# 2. 退出游客模式
at.button(key="btn_logout").click().run()
check(at.session_state["stage"] == "auth", "退出后回到 auth 页")

# 3. 注册
at.text_input(key="reg_username").set_value("冒烟测试")
at.text_input(key="reg_password").set_value("abc12345")
at.text_input(key="reg_confirm").set_value("abc12345")
at.button(key="btn_register").click().run()
check(not at.exception, "注册无异常")
check(at.session_state["stage"] == "upload", f"注册后 stage=upload（实际 {at.session_state['stage']}）")
check(at.session_state["user"] == "冒烟测试", "session user=冒烟测试")
check(any("冒烟测试" in m.value for m in at.markdown), "右上角显示用户名")

# 4. 登录态下（有文本时）在线分析按钮可用
# 注意：页面有两个「开始分析」——粘贴 tab 应有文本而启用，文件 tab 未传文件而禁用
at.text_area(key="paste_area").set_value("测试剧本内容")
at.run()
btns = [b for b in at.button if b.label == "开始分析"]
check(btns and any(not b.disabled for b in btns), "登录用户「开始分析」按钮可用（粘贴 tab 启用）")

# 5. 退出登录
at.button(key="btn_logout").click().run()
check(at.session_state["stage"] == "auth", "退出登录后回到 auth 页")

# 6. 错误密码
at.text_input(key="login_username").set_value("冒烟测试")
at.text_input(key="login_password").set_value("wrong-pass")
at.button(key="btn_login").click().run()
check(at.session_state["stage"] == "auth", "错误密码停留 auth 页")
check(any("用户名或密码错误" in e.value for e in at.error), "显示「用户名或密码错误」提示")

# 7. 正确密码登录
at.text_input(key="login_password").set_value("abc12345")
at.button(key="btn_login").click().run()
check(at.session_state["stage"] == "upload", "正确密码登录成功进入 upload")
check(at.session_state["user"] == "冒烟测试", "登录后 user 正确")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
