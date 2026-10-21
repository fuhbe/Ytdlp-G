"""Versioned SQLite queue, history and schedules. No credentials are stored."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import Options
from .paths import validate_url

ACTIVE = {"running", "processing", "archiving"}


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 2:
            raise RuntimeError("database_newer")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
                destination TEXT NOT NULL, options TEXT NOT NULL, status TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 0, progress REAL DEFAULT 0,
                downloaded INTEGER DEFAULT 0, total INTEGER DEFAULT 0,
                speed REAL DEFAULT 0, eta REAL DEFAULT 0, error TEXT DEFAULT '',
                files TEXT DEFAULT '[]', created TEXT NOT NULL, updated TEXT NOT NULL,
                platform TEXT DEFAULT '', thumbnail TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
                destination TEXT NOT NULL, options TEXT NOT NULL, due TEXT NOT NULL,
                recurrence TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                last_run TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
            );
        """)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(jobs)")}
        if "estimated" not in columns:
            self.connection.execute(
                "ALTER TABLE jobs ADD COLUMN estimated INTEGER NOT NULL DEFAULT 0"
            )
        self.connection.execute("PRAGMA user_version=2")
        self.connection.execute("UPDATE batches SET status='pending' WHERE status='running'")
        self.connection.execute(
            "UPDATE jobs SET status='interrupted', speed=0, eta=0 WHERE status IN ('running','processing','archiving')"
        )
        self.connection.commit()

    def add_job(self, url, title, destination, options, **metadata):
        url = validate_url(url)
        Options.from_dict(options)
        try:
            thumbnail = validate_url(metadata.get("thumbnail", ""))
        except ValueError:
            thumbnail = ""
        identifier = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()
        with self.connection:
            self.connection.execute(
                "INSERT INTO jobs(id,url,title,destination,options,status,created,updated,platform,thumbnail) VALUES(?,?,?,?,?,'queued',?,?,?,?)",
                (
                    identifier,
                    url,
                    title,
                    str(destination),
                    json.dumps(options),
                    now,
                    now,
                    metadata.get("platform", ""),
                    thumbnail,
                ),
            )
        return identifier

    def update(self, identifier, **values):
        allowed = {
            "status",
            "progress",
            "downloaded",
            "total",
            "speed",
            "eta",
            "error",
            "files",
            "title",
            "priority",
            "estimated",
        }
        if not values.keys() <= allowed:
            raise ValueError("invalid_field")
        if "files" in values:
            values["files"] = json.dumps(values["files"], ensure_ascii=False)
        values["updated"] = datetime.now(UTC).isoformat()
        with self.connection:
            self.connection.execute(
                f"UPDATE jobs SET {','.join(f'{key}=?' for key in values)} WHERE id=?",
                (*values.values(), identifier),
            )

    def jobs(self, search=""):
        rows = self.connection.execute(
            "SELECT * FROM jobs WHERE title LIKE ? OR url LIKE ? ORDER BY priority DESC,created",
            (f"%{search}%", f"%{search}%"),
        )
        result = []
        for row in rows:
            item = dict(row)
            item["options"] = json.loads(item["options"])
            item["files"] = json.loads(item["files"])
            result.append(item)
        return result

    def delete(self, identifier):
        with self.connection:
            self.connection.execute(
                "DELETE FROM jobs WHERE id=? AND status NOT IN ('running','processing','archiving')",
                (identifier,),
            )

    def add_schedule(self, url, title, destination, options, due, recurrence):
        url = validate_url(url)
        Options.from_dict(options)
        if recurrence not in {"once", "daily", "weekly"} or due.tzinfo is None:
            raise ValueError("invalid_schedule")
        identifier = uuid.uuid4().hex
        with self.connection:
            self.connection.execute(
                "INSERT INTO schedules(id,url,title,destination,options,due,recurrence) VALUES(?,?,?,?,?,?,?)",
                (
                    identifier,
                    url,
                    title,
                    str(destination),
                    json.dumps(options),
                    due.astimezone(UTC).isoformat(),
                    recurrence,
                ),
            )
        return identifier

    def schedules(self):
        return [
            dict(row) for row in self.connection.execute("SELECT * FROM schedules ORDER BY due")
        ]

    def cancel_schedule(self, identifier):
        with self.connection:
            self.connection.execute("UPDATE schedules SET enabled=0 WHERE id=?", (identifier,))

    def close(self):
        self.connection.close()

    def add_batch(self, payload):
        identifier = uuid.uuid4().hex
        with self.connection:
            self.connection.execute(
                "INSERT INTO batches(id,payload) VALUES(?,?)", (identifier, json.dumps(payload))
            )
        return identifier

    def batches(self):
        return [
            json.loads(row["payload"]) | {"id": row["id"]}
            for row in self.connection.execute("SELECT * FROM batches WHERE status='pending'")
        ]

    def set_batch_status(self, identifier, status):
        if status not in {"pending", "running", "completed", "failed"}:
            raise ValueError("invalid_options")
        with self.connection:
            self.connection.execute("UPDATE batches SET status=? WHERE id=?", (status, identifier))
