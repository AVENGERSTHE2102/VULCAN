import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path


def uid():
    return uuid.uuid4().hex


class Store:
    def __init__(self, path=None):
        path = path or os.environ.get("LAB_DB", ".data/lab.db")
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS objects(session TEXT, kind TEXT, id TEXT, mission INTEGER, data TEXT, PRIMARY KEY(session,kind,id));
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, session TEXT, task TEXT, mission INTEGER, seq INTEGER, data TEXT);
        CREATE INDEX IF NOT EXISTS event_task ON events(session,task,seq);
        """)

    def put(self, session, kind, id, data, mission=0):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO objects VALUES(?,?,?,?,?)",
                (session, kind, id, mission, json.dumps(data)),
            )
        return data

    def get(self, session, kind, id, default=None):
        with self.lock:
            row = self.db.execute(
                "SELECT data FROM objects WHERE session=? AND kind=? AND id=?",
                (session, kind, id),
            ).fetchone()
        return json.loads(row[0]) if row else default

    def list(self, session, kind, mission=None):
        sql = "SELECT data FROM objects WHERE session=? AND kind=?"
        args = [session, kind]
        if mission is not None:
            sql += " AND mission=?"
            args.append(mission)
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute(sql, args).fetchall()]

    def event(
        self,
        session,
        task,
        kind,
        data,
        action=None,
        source="System",
        provider=None,
        model=None,
    ):
        with self.lock, self.db:
            seq = (
                self.db.execute(
                    "SELECT COUNT(*) FROM events WHERE session=? AND task=?",
                    (session, task["id"]),
                ).fetchone()[0]
                + 1
            )
            e = {
                "id": uid(),
                "task_id": task["id"],
                "action_id": action,
                "sequence": seq,
                "timestamp": time.time(),
                "kind": kind,
                "source": source,
                "provider": provider,
                "model": model,
                "data": data,
            }
            self.db.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?)",
                (e["id"], session, task["id"], task["mission"], seq, json.dumps(e)),
            )
        return e

    def events(self, session, task=None, after=0):
        with self.lock:
            if task:
                rows = self.db.execute(
                    "SELECT data FROM events WHERE session=? AND task=? AND seq>? ORDER BY seq",
                    (session, task, after),
                ).fetchall()
            else:
                rows = self.db.execute(
                    "SELECT data FROM events WHERE session=? ORDER BY rowid", (session,)
                ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def reset(self, session, mission=None):
        with self.lock, self.db:
            for table in ("objects", "events"):
                self.db.execute(
                    f"DELETE FROM {table} WHERE session=?"
                    + (" AND mission=?" if mission else ""),
                    (session, mission) if mission else (session,),
                )
