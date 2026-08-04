"""Общие зависимости FastAPI.

`get_conn` живёт здесь (а не в main.py), чтобы роутеры могли на неё ссылаться без
кругового импорта. Объект функции тот же самый, что импортируют тесты как
`backend.main.get_conn`, — значит `app.dependency_overrides` продолжает работать.
"""
from __future__ import annotations

import sqlite3

from ir_storyboard import db, matrix


def get_conn() -> sqlite3.Connection:
    conn = db.connect()
    db.init_schema(conn)
    matrix.seed_layers(conn)
    try:
        yield conn
    finally:
        conn.close()
