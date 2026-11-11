"""Bounded community PBs, isolated from the verified competition store."""
import hashlib
import math
import sqlite3
import struct
import threading

from .ghost_service import ContractError
from .ta_rec_car import REC_CAR_IDS


MAGIC = b"CTA1"
ROW_BYTES = 236
RULES = "f4e932bed02ddefd261e5fc798870f474d8fc5e39f4d32b3aa9fc0144e34050f"
PHYSICS = "cd78647227a0a4bb9c56939f2f00b85917530f3bf10ad9c92c6b1d6e780bf0a8"
_STAGES = (363, 364, 365, 366, 367, 0, 369, 0, 376, 371, 372, 0, 374, 375, 377)
_COHORT = bytes.fromhex(RULES + PHYSICS)
BOARD_ORDER = "score ASC, date DESC, attempt ASC, subject ASC, owner ASC"


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
                CREATE TABLE IF NOT EXISTS community_model_best_v1 (
                    course INTEGER NOT NULL, traffic INTEGER NOT NULL,
                    model_class INTEGER NOT NULL, score INTEGER NOT NULL,
                    PRIMARY KEY(course, traffic, model_class));
                CREATE TABLE IF NOT EXISTS community_crown_v1 (
                    course INTEGER PRIMARY KEY, subject TEXT NOT NULL, owner BLOB NOT NULL,
                    acquired_at INTEGER NOT NULL);
                INSERT OR IGNORE INTO community_crown_v1
                    SELECT course, subject, owner, date FROM (
                        SELECT course, subject, owner, date, ROW_NUMBER() OVER (
                            PARTITION BY course ORDER BY score, date DESC, attempt, subject, owner
                        ) AS place FROM community_pb_v1 WHERE traffic=0
                    ) WHERE place=1;
            """)
            self._db.execute("BEGIN IMMEDIATE")
            for course, traffic, score, model in self._db.execute("""
                SELECT course,traffic,score,substr(record,221,4) FROM community_pb_v1
            """).fetchall():
                model_id, = struct.unpack("<I", model)
                if model_id < len(REC_CAR_IDS):
                    self._save_model_best(course, traffic, REC_CAR_IDS[model_id], score)
            self._db.execute("COMMIT")
        except BaseException:
            self._db.close()
            raise

    def _save_model_best(self, course, traffic, model_class, score):
        return self._db.execute("""
            INSERT INTO community_model_best_v1 VALUES (?,?,?,?)
            ON CONFLICT(course,traffic,model_class) DO UPDATE SET score=excluded.score
            WHERE excluded.score < community_model_best_v1.score
        """, (course, traffic, model_class, score)).rowcount != 0

    def _result(self, course, traffic, subject, owner, attempt, current, old_course, new_model, model_class):
        board = self._db.execute(f"""
            SELECT subject,owner,attempt,score FROM community_pb_v1
            WHERE course=? AND traffic=? ORDER BY {BOARD_ORDER} LIMIT 100
        """, (course, traffic)).fetchall()
        personal, = self._db.execute("""
            SELECT score FROM community_pb_v1 WHERE subject=? AND owner=? AND course=? AND traffic=?
        """, (subject, owner, course, traffic)).fetchone()
        car_best, = self._db.execute("""
            SELECT score FROM community_model_best_v1 WHERE course=? AND traffic=? AND model_class=?
        """, (course, traffic, model_class)).fetchone()
        position = next((i for i, row in enumerate(board, 1) if row[:3] == (subject, owner, attempt)), 0)
        course_best = board[0][3]
        flags = ((old_course is None or course_best < old_course)
                 | (new_model << 1) | ((current is None or personal < current[0]) << 2))
        return {"course_best_ms": course_best, "car_best_ms": car_best,
                "personal_best_ms": personal, "rank": position, "new_records": flags}

    def submit(self, subject, body, *, include_result=False):
        course, traffic, owner, attempt, date, score = decode(body)
        model_id, = struct.unpack_from("<I", body, 220)
        model_class = REC_CAR_IDS[model_id]
        ack = {"sha256": hashlib.sha256(body).hexdigest(), "verified": False}
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
                if include_result:
                    old_course, = self._db.execute("""
                        SELECT MIN(score) FROM community_pb_v1 WHERE course=? AND traffic=?
                    """, (course, traffic)).fetchone()
                saved = self._db.execute("""
                    INSERT INTO community_pb_v1 VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(subject,owner,course,traffic) DO UPDATE SET
                    attempt=excluded.attempt,date=excluded.date,score=excluded.score,record=excluded.record
                    WHERE excluded.score < community_pb_v1.score
                """, (subject, owner, course, traffic, attempt, date, score, record))
                if traffic == 0 and saved.rowcount:
                    self._db.execute("""
                        INSERT INTO community_crown_v1 VALUES (?,?,?,?)
                        ON CONFLICT(course) DO UPDATE SET
                            subject=excluded.subject, owner=excluded.owner, acquired_at=excluded.acquired_at
                        WHERE (excluded.subject<>community_crown_v1.subject OR excluded.owner<>community_crown_v1.owner)
                          AND ? < (
                            SELECT score FROM community_pb_v1
                            WHERE course=community_crown_v1.course AND traffic=0
                              AND subject=community_crown_v1.subject AND owner=community_crown_v1.owner
                          )
                    """, (course, subject, owner, date, score))
                new_model = self._save_model_best(course, traffic, model_class, score)
                if include_result:
                    ack["result"] = self._result(course, traffic, subject, owner, attempt, current,
                                                 old_course, new_model, model_class)
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return ack

    def board(self, course, traffic):
        with self._lock:
            rows = self._db.execute(f"""SELECT record FROM community_pb_v1 WHERE course=? AND traffic=?
                                      ORDER BY {BOARD_ORDER} LIMIT 10""", (course, traffic)).fetchall()
        return b"CTB1" + struct.pack("<I", len(rows)) + b"".join(row[0] for row in rows)

    def close(self):
        with self._lock:
            self._db.close()
