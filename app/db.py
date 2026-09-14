"""SQLite-Persistenz: Listings (Duplikat-Check via UNIQUE-Constraint),
Matches (pro Profil, damit dieselbe Wohnung nicht doppelt gemeldet wird)
und ein einfaches Scan-Log.

Annahme (Default lt. Auftrag): SQLite statt Postgres, ein Prozess schreibt
sequenziell -> kein Advisory-Lock nötig, `check_same_thread=False` +
WAL-Modus reichen für FastAPI-Thread + Scheduler-Thread im selben Prozess.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

log = logging.getLogger("db")

_lock = threading.Lock()  # ein Prozess, ein Scheduler-Thread -> reicht als einfache Schreibsperre
_conn: sqlite3.Connection | None = None


def _connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


@contextmanager
def _cursor():
    with _lock:
        conn = _connection()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def init_db() -> None:
    with _cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS listings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                price REAL,
                price_total REAL,
                rooms REAL,
                size REAL,
                address TEXT,
                plz TEXT,
                url TEXT NOT NULL,
                raw TEXT NOT NULL DEFAULT '{}',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                UNIQUE(source, external_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS matches(
                listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                profile_name TEXT NOT NULL,
                score INTEGER NOT NULL,
                reasons TEXT NOT NULL DEFAULT '[]',
                notified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(listing_id, profile_name)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                duration_seconds REAL,
                summary TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings(last_seen DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_matches_score ON matches(score DESC)")
    log.info("SQLite-Datenbank bereit: %s", config.DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_listing(item) -> tuple[int, bool]:
    """Fügt ein Listing ein oder aktualisiert es. Der Duplikat-Check läuft
    über UNIQUE(source, external_id): dieselbe Wohnung wird nie doppelt
    angelegt, sondern nur `last_seen` aktualisiert."""
    now = _now()
    with _cursor() as cur:
        cur.execute(
            "SELECT id FROM listings WHERE source=? AND external_id=?",
            (item.source, item.external_id),
        )
        row = cur.fetchone()
        if row:
            listing_id = row["id"]
            cur.execute(
                """UPDATE listings SET title=?, description=?, price=?, price_total=?,
                   rooms=?, size=?, address=?, plz=?, url=?, raw=?, last_seen=?
                   WHERE id=?""",
                (
                    item.title, item.description, item.price, item.price_total,
                    item.rooms, item.size, item.address, item.plz, item.url,
                    json.dumps(item.raw, ensure_ascii=False), now, listing_id,
                ),
            )
            return listing_id, False

        cur.execute(
            """INSERT INTO listings(source, external_id, title, description, price,
               price_total, rooms, size, address, plz, url, raw, first_seen, last_seen)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item.source, item.external_id, item.title, item.description,
                item.price, item.price_total, item.rooms, item.size, item.address,
                item.plz, item.url, json.dumps(item.raw, ensure_ascii=False), now, now,
            ),
        )
        return cur.lastrowid, True


def save_match(listing_id: int, profile_name: str, score: int, reasons: list[str]) -> bool:
    """Legt einen Match an/aktualisiert ihn und gibt zurück, ob noch NICHT
    benachrichtigt wurde (also ob jetzt notifiziert werden soll)."""
    now = _now()
    with _cursor() as cur:
        cur.execute(
            "SELECT notified FROM matches WHERE listing_id=? AND profile_name=?",
            (listing_id, profile_name),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """UPDATE matches SET score=?, reasons=?, updated_at=?
                   WHERE listing_id=? AND profile_name=?""",
                (score, json.dumps(reasons, ensure_ascii=False), now, listing_id, profile_name),
            )
            return not row["notified"]

        cur.execute(
            """INSERT INTO matches(listing_id, profile_name, score, reasons, notified, created_at, updated_at)
               VALUES(?,?,?,?,0,?,?)""",
            (listing_id, profile_name, score, json.dumps(reasons, ensure_ascii=False), now, now),
        )
        return True


def mark_notified(listing_id: int, profile_name: str) -> None:
    with _cursor() as cur:
        cur.execute(
            "UPDATE matches SET notified=1, updated_at=? WHERE listing_id=? AND profile_name=?",
            (_now(), listing_id, profile_name),
        )


def save_scan_run(summary: dict, duration_seconds: float) -> None:
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO scan_runs(started_at, duration_seconds, summary) VALUES(?,?,?)",
            (_now(), duration_seconds, json.dumps(summary, ensure_ascii=False)),
        )


def get_last_scan_run() -> dict | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT 1")
        row = cur.fetchone()
        return dict(row) if row else None


def get_recent_matches(limit: int = 50) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            """SELECT m.profile_name, m.score, m.reasons, m.notified, l.title, l.price,
                      l.price_total, l.rooms, l.size, l.address, l.url, l.source, l.last_seen
               FROM matches m JOIN listings l ON l.id = m.listing_id
               ORDER BY m.updated_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
