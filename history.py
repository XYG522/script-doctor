"""分析历史记录模块。

存储：与 auth.py 共用本地 SQLite（users.db），reports 表保存每份报告的完整 JSON。
设计：
- 列表查询只返回展示列（不含 report_json），按时间倒序，避免逐条解析 JSON
- title / word_count / scene_count / score 为冗余列，方便列表展示
- script_excerpt 存原文前 200 字（去空白），帮助用户认出剧本
- 取完整报告时校验 user_id 归属
"""
import json
import os
import re
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.db")
EXCERPT_CHARS = 200
LIST_LIMIT = 100


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite 默认关闭外键约束
    return conn


def init_db() -> None:
    """建表 + 索引（幂等，首次运行自动创建）。"""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL REFERENCES users(id),
                title           TEXT NOT NULL DEFAULT '未命名剧本',
                script_excerpt  TEXT NOT NULL DEFAULT '',
                word_count      INTEGER NOT NULL DEFAULT 0,
                scene_count     INTEGER NOT NULL DEFAULT 0,
                score           INTEGER,
                report_json     TEXT NOT NULL,
                created_at      TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id, id DESC)"
        )


def save_report(user_id: int, *, script_excerpt: str, report: dict) -> int:
    """保存一份分析报告，返回新记录 id。script_excerpt 传剧本原文即可，内部去空白截断。"""
    sm = report.get("script_meta") or {}
    sc = report.get("score") or {}
    try:
        score = int(sc["overall"]) if sc.get("overall") is not None else None
    except (TypeError, ValueError):
        score = None
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO reports
                (user_id, title, script_excerpt, word_count, scene_count,
                 score, report_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                sm.get("title") or "未命名剧本",
                re.sub(r"\s+", "", script_excerpt or "")[:EXCERPT_CHARS],
                int(sm.get("word_count", 0) or 0),
                int(sm.get("scene_count", 0) or 0),
                score,
                json.dumps(report, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        new_id = cur.lastrowid
    return new_id


def list_reports(user_id: int, limit: int = LIST_LIMIT) -> list[dict]:
    """按时间倒序列出用户的历史记录（仅展示列，不含完整 JSON）。"""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, script_excerpt, word_count, scene_count, score, created_at
            FROM reports WHERE user_id = ? ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [
        {
            "id": r[0],
            "title": r[1],
            "script_excerpt": r[2],
            "word_count": r[3],
            "scene_count": r[4],
            "score": r[5],
            "created_at": r[6],
        }
        for r in rows
    ]


def get_report(user_id: int, report_id: int) -> dict | None:
    """取一份完整报告；非本人记录或不存在返回 None。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT report_json FROM reports WHERE id = ? AND user_id = ?",
            (report_id, user_id),
        ).fetchone()
    return json.loads(row[0]) if row else None
