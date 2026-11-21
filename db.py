# -*- coding: utf-8 -*-
"""God's Eye — database layer (SQLite, stdlib only).

Design (design):
- A *person* is a dossier. It has no fixed fields.
- A person owns any number of *identifiers* (telegram_id, username, phone,
  email, name, ...). New identifier types can be attached at any time —
  the schema never changes.
- Every search run is logged, and everything found is stored as a *finding*
  linked to the person, so dossiers grow dynamically over time.

sqlite3 is synchronous; calls are pushed to a thread so the async bot
never blocks. No third-party wheels needed (32-bit friendly).
"""
import asyncio
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS persons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS identifiers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id   INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    type        TEXT NOT NULL,              -- telegram_id | username | phone | email | name | ...
    value       TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    UNIQUE(type, value)
);

CREATE TABLE IF NOT EXISTS searches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id   INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    started_at  INTEGER NOT NULL,
    finished_at INTEGER,
    status      TEXT NOT NULL DEFAULT 'running'   -- running | done | error
);

CREATE TABLE IF NOT EXISTS findings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id   INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    search_id   INTEGER REFERENCES searches(id) ON DELETE SET NULL,
    source      TEXT NOT NULL,              -- e.g. telegram_public, web
    category    TEXT NOT NULL,              -- e.g. profile, link, mention
    title       TEXT,
    value       TEXT NOT NULL,              -- the found datum / URL
    snippet     TEXT,
    found_at    INTEGER NOT NULL,
    UNIQUE(person_id, source, value)
);

CREATE TABLE IF NOT EXISTS sent_photos (
    person_id   INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    ref         TEXT NOT NULL,              -- photo ref already sent to the owner
    sent_at     INTEGER NOT NULL,
    PRIMARY KEY (person_id, ref)
);

CREATE INDEX IF NOT EXISTS idx_ident_person ON identifiers(person_id);
CREATE INDEX IF NOT EXISTS idx_find_person  ON findings(person_id);
"""


def _now() -> int:
    return int(time.time())


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._lock = asyncio.Lock()

    # -- internal ---------------------------------------------------------
    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    # -- persons ----------------------------------------------------------
    def _create_person_sync(self, label=None) -> int:
        cur = self._conn.execute(
            "INSERT INTO persons(label, created_at, updated_at) VALUES(?,?,?)",
            (label, _now(), _now()),
        )
        self._conn.commit()
        return cur.lastrowid

    async def create_person(self, label=None) -> int:
        return await self._run(self._create_person_sync, label)

    def _get_person_sync(self, person_id):
        row = self._conn.execute(
            "SELECT * FROM persons WHERE id=?", (person_id,)
        ).fetchone()
        return dict(row) if row else None

    async def get_person(self, person_id):
        return await self._run(self._get_person_sync, person_id)

    def _list_persons_sync(self):
        rows = self._conn.execute(
            "SELECT p.*, COUNT(DISTINCT i.id) AS n_ident, COUNT(DISTINCT f.id) AS n_find "
            "FROM persons p "
            "LEFT JOIN identifiers i ON i.person_id = p.id "
            "LEFT JOIN findings f ON f.person_id = p.id "
            "GROUP BY p.id ORDER BY p.id"
        ).fetchall()
        return [dict(r) for r in rows]

    async def list_persons(self):
        return await self._run(self._list_persons_sync)

    def _delete_person_sync(self, person_id):
        self._conn.execute("DELETE FROM findings WHERE person_id=?", (person_id,))
        self._conn.execute("DELETE FROM searches WHERE person_id=?", (person_id,))
        self._conn.execute("DELETE FROM identifiers WHERE person_id=?", (person_id,))
        cur = self._conn.execute("DELETE FROM persons WHERE id=?", (person_id,))
        self._conn.commit()
        return cur.rowcount > 0

    async def delete_person(self, person_id):
        return await self._run(self._delete_person_sync, person_id)

    def _merge_persons_sync(self, into_id, from_id):
        """Merge dossier `from_id` INTO dossier `into_id` and delete the
        emptied dossier. Identifiers are reassigned (the (type, value)
        pair is globally UNIQUE, so every identifier row already has
        exactly one owner and a plain UPDATE can never collide),
        findings move over deduped by the table's UNIQUE(person_id,
        source, value) — i.e. a finding the target already owns (same
        source and value) is not duplicated — and search history is
        reassigned to the surviving dossier so finding -> search links
        stay valid. Returns True when a merge actually happened."""
        if into_id == from_id:
            return False
        into = self._conn.execute(
            "SELECT id FROM persons WHERE id=?", (into_id,)).fetchone()
        src = self._conn.execute(
            "SELECT id FROM persons WHERE id=?", (from_id,)).fetchone()
        if into is None or src is None:
            return False
        # identifiers: reassign ownership (a copy would collide with
        # the still-existing original row on UNIQUE(type, value))
        self._conn.execute(
            "UPDATE identifiers SET person_id=? WHERE person_id=?",
            (into_id, from_id),
        )
        # findings: move the ones the target does not already own
        # (dedupe by source+value per the UNIQUE constraint, which is
        # what "same finding" means everywhere else in this schema),
        # then drop whatever stayed behind on the source dossier.
        self._conn.execute(
            "INSERT OR IGNORE INTO findings(person_id, search_id, source, "
            "category, title, value, snippet, found_at) "
            "SELECT ?, search_id, source, category, title, value, snippet, "
            "found_at FROM findings WHERE person_id=?",
            (into_id, from_id),
        )
        self._conn.execute(
            "DELETE FROM findings WHERE person_id=?", (from_id,))
        # search history follows the surviving dossier
        self._conn.execute(
            "UPDATE searches SET person_id=? WHERE person_id=?",
            (into_id, from_id),
        )
        self._conn.execute("DELETE FROM persons WHERE id=?", (from_id,))
        self._conn.execute(
            "UPDATE persons SET updated_at=? WHERE id=?", (_now(), into_id))
        self._conn.commit()
        return True

    async def merge_persons(self, into_id, from_id):
        return await self._run(self._merge_persons_sync, into_id, from_id)

    # -- identifiers --------------------------------------------------------
    def _find_person_by_identifier_sync(self, type_, value):
        row = self._conn.execute(
            "SELECT person_id FROM identifiers WHERE type=? AND value=?",
            (type_, value),
        ).fetchone()
        return row["person_id"] if row else None

    async def find_person_by_identifier(self, type_, value):
        return await self._run(self._find_person_by_identifier_sync, type_, value)

    def _add_identifier_sync(self, person_id, type_, value):
        """Attach an identifier to a person. If the identifier is already
        known, returns the person it belongs to (dossiers merge by lookup,
        never duplicate)."""
        existing = self._conn.execute(
            "SELECT person_id FROM identifiers WHERE type=? AND value=?",
            (type_, value),
        ).fetchone()
        if existing:
            return existing["person_id"]
        self._conn.execute(
            "INSERT INTO identifiers(person_id, type, value, created_at) VALUES(?,?,?,?)",
            (person_id, type_, value, _now()),
        )
        self._conn.execute(
            "UPDATE persons SET updated_at=? WHERE id=?", (_now(), person_id)
        )
        self._conn.commit()
        return person_id

    async def add_identifier(self, person_id, type_, value):
        return await self._run(self._add_identifier_sync, person_id, type_, value)

    def _list_identifiers_sync(self, person_id):
        rows = self._conn.execute(
            "SELECT * FROM identifiers WHERE person_id=? ORDER BY id", (person_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    async def list_identifiers(self, person_id):
        return await self._run(self._list_identifiers_sync, person_id)

    # -- searches & findings -------------------------------------------------
    def _start_search_sync(self, person_id):
        cur = self._conn.execute(
            "INSERT INTO searches(person_id, started_at) VALUES(?,?)",
            (person_id, _now()),
        )
        self._conn.commit()
        return cur.lastrowid

    async def start_search(self, person_id):
        return await self._run(self._start_search_sync, person_id)

    def _finish_search_sync(self, search_id, status):
        self._conn.execute(
            "UPDATE searches SET finished_at=?, status=? WHERE id=?",
            (_now(), status, search_id),
        )
        self._conn.commit()

    async def finish_search(self, search_id, status="done"):
        return await self._run(self._finish_search_sync, search_id, status)

    def _add_finding_sync(self, person_id, search_id, source, category, title, value, snippet):
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO findings(person_id, search_id, source, category, title, value, snippet, found_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (person_id, search_id, source, category, title, value, snippet, _now()),
        )
        self._conn.commit()
        return cur.rowcount > 0  # True if newly inserted (not a duplicate)

    async def add_finding(self, person_id, search_id, source, category, title, value, snippet=None):
        return await self._run(
            self._add_finding_sync, person_id, search_id, source, category, title, value, snippet
        )

    def _list_findings_sync(self, person_id):
        rows = self._conn.execute(
            "SELECT * FROM findings WHERE person_id=? ORDER BY source, category, id",
            (person_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    async def list_findings(self, person_id):
        return await self._run(self._list_findings_sync, person_id)

    # -- sent photos (dedupe: a photo is sent to the owner ONCE) ---------
    def _list_sent_photos_sync(self, person_id):
        rows = self._conn.execute(
            "SELECT ref FROM sent_photos WHERE person_id=?",
            (person_id,),
        ).fetchall()
        return {r[0] for r in rows}

    async def list_sent_photos(self, person_id):
        return await self._run(self._list_sent_photos_sync, person_id)

    def _mark_photo_sent_sync(self, person_id, ref):
        self._conn.execute(
            "INSERT OR IGNORE INTO sent_photos(person_id, ref, sent_at) "
            "VALUES(?,?,?)",
            (person_id, ref, _now()),
        )
        self._conn.commit()

    async def mark_photo_sent(self, person_id, ref):
        return await self._run(self._mark_photo_sent_sync, person_id, ref)
