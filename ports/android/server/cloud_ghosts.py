"""Bounded shared-ghost archive, separate from verified competition results."""
from dataclasses import dataclass
import hashlib
import itertools
import re
import secrets
import sqlite3
import struct
import threading
import time
import zlib

from .ghost_service import ContractError, TrustedPrincipal


_HEADER = 248
_MAX_AREAS = 512
_MAX_SAMPLES = 8192
_SAMPLE_BYTES = 48
MAX_RECORD_BYTES = _HEADER + 28 + 4 * _MAX_AREAS + _SAMPLE_BYTES * _MAX_SAMPLES
SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
GHOST_ID = re.compile(r"[0-9a-f]{32}", re.ASCII)
BATTLE_BYTES = 34
_NAME_HEX = re.compile(r"(?:[0-9a-f]{2}){1,15}", re.ASCII)
_CURSOR = re.compile(r"([1-9][0-9]{0,18})\.([1-9][0-9]{0,18})", re.ASCII)
# 3DX+ frontend ERamp and area tables (0x9739140 and 0x97391a0).
_AREA_RAMPS = ((0, 3), (4, 5), (6, 9), (10, 13), (17, 17), (14, 14), (15, 16), (18, 21))
_ERAMPS = (*range(2, 16), 1, *range(16, 23))
# Shared-only TA slots. (Ghost menu area, EStage, original start area,
# start and goal in mm) from GetConfigRaceField_TimeAttack and 0x9778900.
_TA_FIELDS = (
    (0, 363, 28, 1535000, 15306708),
    (0, 364, 36, 2930000, 16745960),
    (1, 365, 44, 1095000, 18559274),
    (1, 366, 37, 670000, 18313834),
    (2, 367, 45, 7220000, 29711096),
    (3, 369, 13, 1185000, 16288232),
    (4, 376, 64, 150000, 15088780),
    (5, 371, 5, 5000, 18664480),
    (7, 377, 72, 11870000, 28680000),
    (6, 372, 59, 390000, 16180000),
    (2, 374, 55, 3630000, 63428504),
    (2, 375, 56, 815000, 38993028),
)


@dataclass(frozen=True)
class GhostProfile:
    physics_sha256: str
    display_name: str
    raw_model: int
    raw_ramp: int
    route: int


def _valid_name(name):
    return (1 <= len(name) <= 5
            and all((ch.isprintable() or ch == "\u3000") and ch not in "/\\" and ord(ch) <= 0xFFFF for ch in name))


def decode_query_name(value):
    if not _NAME_HEX.fullmatch(value):
        raise ContractError("invalid_name_hex")
    try:
        name = bytes.fromhex(value).decode("utf-8")
    except UnicodeError:
        raise ContractError("invalid_name_hex") from None
    if not _valid_name(name):
        raise ContractError("invalid_name_hex")
    return name


def _trail_syntax(trail, stage, max_ticks):
    version, count = struct.unpack_from("<2I", trail)
    if version != 0x070426A or not 1 <= count <= _MAX_AREAS or len(trail) < 28 + 4 * count:
        raise ContractError("invalid_trail_header")
    areas = set(struct.unpack_from(f"<{count}I", trail, 8))
    at = 8 + 4 * count
    trail_stage, _, step, n = struct.unpack_from("<4I", trail, at)
    if (trail_stage != stage or not 1 <= step <= 60 or not 2 <= n <= _MAX_SAMPLES
            or (n - 1) * step > max_ticks or len(trail) != at + 20 + n * _SAMPLE_BYTES):
        raise ContractError("invalid_trail_header")
    if sum(trail[:-4]) & 0xFFFFFFFF != struct.unpack_from("<I", trail, len(trail) - 4)[0]:
        raise ContractError("invalid_trail_checksum")
    # Original first differences across transposed byte columns. Reassemble
    # rows using the same fixed bounds as the native container reader.
    decoded = bytes(value & 255 for value in itertools.accumulate(trail[at + 16:-4]))
    for row in zip(*(decoded[column * n:(column + 1) * n] for column in range(_SAMPLE_BYTES))):
        sample = bytes(row)
        pose = struct.unpack_from("<4f", sample) + struct.unpack_from("<3f", sample, 32)
        kind, area = struct.unpack_from("<2I", sample, 24)
        if kind != 4 or area not in areas or not all(abs(x) <= 1e9 for x in pose):
            raise ContractError("invalid_trail_sample")


def parse_record(body: bytes, area: int) -> GhostProfile:
    """Validate wire syntax only. The client's native binder checks route geometry."""
    if type(area) is not int or not 0 <= area < len(_AREA_RAMPS):
        raise ContractError("invalid_area")
    if type(body) is not bytes or not _HEADER + 28 <= len(body) <= MAX_RECORD_BYTES:
        raise ContractError("invalid_record_length")
    if body[:8] != b"W3GCROWN":
        raise ContractError("invalid_record_magic")
    version, header, payload, total, checksum, flags, ramp, route = struct.unpack_from("<8I", body, 8)
    if (version != 1 or header != _HEADER or payload != len(body) - _HEADER
            or total != len(body) or flags or any(body[180:184]) or any(body[242:248])):
        raise ContractError("invalid_record_header")
    crc = zlib.crc32(body[28:], zlib.crc32(b"\x00" * 4, zlib.crc32(body[:24])))
    if crc != checksum:
        raise ContractError("invalid_record_checksum")
    raw_model, raw_ramp, custom, aero, mirror, wing, bonnet, wheel, neon, vinyl, title, class_id = (
        struct.unpack_from("<12I", body, 184))
    low, high = _AREA_RAMPS[area]
    stage, road, section, start, goal, mode = struct.unpack_from("<3I2fI", body, 40)
    if raw_ramp < len(_ERAMPS):
        if not low <= raw_ramp <= high or ramp != _ERAMPS[raw_ramp] or route >= 64:
            raise ContractError("invalid_record_course")
    else:
        course = raw_ramp - len(_ERAMPS)
        if (course >= len(_TA_FIELDS) or ramp != raw_ramp + 1 or route or road or mode
                or _TA_FIELDS[course] != (area, stage, section, start, goal)):
            raise ContractError("invalid_record_course")
    if (raw_model >= 247 or custom > 10 or aero > 3 or mirror > 4 or wing > 8 or bonnet > 4
            or (wheel >= 113 and wheel != 143) or neon > 64 or vinyl > 255 or title > 65535 or class_id > 255):
        raise ContractError("invalid_record_profile")
    car_type, gears, *tyres, spokes, power, handling = struct.unpack_from("<2I6f3I", body, 64)
    if (not stage or max(stage, road, section, mode) > 0x7FFFFFFF or not 0 <= start < goal <= 1e9
            or car_type > 44 or not 4 <= gears <= 6 or spokes > 64
            or power > 24 or handling > 24 or power + handling > 34
            or not all(abs(x) <= 1e6 for x in tyres) or min(tyres[1], tyres[4]) < 1
            or struct.unpack_from("<Q", body, 172)[0] > 253402300799):
        raise ContractError("invalid_record_metadata")
    try:
        physics = body[108:172].decode("ascii")
        name = body[232:242].decode("utf-16-le").rstrip("\x00")
    except UnicodeError:
        raise ContractError("invalid_record_profile") from None
    if not SHA256.fullmatch(physics) or not _valid_name(name):
        raise ContractError("invalid_record_profile")
    # Shuto Tokyo is the 60 km TA field. The exception is limited to
    # its already-validated shared-only selector, never arcade profiles.
    max_ticks = 72000 if raw_ramp == 32 and stage == 374 else 36000
    _trail_syntax(memoryview(body)[_HEADER:], stage, max_ticks)
    return GhostProfile(physics, name, raw_model, raw_ramp, route)


class SharedGhosts:
    """Immutable share IDs with optional age- and activity-based eviction."""
    def __init__(self, path, *, max_per_subject=1024, max_total=16384, retention_days=0):
        if not 0 < max_per_subject <= max_total or not 0 <= retention_days <= 3650:
            raise ValueError("invalid ghost quota")
        self._max_per_subject = max_per_subject
        self._max_total = max_total
        self._retention_ms = retention_days * 86400000
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        try:
            if self._retention_ms:
                self._db.execute("PRAGMA auto_vacuum=INCREMENTAL")
                self._db.execute("PRAGMA max_page_count=114688")  # 448 MiB at 4 KiB/page
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS shared_ghosts_v1 (
                    sequence INTEGER PRIMARY KEY,
                    id TEXT UNIQUE NOT NULL,
                    subject TEXT NOT NULL,
                    area INTEGER NOT NULL,
                    physics_sha256 TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    bytes INTEGER NOT NULL,
                    display_name TEXT NOT NULL,
                    raw_model INTEGER NOT NULL,
                    raw_ramp INTEGER NOT NULL,
                    route INTEGER NOT NULL,
                    created_ms INTEGER NOT NULL,
                    record BLOB NOT NULL,
                    card_id TEXT,
                    UNIQUE(subject, area, sha256)
                );
            """)
            if "card_id" not in {row[1] for row in self._db.execute("PRAGMA table_info(shared_ghosts_v1)")}:
                self._db.execute("ALTER TABLE shared_ghosts_v1 ADD COLUMN card_id TEXT")
            self._db.executescript("""
                CREATE INDEX IF NOT EXISTS shared_ghosts_v1_subject
                  ON shared_ghosts_v1(subject, area, physics_sha256, sequence DESC);
                CREATE INDEX IF NOT EXISTS shared_ghosts_v1_physics
                  ON shared_ghosts_v1(physics_sha256, sequence DESC);
                CREATE INDEX IF NOT EXISTS shared_ghosts_v1_cards
                  ON shared_ghosts_v1(subject, card_id, area, physics_sha256, sequence DESC);
                CREATE TABLE IF NOT EXISTS shared_ghost_battles_v1 (
                    sequence INTEGER PRIMARY KEY,
                    challenger TEXT NOT NULL,
                    nonce BLOB NOT NULL,
                    ghost_id TEXT NOT NULL REFERENCES shared_ghosts_v1(id),
                    challenger_won INTEGER NOT NULL,
                    raw_model INTEGER NOT NULL,
                    hp INTEGER NOT NULL,
                    gap INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    created_ms INTEGER NOT NULL,
                    UNIQUE(challenger, nonce)
                );
                CREATE INDEX IF NOT EXISTS shared_ghost_battles_v1_ghost
                  ON shared_ghost_battles_v1(ghost_id, sequence DESC);
                CREATE INDEX IF NOT EXISTS shared_ghost_battles_v1_age ON shared_ghost_battles_v1(created_ms);
                CREATE INDEX IF NOT EXISTS shared_ghosts_v1_age ON shared_ghosts_v1(created_ms);
                CREATE TABLE IF NOT EXISTS shared_ghost_sequence (key INTEGER PRIMARY KEY, last INTEGER NOT NULL);
                INSERT OR IGNORE INTO shared_ghost_sequence SELECT 1,COALESCE(MAX(sequence),0) FROM shared_ghosts_v1;
            """)
        except BaseException:
            self._db.close()
            raise

    @staticmethod
    def _view(row):
        return {**{key: row[key] for key in (
            "id", "sha256", "bytes", "area", "physics_sha256", "display_name",
            "raw_model", "raw_ramp", "route", "created_ms")}, "verified": False}

    def _discard(self, select, args):
        # These statements share the caller's write transaction. A replay and
        # its bounded reported history expire together.
        self._db.execute("DELETE FROM shared_ghost_battles_v1 WHERE ghost_id IN (" + select + ")", args)
        self._db.execute("DELETE FROM shared_ghosts_v1 WHERE id IN (" + select + ")", args)

    def _expire(self, now):
        cutoff = now - self._retention_ms
        self._discard("SELECT id FROM shared_ghosts_v1 WHERE created_ms<=?", (cutoff,))
        self._db.execute("DELETE FROM shared_ghost_battles_v1 WHERE created_ms<=?", (cutoff,))

    def maintain(self):
        if not self._retention_ms:
            return
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._expire(time.time_ns() // 1_000_000)
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("PRAGMA incremental_vacuum(1024)")

    def publish(self, principal, area, record, card_id=None):
        if type(principal) is not TrustedPrincipal:
            raise ContractError("trusted_auth_context_required", 401)
        if card_id is not None and (type(card_id) is not str or not GHOST_ID.fullmatch(card_id)):
            raise ContractError("invalid_card_id")
        profile = parse_record(record, area)
        digest = hashlib.sha256(record).hexdigest()
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                now = time.time_ns() // 1_000_000
                if self._retention_ms:
                    self._expire(now)
                old = self._db.execute("""
                    SELECT * FROM shared_ghosts_v1 WHERE subject=? AND area=? AND sha256=?
                """, (principal.subject, area, digest)).fetchone()
                if old is not None:
                    if card_id is not None and old["card_id"] is None:
                        self._db.execute("UPDATE shared_ghosts_v1 SET card_id=? WHERE id=?",
                                         (card_id, old["id"]))
                    elif card_id is not None and old["card_id"] != card_id:
                        raise ContractError("ghost_card_conflict", 409)
                    result = self._view(old), False
                else:
                    owner_count = self._db.execute(
                        "SELECT COUNT(*) FROM shared_ghosts_v1 WHERE subject=?", (principal.subject,)).fetchone()[0]
                    total_count = self._db.execute("SELECT COUNT(*) FROM shared_ghosts_v1").fetchone()[0]
                    if owner_count >= self._max_per_subject and not self._retention_ms:
                        raise ContractError("ghost_account_quota", 429)
                    if owner_count >= self._max_per_subject:
                        self._discard("SELECT id FROM shared_ghosts_v1 WHERE subject=? ORDER BY sequence LIMIT ?",
                                      (principal.subject, owner_count - self._max_per_subject + 1))
                    if total_count >= self._max_total:
                        if not self._retention_ms:
                            raise ContractError("ghost_archive_full", 503)
                        excess = self._db.execute("SELECT COUNT(*) FROM shared_ghosts_v1").fetchone()[0] - self._max_total + 1
                        if excess > 0:
                            self._discard("SELECT id FROM shared_ghosts_v1 ORDER BY sequence LIMIT ?", (excess,))
                    ghost_id = secrets.token_hex(16)
                    self._db.execute("UPDATE shared_ghost_sequence SET last=last+1 WHERE key=1")
                    self._db.execute("""
                        INSERT INTO shared_ghosts_v1
                        (sequence,id,subject,area,physics_sha256,sha256,bytes,display_name,raw_model,raw_ramp,route,created_ms,record,card_id)
                        VALUES ((SELECT last FROM shared_ghost_sequence WHERE key=1),?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (ghost_id, principal.subject, area, profile.physics_sha256, digest, len(record),
                          profile.display_name, profile.raw_model, profile.raw_ramp, profile.route,
                          now, record, card_id))
                    result = self._view(self._db.execute(
                        "SELECT * FROM shared_ghosts_v1 WHERE id=?", (ghost_id,)).fetchone()), True
                self._db.execute("COMMIT")
                return result
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def list(self, physics, area, limit, cursor, *, name=None, ghost_id=None, exclude_subject=None):
        with self._lock:
            if cursor is None:
                upper = self._db.execute("SELECT COALESCE(MAX(sequence),0) FROM shared_ghosts_v1").fetchone()[0]
                before = upper + 1
            else:
                match = _CURSOR.fullmatch(cursor)
                if not match:
                    raise ContractError("invalid_cursor")
                upper, before = map(int, match.groups())
                if not 1 <= before <= upper < (1 << 63) - 1:
                    raise ContractError("invalid_cursor")
            rows = self._db.execute("""
                SELECT g.id,g.sha256,g.bytes,g.area,g.physics_sha256,g.display_name,
                       g.raw_model,g.raw_ramp,g.route,g.created_ms,g.sequence
                FROM shared_ghosts_v1 AS g
                WHERE g.physics_sha256=? AND (? IS NULL OR g.area=?)
                  AND (? IS NULL OR instr(g.display_name,?)>0)
                  AND (? IS NULL OR g.id=?)
                  AND (? IS NULL OR g.subject<>?)
                  AND g.sequence<=? AND g.sequence<?
                  AND (? IS NOT NULL OR NOT EXISTS (
                    SELECT 1 FROM shared_ghosts_v1 AS newer
                    WHERE newer.subject=g.subject AND newer.area=g.area
                      AND newer.physics_sha256=g.physics_sha256
                      AND newer.card_id IS g.card_id
                      AND (newer.raw_ramp=g.raw_ramp OR (newer.raw_ramp<22 AND g.raw_ramp<22))
                      AND (g.card_id IS NOT NULL OR ? IS NULL OR instr(newer.display_name,?)>0)
                      AND newer.sequence>g.sequence AND newer.sequence<=?
                  ))
                ORDER BY g.sequence DESC LIMIT ?
            """, (physics, area, area, name, name, ghost_id, ghost_id,
                  exclude_subject, exclude_subject, upper, before, ghost_id,
                  name, name, upper, limit + 1)).fetchall()
        next_cursor = f"{upper}.{rows[limit - 1]['sequence']}" if len(rows) > limit else None
        return {"ghosts": [self._view(row) for row in rows[:limit]], "next_cursor": next_cursor}

    def battle(self, principal, ghost_id, body):
        if type(principal) is not TrustedPrincipal:
            raise ContractError("trusted_auth_context_required", 401)
        if len(body) != BATTLE_BYTES:
            raise ContractError("invalid_battle_length")
        nonce, won, model, hp, gap = struct.unpack_from("<16sBBHi", body)
        try:
            name = body[24:].decode("utf-16-le").rstrip("\x00")
        except UnicodeError:
            raise ContractError("invalid_battle_result") from None
        if (won > 1 or model >= 247 or not 1 <= hp <= 2000 or not _valid_name(name)
                or (gap != -(1 << 31) and abs(gap) > 1000000)):
            raise ContractError("invalid_battle_result")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                owner = self._db.execute(
                    "SELECT subject FROM shared_ghosts_v1 WHERE id=?", (ghost_id,)).fetchone()
                if owner is None:
                    raise ContractError("ghost_not_found", 404)
                if owner["subject"] == principal.subject:
                    raise ContractError("own_ghost_battle", 409)
                prior = self._db.execute("""
                    SELECT ghost_id, challenger_won, raw_model, hp, gap, name
                    FROM shared_ghost_battles_v1 WHERE challenger=? AND nonce=?
                """, (principal.subject, nonce)).fetchone()
                if prior is None:
                    count = self._db.execute("""
                        SELECT COUNT(*) FROM shared_ghost_battles_v1 WHERE challenger=?
                    """, (principal.subject,)).fetchone()[0]
                    if count >= self._max_per_subject * 16:
                        raise ContractError("ghost_battle_account_quota", 429)
                    count = self._db.execute("SELECT COUNT(*) FROM shared_ghost_battles_v1").fetchone()[0]
                    if count >= self._max_total * 16:
                        raise ContractError("ghost_battle_archive_full", 503)
                    self._db.execute("""
                        INSERT INTO shared_ghost_battles_v1
                        (challenger, nonce, ghost_id, challenger_won, raw_model, hp, gap, name, created_ms)
                        VALUES (?,?,?,?,?,?,?,?,?)
                    """, (principal.subject, nonce, ghost_id, won, model, hp, gap, name,
                          time.time_ns() // 1_000_000))
                elif tuple(prior) != (ghost_id, won, model, hp, gap, name):
                    raise ContractError("ghost_battle_nonce_conflict", 409)
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return prior is None

    def defense(self, principal, card_id):
        if type(principal) is not TrustedPrincipal:
            raise ContractError("trusted_auth_context_required", 401)
        with self._lock:
            binds = (principal.subject, card_id)
            # One read statement gives totals and recent rows from the same snapshot.
            rows = self._db.execute("""
                SELECT b.created_ms, 1-b.challenger_won AS won, b.raw_model, b.hp, b.name, g.area, b.gap,
                       COUNT(*) OVER () AS battles, SUM(1-b.challenger_won) OVER () AS wins
                FROM shared_ghosts_v1 AS g JOIN shared_ghost_battles_v1 AS b ON b.ghost_id=g.id
                WHERE g.subject=? AND g.card_id=?
                ORDER BY b.sequence DESC LIMIT 8
            """, binds).fetchall()
        recent = [{k: row[k] for k in ("created_ms", "won", "raw_model", "hp", "name", "area", "gap")} for row in rows]
        return {"battles": rows[0]["battles"] if rows else 0, "wins": rows[0]["wins"] if rows else 0,
                "recent": recent, "verified": False}

    def download(self, ghost_id):
        with self._lock:
            row = self._db.execute(
                "SELECT sha256,record FROM shared_ghosts_v1 WHERE id=?", (ghost_id,)).fetchone()
        if row is None:
            raise ContractError("ghost_not_found", 404)
        return row["record"], row["sha256"]

    def close(self):
        with self._lock:
            self._db.close()
