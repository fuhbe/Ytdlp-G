"""Local job journal. A separate SQLite write lock lasts for the runner's lifetime."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager


def connect(root):
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "queue.sqlite", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS jobs
        (id INTEGER PRIMARY KEY, signature TEXT UNIQUE, request TEXT NOT NULL,
         state TEXT NOT NULL, result TEXT)""")
    db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    return db


@contextmanager
def runner(root, db):
    lock = sqlite3.connect(root / "runner.sqlite", timeout=0)
    try:
        try:
            lock.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise ValueError("queue_busy") from exc
        db.execute("UPDATE jobs SET state='pending' WHERE state='running'")
        yield
    finally:
        lock.close()


def enqueue(db, request):
    body = json.dumps(request, sort_keys=True)
    key = hashlib.sha256(body.encode()).hexdigest()
    db.execute(
        "INSERT OR IGNORE INTO jobs(signature,request,state) VALUES(?,?,'pending')", (key, body)
    )
    return db.execute("SELECT id FROM jobs WHERE signature=?", (key,)).fetchone()[0]


def control(db, action, job=None):
    states, target = {
        "pause": (("pending", "running"), "paused"),
        "resume": (("paused",), "pending"),
        "cancel": (("pending", "paused", "running"), "cancelled"),
        "retry": (("failed", "partial", "cancelled"), "pending"),
    }[action]
    marks = ",".join("?" for _ in states)
    sql = f"UPDATE jobs SET state=? WHERE state IN ({marks})"
    args = [target, *states]
    if job is not None:
        sql += " AND id=?"
        args.append(job)
    return db.execute(sql, args).rowcount
