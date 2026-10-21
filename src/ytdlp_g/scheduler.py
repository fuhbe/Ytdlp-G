"""App-open scheduler with transactional occurrence claiming and UTC storage."""

import json
from datetime import UTC, datetime, timedelta


def tick(database, now=None):
    now = now or datetime.now(UTC)
    added = []
    for schedule in database.schedules():
        due = datetime.fromisoformat(schedule["due"])
        if not schedule["enabled"] or due > now:
            continue
        # add_job's transaction must be nested in the same transaction: explicitly
        # perform both statements here to avoid a crash between enqueue and claim.
        import uuid

        identifier = uuid.uuid4().hex
        stamp = now.isoformat()
        next_due = due
        days = {"daily": 1, "weekly": 7}.get(schedule["recurrence"])
        if days:
            while next_due <= now:
                next_due += timedelta(days=days)
        with database.connection:
            database.connection.execute(
                "INSERT INTO jobs(id,url,title,destination,options,status,created,updated) VALUES(?,?,?,?,?,'queued',?,?)",
                (
                    identifier,
                    schedule["url"],
                    schedule["title"],
                    schedule["destination"],
                    json.dumps(json.loads(schedule["options"])),
                    stamp,
                    stamp,
                ),
            )
            database.connection.execute(
                "UPDATE schedules SET due=?,enabled=?,last_run=? WHERE id=?",
                (next_due.isoformat(), int(bool(days)), stamp, schedule["id"]),
            )
        added.append(identifier)
    return added
