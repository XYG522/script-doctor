"""用户注册 / 登录模块。

存储：本地 SQLite（users.db，与 app.py 同目录）
密码：PBKDF2-SHA256 加盐哈希（仅标准库实现，无第三方依赖）
"""
import hashlib
import os
import re
import secrets
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.db")
USERNAME_RE = re.compile(r"^\w{2,20}$")  # 字母 / 数字 / 下划线 / 中文，2~20 位
MIN_PASSWORD_LEN = 6
_PBKDF2_ITERATIONS = 200_000


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """建表（幂等，首次运行自动创建 users.db）。"""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE,
                salt          TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL
            )
            """
        )


def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    )
    return dk.hex()


def validate_username(username: str) -> tuple[bool, str]:
    """返回 (是否合法, 原因)。"""
    if not USERNAME_RE.fullmatch(username):
        return False, "用户名需为 2~20 位字母、数字、下划线或中文，不能含空格"
    return True, ""


def validate_password(password: str) -> tuple[bool, str]:
    if len(password) < MIN_PASSWORD_LEN:
        return False, f"密码至少 {MIN_PASSWORD_LEN} 位"
    return True, ""


def register(username: str, password: str) -> tuple[bool, str]:
    """注册新用户。成功返回 (True, 提示语)，失败返回 (False, 原因)。"""
    ok, msg = validate_username(username)
    if not ok:
        return False, msg
    ok, msg = validate_password(password)
    if not ok:
        return False, msg

    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO users (username, salt, password_hash, created_at)"
                " VALUES (?, ?, ?, ?)",
                (username, salt, pw_hash, datetime.now().isoformat(timespec="seconds")),
            )
    except sqlite3.IntegrityError:
        return False, "该用户名已被注册"
    return True, f"注册成功，欢迎 {username}！"


def verify(username: str, password: str) -> bool:
    """校验用户名密码是否正确（用户不存在与密码错误同样返回 False）。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT salt, password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        return False
    salt, stored_hash = row
    return secrets.compare_digest(stored_hash, _hash_password(password, salt))


def get_user_id(username: str) -> int | None:
    """按用户名查用户 id（历史记录用）；用户不存在返回 None。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
    return row[0] if row else None
