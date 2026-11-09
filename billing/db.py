import sqlite3

from flask import current_app, g


def connect():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def fetch_one(sql, params=()):
    row = connect().execute(sql, params).fetchone()
    return dict(row) if row is not None else None


def fetch_all(sql, params=()):
    return [dict(row) for row in connect().execute(sql, params)]


def close(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
