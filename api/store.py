"""Where readings actually go.

WHAT WAS HAPPENING BEFORE

Every reading landed in an in-memory deque of 512 per station and nothing else.
Restart the process and the record was gone. That is fine for a screen showing
what arrived in the last minute and wrong for anything called a station network:
the whole argument of this project is that a fault is only visible against
history, and history that evaporates on restart is not history.

WHY SQLITE AND NOT THE DATABASE THE BLUEPRINT NAMES

The blueprint specifies PostgreSQL with TimescaleDB, and it is right for a
national network: 2,000 stations at 15 minutes is 70 million rows a year, and
continuous aggregates give the rollups for free. None of that is needed to stop
losing data today, and standing up Postgres to store a few thousand rows would
be a day spent on infrastructure instead of on the detector.

SQLite is in the standard library, writes durably, handles this load without
noticing, and speaks the same SQL. The migration is a connection string and a
COPY, which is exactly the property the blueprint asks for -- build against the
interface, present the production topology as the design.

WHAT THIS IS HONEST ABOUT

On a Hugging Face Space the filesystem is ephemeral: the rows survive a restart
of the process but not a rebuild of the container. That is a property of the
free tier, not of this code, and /api/ingest/history says so rather than
implying a permanence it does not have.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("SKYGUARD_DB", _ROOT / "data" / "skyguard.db"))

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  t         REAL    NOT NULL,          -- unix seconds, server receipt
  station   TEXT    NOT NULL,
  seq       INTEGER,                   -- the node's own counter, for gap detection
  temp      REAL,
  rh        REAL,
  pres      REAL,
  node_flags   TEXT,                   -- what the node's own screen found
  server_flags TEXT,                   -- what this server found
  accepted  INTEGER NOT NULL
);
-- The query this table exists to answer is "what has station X sent lately",
-- and without this index that is a full scan the moment the table is large.
CREATE INDEX IF NOT EXISTS readings_station_t ON readings (station, t DESC);
"""


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False because FastAPI serves this from a threadpool and
    # every write goes through the lock below anyway.
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    # WAL lets a reader run while a writer holds the file, which is what a
    # dashboard polling history during ingest actually does.
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.executescript(SCHEMA)
    c.commit()
    _conn = c
    return c


def record(rec: dict) -> None:
    """Append one reading. Never raises into the ingest path.

    A station whose reading was accepted and screened must not get a 500
    because the disk is full or the file is locked: the measurement is already
    correct and the storage is a separate concern. Failures are swallowed here
    and visible through /api/ingest/history returning fewer rows than expected.
    """
    try:
        with _lock:
            c = _connect()
            c.execute(
                "INSERT INTO readings (t, station, seq, temp, rh, pres,"
                " node_flags, server_flags, accepted)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (rec["t"], rec["station"], rec.get("seq"),
                 rec.get("temp"), rec.get("rh"), rec.get("pres"),
                 ",".join(rec.get("node_flags") or []),
                 ",".join(rec.get("server_flags") or []),
                 1 if rec.get("accepted") else 0))
            c.commit()
    except Exception:
        pass


def history(station: str | None = None, limit: int = 200) -> list[dict]:
    """Newest first. What the node has actually sent, from disk."""
    try:
        with _lock:
            c = _connect()
            if station:
                rows = c.execute(
                    "SELECT t, station, seq, temp, rh, pres, node_flags,"
                    " server_flags, accepted FROM readings WHERE station = ?"
                    " ORDER BY t DESC LIMIT ?", (station, limit)).fetchall()
            else:
                rows = c.execute(
                    "SELECT t, station, seq, temp, rh, pres, node_flags,"
                    " server_flags, accepted FROM readings"
                    " ORDER BY t DESC LIMIT ?", (limit,)).fetchall()
    except Exception:
        return []
    cols = ("t", "station", "seq", "temp", "rh", "pres",
            "node_flags", "server_flags", "accepted")
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d["node_flags"] = [x for x in (d["node_flags"] or "").split(",") if x]
        d["server_flags"] = [x for x in (d["server_flags"] or "").split(",") if x]
        d["accepted"] = bool(d["accepted"])
        out.append(d)
    return out


def stats() -> dict:
    """How much is stored, and where."""
    try:
        with _lock:
            c = _connect()
            n = c.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
            stations = c.execute(
                "SELECT COUNT(DISTINCT station) FROM readings").fetchone()[0]
            span = c.execute(
                "SELECT MIN(t), MAX(t) FROM readings").fetchone()
    except Exception as e:
        return {"available": False, "why": f"{type(e).__name__}: {e}"}
    return {
        "available": True,
        "path": str(DB_PATH),
        "bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        "readings": n,
        "stations": stations,
        "first": span[0], "last": span[1],
        "durability": "Rows survive a process restart. On an ephemeral host "
                      "(a free Hugging Face Space) they do not survive a "
                      "container rebuild -- that is the host, not the store.",
    }
