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
  accepted  INTEGER NOT NULL,
  frame     INTEGER,                   -- which frame of the shared record
  pass_no   INTEGER                    -- which traverse of it
);
-- The query this table exists to answer is "what has station X sent lately",
-- and without this index that is a full scan the moment the table is large.
CREATE INDEX IF NOT EXISTS readings_station_t ON readings (station, t DESC);
"""


# SCHEMA is applied with CREATE TABLE IF NOT EXISTS, which creates a missing
# table and does NOTHING for a table that exists with the wrong columns. Adding
# a column to SCHEMA alone would therefore work on a fresh clone and silently
# not work on every machine that already has data -- including the deployed
# Space. PRAGMA user_version is the version marker; each step is idempotent and
# additive, and no step ever drops a column.
SCHEMA_VERSION = 3


def _migrate(c: sqlite3.Connection) -> None:
    have = int(c.execute("PRAGMA user_version").fetchone()[0])
    if have >= SCHEMA_VERSION:
        return
    if have < 2:
        # The housekeeping tier. Without these the hardware-health agent in
        # api/orchestrator.py has nothing to look at and abstains on every
        # live reading -- one of three panel members silently not voting.
        cols = c.execute("PRAGMA table_info(readings)").fetchall()
        existing = {row[1] for row in cols}
        for name, decl in (
            ("vbat_mv",       "INTEGER"),   # supply, millivolts
            ("log_temp_c100", "INTEGER"),   # logger die temperature, 1/100 C
            ("flat_pct",      "INTEGER"),   # % of the node's window that repeated
            ("gap_pct",       "INTEGER"),   # % of scheduled samples missed
            ("selftest_mask", "INTEGER"),   # bitmask, 0 = every check passed
            ("health",        "TEXT"),      # S1..S5 from the healing ladder
            ("boot_id",       "INTEGER"),   # distinguishes a reboot from an outage
            ("reboot_count",  "INTEGER"),
            ("replayed",      "INTEGER"),   # arrived from the store-and-forward spool
        ):
            if name not in existing:
                c.execute(f"ALTER TABLE readings ADD COLUMN {name} {decl}")
    if have < 3:
        # WHICH MOMENT OF THE RECORD A READING IS FOR.
        #
        # Kept because it is not derivable afterwards. A node's trace is drawn
        # on the shared frame axis, and without this column the only way to
        # place a stored reading is to assume frame == seq -- which is true
        # only until a node reboots, replays a spool, or wraps the record.
        cols = c.execute("PRAGMA table_info(readings)").fetchall()
        existing = {row[1] for row in cols}
        for name, decl in (("frame", "INTEGER"), ("pass_no", "INTEGER")):
            if name not in existing:
                c.execute(f"ALTER TABLE readings ADD COLUMN {name} {decl}")
    c.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


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
    _migrate(c)
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
                " node_flags, server_flags, accepted,"
                " vbat_mv, log_temp_c100, flat_pct, gap_pct,"
                " selftest_mask, health, boot_id, reboot_count, replayed,"
                " frame, pass_no)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["t"], rec["station"], rec.get("seq"),
                 rec.get("temp"), rec.get("rh"), rec.get("pres"),
                 ",".join(rec.get("node_flags") or []),
                 ",".join(rec.get("server_flags") or []),
                 1 if rec.get("accepted") else 0,
                 rec.get("vbat_mv"), rec.get("log_temp_c100"),
                 rec.get("flat_pct"), rec.get("gap_pct"),
                 rec.get("selftest_mask"), rec.get("health"),
                 rec.get("boot_id"), rec.get("reboot_count"),
                 1 if rec.get("replayed") else 0,
                 rec.get("frame"), rec.get("pass_no")))
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
                    " server_flags, accepted, frame, pass_no FROM readings"
                    " WHERE station = ?"
                    " ORDER BY t DESC LIMIT ?", (station, limit)).fetchall()
            else:
                rows = c.execute(
                    "SELECT t, station, seq, temp, rh, pres, node_flags,"
                    " server_flags, accepted, frame, pass_no FROM readings"
                    " ORDER BY t DESC LIMIT ?", (limit,)).fetchall()
    except Exception:
        return []
    cols = ("t", "station", "seq", "temp", "rh", "pres",
            "node_flags", "server_flags", "accepted", "frame", "pass_no")
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


def node_health(station: str, window: int = 64) -> dict | None:
    """Latest housekeeping for one station, plus what it implies.

    The node counts its own flat and gap fractions over a rolling window and
    reports them, because it is the only tier that knows a sample was DUE and
    never taken. The server cannot recover that from the rows it received --
    absence of a row is exactly what is not stored. Where the node does not
    report them, they are derived here from the sequence numbers, which is
    weaker but better than nothing.
    """
    try:
        with _lock:
            c = _connect()
            rows = c.execute(
                "SELECT t, seq, vbat_mv, log_temp_c100, flat_pct, gap_pct,"
                " selftest_mask, health, boot_id, reboot_count, temp, rh, pres"
                " FROM readings WHERE station = ? ORDER BY t DESC LIMIT ?",
                (station, window)).fetchall()
    except Exception:
        return None
    if not rows:
        return None

    latest = rows[0]
    out = {
        "station": station, "t": latest[0], "seq": latest[1],
        "vbat_mv": latest[2], "log_temp_c100": latest[3],
        "flat_pct": latest[4], "gap_pct": latest[5],
        "selftest_mask": latest[6], "health": latest[7],
        "boot_id": latest[8], "reboot_count": latest[9],
        "samples": len(rows),
    }

    # FALLBACK, CLEARLY LABELLED AS ONE.
    #
    # A node that reports its own fractions is believed. For one that does not,
    # the sequence numbers still reveal missing samples: seq counts what the
    # node TOOK, so a jump larger than the number of rows received is a gap the
    # server never saw. This cannot see a sample the node itself failed to
    # take, which is why the node's own count is preferred when present.
    if out["gap_pct"] is None and len(rows) >= 2:
        seqs = [r[1] for r in rows if r[1] is not None]
        if len(seqs) >= 2:
            span = max(seqs) - min(seqs) + 1
            if span > 0:
                out["gap_pct"] = max(0, min(100, round(100 * (1 - len(seqs) / span))))
                out["gap_source"] = "derived from seq"

    if out["flat_pct"] is None and len(rows) >= 2:
        same = sum(1 for a, b in zip(rows, rows[1:])
                   if a[10] is not None and a[10] == b[10])
        out["flat_pct"] = round(100 * same / max(len(rows) - 1, 1))
        out["flat_source"] = "derived from stored values"
    return out
