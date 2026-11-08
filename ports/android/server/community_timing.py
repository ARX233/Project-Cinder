"""Bounded community PBs, isolated from the verified competition store."""
import hashlib
import math
import sqlite3
import struct
import threading

from .ghost_service import ContractError


MAGIC = b"CTA1"
ROW_BYTES = 236
RULES = "f4e932bed02ddefd261e5fc798870f474d8fc5e39f4d32b3aa9fc0144e34050f"
PHYSICS = "cd78647227a0a4bb9c56939f2f00b85917530f3bf10ad9c92c6b1d6e780bf0a8"
_STAGES = (363, 364, 365, 366, 367, 0, 369, 0, 376, 371, 372, 0, 374, 375, 377)
_COHORT = bytes.fromhex(RULES + PHYSICS)


def partition(rules, physics, course, traffic):
    if rules != RULES or physics != PHYSICS:
        raise ContractError("community_cohort_unsupported", 409)
    if not 0 <= course < len(_STAGES) or not _STAGES[course] or traffic not in (0, 1):
        raise ContractError("invalid_community_course")
    return course, traffic


def decode(body):
    if len(body) != ROW_BYTES or body[:4] != MAGIC:
        raise ContractError("invalid_community_record")
    if body[4:68] != _COHORT:
        raise ContractError("community_cohort_unsupported", 409)
    course, traffic, owner, attempt, date, elapsed, split_count = struct.unpack_from("<II16s16sQfI", body, 68)
    partition(RULES, PHYSICS, course, traffic)
    if not any(owner) or not any(attempt) or date > 253402300799999 or not 0 < elapsed < 1049 or split_count > 7:
        raise ContractError("invalid_community_record")
    # Match the native console's binary32 multiplication before truncation.
    ms = int(struct.unpack("<f", struct.pack("<f", elapsed * 1000.0))[0])
    if not 1 <= ms <= 1048574:
        raise ContractError("invalid_community_time")
    splits = struct.unpack_from("<7f", body, 124)
    if any(not math.isfinite(t) or not 0 <= t <= elapsed or (i and t < splits[i-1])
           for i, t in enumerate(splits[:split_count])) or any(body[124+4*split_count:152]):
        raise ContractError("invalid_community_splits")
    stage, road, section, start, goal, route, mode, frontend, result, eligible = struct.unpack_from("<3I2f5I", body, 152)
    if ((stage, road, route, mode, frontend, result, eligible) != (_STAGES[course], 0, 0, 6, 2, 8, 1)
            or section >= 75 or not 0 <= start < goal <= 1e9):
        raise ContractError("invalid_community_field")
    glyphs = struct.unpack_from("<5I", body, 192)
    title, klass, model, car_type, power, handling = struct.unpack_from("<6I", body, 212)
    name = "".join(chr(x) for x in glyphs if 0 < x < 65536)
    if (not name or any(x >= 65536 for x in glyphs) or any(glyphs[len(name):])
            or any(not (c.isprintable() or c == "\u3000") for c in name)
            or not 1 <= title < 5200 or klass >= 47 or model >= 247 or 224 <= model <= 231
            or car_type >= 45 or power > 24 or handling > 24):
        raise ContractError("invalid_community_car")
    return course, traffic, owner, attempt, date, ms


class CommunityTiming:
    def __init__(self, path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        try:
            self._db.executescript("""
                PRAGMA max_page_count=8192;
                CREATE TABLE IF NOT EXISTS community_pb_v1 (
                    subject TEXT NOT NULL, owner BLOB NOT NULL, course INTEGER NOT NULL,
                    traffic INTEGER NOT NULL, attempt BLOB NOT NULL, date INTEGER NOT NULL,
                    score INTEGER NOT NULL, record BLOB NOT NULL,
                    PRIMARY KEY(subject, owner, course, traffic), UNIQUE(subject, attempt));
                CREATE INDEX IF NOT EXISTS community_rank_v1
                    ON community_pb_v1(course, traffic, score, date DESC, attempt);
            """)
        except BaseException:
            self._db.close()
            raise

    def submit(self, subject, body):
        course, traffic, owner, attempt, date, score = decode(body)
        # Keep the client's local card key private. Returned rows contain only
        # a scoped stable pseudonym and the data shown in the game.
        public_owner = hashlib.sha256(subject.encode("ascii") + b"\0" + owner).digest()[:16]
        record = body[:76] + public_owner + body[92:]
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                prior = self._db.execute("SELECT record FROM community_pb_v1 WHERE subject=? AND attempt=?",
                                         (subject, attempt)).fetchone()
                if prior and prior[0] != record:
                    raise ContractError("community_attempt_conflict", 409)
                current = self._db.execute("SELECT score FROM community_pb_v1 WHERE subject=? AND owner=? AND course=? AND traffic=?",
                                           (subject, owner, course, traffic)).fetchone()
                if current is None:
                    if self._db.execute("SELECT COUNT(*) FROM community_pb_v1 WHERE subject=?", (subject,)).fetchone()[0] >= 384:
                        raise ContractError("community_account_quota", 429)
                    if self._db.execute("SELECT COUNT(*) FROM community_pb_v1").fetchone()[0] >= 20000:
                        raise ContractError("community_archive_full", 503)
                self._db.execute("""
                    INSERT INTO community_pb_v1 VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(subject,owner,course,traffic) DO UPDATE SET
                    attempt=excluded.attempt,date=excluded.date,score=excluded.score,record=excluded.record
                    WHERE excluded.score < community_pb_v1.score
                """, (subject, owner, course, traffic, attempt, date, score, record))
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return {"sha256": hashlib.sha256(body).hexdigest(), "verified": False}

    def board(self, course, traffic):
        with self._lock:
            rows = self._db.execute("""SELECT record FROM community_pb_v1 WHERE course=? AND traffic=?
                                      ORDER BY score, date DESC, attempt LIMIT 10""", (course, traffic)).fetchall()
        return b"CTB1" + struct.pack("<I", len(rows)) + b"".join(row[0] for row in rows)

    def close(self):
        with self._lock:
            self._db.close()
