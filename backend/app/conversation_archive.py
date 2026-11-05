"""Durable deleted-chat snapshots, independent of model conversation memory."""
import json
import sqlite3
from .database import xline_database


def archived_chats() -> dict:
    with sqlite3.connect(xline_database.path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS chat_recycle (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        return {key: json.loads(value) for key, value in connection.execute("SELECT id, payload FROM chat_recycle")}


