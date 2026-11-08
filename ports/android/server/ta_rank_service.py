"""Offline future TA contract/reference store; NO listener/deployment/game replay.

TrustedPrincipal is a server-internal marker created AFTER a real auth adapter;
constructing it is NOT authentication. The injected verifier must independently
replay the pinned original engine and check complete inputs/config/eligibility.
No verifier, error, timeout, mismatch or client boolean can enter the global board.
Synthetic tests establish this contract only, never original-engine anti-cheat.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import struct
import threading
import time
from typing import Optional, Protocol

MAX_JSON_BYTES = 8192
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_DATE = 253402300799999
MAX_SCORE = 0xFFFFE
STAGES = (363, 364, 365, 366, 367, 0, 369, 0, 376, 371, 372, 0, 374, 375, 377)

class ContractError(ValueError):
    pass

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")

def exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ContractError("unknown_or_missing_fields")
    return value

def integer(value, low=0, high=(1 << 53)-1):
    if type(value) is not int or not low <= value <= high:
        raise ContractError("invalid_integer")
    return value

def hexvalue(value, size):
    if type(value) is not str or re.fullmatch("[0-9a-f]{%d}" % size, value) is None:
        raise ContractError("invalid_hex_identity")
    return value

def scalar(value):
    integer(value, 0, 0x10FFFF)
    if 0xD800 <= value <= 0xDFFF:
        raise ContractError("invalid_unicode")
    return value

def elapsed_ms(bits):
    word = int(hexvalue(bits, 8), 16)
    seconds = struct.unpack("<f", struct.pack("<I", word))[0]
    if not math.isfinite(seconds):
        raise ContractError("noncompetitive_time")
    try:
        scaled = struct.unpack("<f", struct.pack("<f", seconds * 1000.0))[0]
    except OverflowError:
        raise ContractError("noncompetitive_time") from None
    if not math.isfinite(scaled) or not 1 <= scaled < 0xFFFFF:
        raise ContractError("noncompetitive_time")
    return int(scaled)

@dataclass(frozen=True)
class Partition:
    rules_sha256: str
    physics_sha256: str
    course_id: int
    traffic: int

    def __post_init__(self):
        for value in (self.rules_sha256, self.physics_sha256):
            hexvalue(value, 64)
            if int(value, 16) == 0:
                raise ContractError("missing_cohort")
        integer(self.course_id, 0, 14)
        if not STAGES[self.course_id]:
            raise ContractError("disabled_course")
        integer(self.traffic, 0, 1)

    def wire(self):
        return dict(rules_sha256=self.rules_sha256, physics_sha256=self.physics_sha256,
                    course_id=self.course_id, traffic=self.traffic)

    @property
    def key(self):
        return canonical(self.wire()).decode("ascii")

    @classmethod
    def parse(cls, obj):
        return cls(**exact(obj, cls.__dataclass_fields__))

@dataclass(frozen=True)
class Metadata:
    name: tuple
    title_id: int
    class_id: int
    model_id: int
    car_type: int
    power: int
    handling: int
    original_id_valid: int
    original_id1: int
    original_id2: int
    original_devel: int

    def __post_init__(self):
        if type(self.name) is not tuple or len(self.name) != 5:
            raise ContractError("invalid_name")
        padding = False
        for c in self.name:
            scalar(c)
            if padding and c:
                raise ContractError("invalid_name_padding")
            padding |= c == 0
        for k in ("title_id", "class_id", "model_id", "car_type", "original_id1", "original_id2"):
            integer(getattr(self, k), 0, 0xFFFFFFFF)
        integer(self.model_id, 0, 246)
        if 224 <= self.model_id <= 231:
            raise ContractError("noncanonical_model_alias")
        integer(self.car_type, 0, 44)
        integer(self.class_id, 0, 46)
        integer(self.title_id, 1, 5199)
        integer(self.power, 0, 24)
        integer(self.handling, 0, 24)
        integer(self.original_id_valid, 0, 1)
        integer(self.original_devel, 0, 255)
        if not self.original_id_valid and (self.original_id1 or self.original_id2 or self.original_devel):
            raise ContractError("unavailable_original_identity")

    def wire(self):
        return {k: list(self.name) if k == "name" else getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def parse(cls, obj):
        obj = dict(exact(obj, cls.__dataclass_fields__))
        if type(obj["name"]) is not list:
            raise ContractError("invalid_name")
        obj["name"] = tuple(obj["name"])
        return cls(**obj)

@dataclass(frozen=True)
class Run:
    native_elapsed_bits: str
    checkpoint_bits: tuple
    race_field: tuple
    native_game_mode: int
    frontend_game_mode: int
    native_result_state: int
    eligible: int
    metadata: Metadata

    def validate(self, partition):
        elapsed_ms(self.native_elapsed_bits)
        total = struct.unpack("<f", bytes.fromhex(self.native_elapsed_bits)[::-1])[0]
        if type(self.checkpoint_bits) is not tuple or len(self.checkpoint_bits) > 7:
            raise ContractError("invalid_checkpoints")
        last = 0
        for word in self.checkpoint_bits:
            t = struct.unpack("<f", bytes.fromhex(hexvalue(word, 8))[::-1])[0]
            if not math.isfinite(t) or not last <= t <= total:
                raise ContractError("invalid_checkpoints")
            last = t
        if type(self.race_field) is not tuple or len(self.race_field) != 6:
            raise ContractError("invalid_race_field")
        words = [int(hexvalue(w, 8), 16) for w in self.race_field]
        start = struct.unpack("<f", struct.pack("<I", words[3]))[0]
        goal = struct.unpack("<f", struct.pack("<I", words[4]))[0]
        if words[0] != STAGES[partition.course_id] or words[1] != 0 or words[2] >= 75 or words[5] != 0 or not (
                math.isfinite(start) and math.isfinite(goal) and 0 <= start < goal <= 1e9):
            raise ContractError("invalid_race_field")
        for field, expected in (("native_game_mode", 6), ("frontend_game_mode", 2),
                                ("native_result_state", 8), ("eligible", 1)):
            if type(getattr(self, field)) is not int or getattr(self, field) != expected:
                raise ContractError("not_eligible_ta_goal")
        if type(self.metadata) is not Metadata:
            raise ContractError("invalid_metadata")

    def wire(self):
        return {k: self.metadata.wire() if k == "metadata" else
                list(getattr(self, k)) if k in ("race_field", "checkpoint_bits") else getattr(self, k)
                for k in self.__dataclass_fields__}

    @classmethod
    def parse(cls, obj, partition):
        obj = dict(exact(obj, cls.__dataclass_fields__))
        for k in ("race_field", "checkpoint_bits"):
            if type(obj[k]) is not list:
                raise ContractError("invalid_array")
            obj[k] = tuple(obj[k])
        obj["metadata"] = Metadata.parse(obj["metadata"])
        run = cls(**obj)
        run.validate(partition)
        return run

@dataclass(frozen=True)
class Attempt:
    schema_version: int
    attempt_id: str
    nonce: str
    partition: Partition
    claimed_completed_at_ms: int  # untrusted audit only; never board tie authority
    input_sha256: str
    run: Run

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ContractError("unsupported_schema")
        for value in (self.attempt_id, self.nonce):
            hexvalue(value, 32)
            if int(value, 16) == 0:
                raise ContractError("zero_identity")
        if type(self.partition) is not Partition or type(self.run) is not Run:
            raise ContractError("invalid_attempt_types")
        integer(self.claimed_completed_at_ms, 0, MAX_DATE)
        hexvalue(self.input_sha256, 64)
        self.run.validate(self.partition)

    def wire(self):
        return dict(schema_version=1, attempt_id=self.attempt_id, nonce=self.nonce,
                    partition=self.partition.wire(), claimed_completed_at_ms=self.claimed_completed_at_ms,
                    input_sha256=self.input_sha256, run=self.run.wire())

def parse_attempt(payload):
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_JSON_BYTES:
        raise ContractError("json_size_limit")
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ContractError("duplicate_json_key")
            result[k] = v
        return result
    def no_float(_):
        raise ContractError("floating_point_not_allowed")
    def number(s):
        if len(s.lstrip("-")) > 16:
            raise ContractError("invalid_integer")
        return integer(int(s))
    try:
        obj = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs,
                         parse_int=number, parse_float=no_float, parse_constant=no_float)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("invalid_json") from None
    exact(obj, Attempt.__dataclass_fields__)
    if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
        raise ContractError("unsupported_schema")
    for k in ("attempt_id", "nonce"):
        hexvalue(obj[k], 32)
        if int(obj[k], 16) == 0:
            raise ContractError("zero_identity")
    p = Partition.parse(obj["partition"])
    return Attempt(1, obj["attempt_id"], obj["nonce"], p,
                   integer(obj["claimed_completed_at_ms"], 0, MAX_DATE),
                   hexvalue(obj["input_sha256"], 64), Run.parse(obj["run"], p))

@dataclass(frozen=True)
class TrustedPrincipal:
    subject: str
    auth_source: str

    def __post_init__(self):
        for value in (self.subject, self.auth_source):
            if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", value) is None:
                raise ContractError("invalid_principal")

@dataclass(frozen=True)
class VerificationRequest:
    principal: TrustedPrincipal
    attempt: Attempt
    input_evidence: bytes
    binding_sha256: str

@dataclass(frozen=True)
class TrustedTimingVerdict:
    binding_sha256: str
    partition: Partition
    measured_run: Run
    measured_ms: int
    verifier_id: str
    verifier_revision: str

class TrustedTimingVerifier(Protocol):
    def verify(self, request: VerificationRequest, *, deadline_monotonic: float) -> TrustedTimingVerdict:
        """Independently replay pinned original engine, all inputs/config and eligibility."""
        ...

class TimingStore:
    """Offline SQLite reference, single owned instance; no HTTP/auth implementation.

    Verifier timeout is checked after return but cannot terminate a hung in-process
    adapter. Production needs a killable worker plus transport bounds/rate quotas,
    trusted cohort registry, auth/TLS, immutable evidence storage and operations.
    """
    def __init__(self, path=":memory:", *, verifier: Optional[TrustedTimingVerifier]=None,
                 now_ms=None, monotonic=None, timeout_s=5.0):
        if type(path) is not str or (path != ":memory:" and not os.path.isabs(path)) or "\0" in path:
            raise ContractError("trusted_absolute_db_path_required")
        if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 60:
            raise ContractError("invalid_timeout")
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=0)
        self._db.row_factory = sqlite3.Row
        self._verifier = verifier
        self._now = now_ms or (lambda: time.time_ns() // 1000000)
        self._mono = monotonic or time.monotonic
        self._timeout = timeout_s
        self._instance = secrets.token_hex(16)
        self._closed = False
        self._busy = False
        self._db.execute("PRAGMA locking_mode=EXCLUSIVE")
        self._db.execute("BEGIN EXCLUSIVE")
        try:
            self._db.execute("CREATE TABLE IF NOT EXISTS ta_claims (subject TEXT, attempt TEXT, nonce TEXT, binding TEXT, state TEXT, receipt TEXT, PRIMARY KEY(subject,attempt), UNIQUE(subject,nonce))")
            self._db.execute("CREATE TABLE IF NOT EXISTS ta_rows (partition TEXT, subject TEXT, ms INTEGER, recorded_ms INTEGER, sequence INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT, UNIQUE(partition,subject))")
            self._db.execute("CREATE TABLE IF NOT EXISTS ta_revisions (partition TEXT PRIMARY KEY, revision INTEGER)")
            self._db.execute("UPDATE ta_claims SET state='FINAL' WHERE state='VERIFYING'")
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            self._db.close()
            raise

    def _ensure(self):
        if self._closed:
            raise ContractError("store_closed")

    def _transaction(self, action):
        self._db.execute("BEGIN IMMEDIATE")
        try:
            result = action()
            self._db.execute("COMMIT")
            return result
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def submit(self, principal, payload, input_evidence):
        if type(principal) is not TrustedPrincipal:
            raise ContractError("trusted_auth_context_required")
        a = parse_attempt(payload)
        if type(input_evidence) is not bytes or not 1 <= len(input_evidence) <= MAX_INPUT_BYTES:
            raise ContractError("input_size_limit")
        if sha256(input_evidence) != a.input_sha256:
            raise ContractError("input_digest_mismatch")
        binding = sha256(canonical(dict(subject=principal.subject, attempt=a.wire())))
        with self._lock:
            self._ensure()
            old = self._db.execute("SELECT * FROM ta_claims WHERE subject=? AND attempt=?", (principal.subject, a.attempt_id)).fetchone()
            if old:
                if old["binding"] != binding:
                    raise ContractError("idempotency_conflict")
                return json.loads(old["receipt"])
            if self._busy:
                raise ContractError("verification_reentry_forbidden")
            if self._db.execute("SELECT 1 FROM ta_claims WHERE subject=? AND nonce=?", (principal.subject, a.nonce)).fetchone():
                raise ContractError("nonce_replay")
            now = integer(self._now(), 0, MAX_DATE)
            receipt = dict(schema_version=1, attempt_id=a.attempt_id, partition=a.partition.wire(),
                           binding_sha256=binding, status="UNVERIFIED", reason="verification_interrupted",
                           server_verified=False, score_ms=None, board_changed=False,
                           recorded_at_ms=now, verifier_id=None, verifier_revision=None)
            self._transaction(lambda: self._db.execute("INSERT INTO ta_claims VALUES (?,?,?,?,?,?)",
                (principal.subject, a.attempt_id, a.nonce, binding, "VERIFYING", canonical(receipt).decode())))
            verdict = None
            reason = "verifier_unconfigured"
            if self._verifier is not None:
                start = self._mono()
                if not math.isfinite(start):
                    reason = "verifier_clock_invalid"
                else:
                    deadline = start + self._timeout
                    self._busy = True
                    try:
                        verdict = self._verifier.verify(VerificationRequest(principal, a, input_evidence, binding), deadline_monotonic=deadline)
                        end = self._mono()
                        if not math.isfinite(end) or end < start or end > deadline:
                            verdict = None
                            reason = "verification_timeout_or_clock_invalid"
                    except Exception:
                        reason = "verifier_error"
                    finally:
                        self._busy = False
            good = type(verdict) is TrustedTimingVerdict
            if good:
                try:
                    verdict.measured_run.validate(verdict.partition)
                    good = (type(verdict.partition) is Partition and verdict.partition == a.partition
                            and verdict.binding_sha256 == binding and verdict.measured_run == a.run
                            and type(verdict.measured_ms) is int and verdict.measured_ms == elapsed_ms(verdict.measured_run.native_elapsed_bits)
                            and type(verdict.verifier_id) is str and 1 <= len(verdict.verifier_id) <= 64
                            and type(verdict.verifier_revision) is str and 1 <= len(verdict.verifier_revision) <= 64)
                except (ContractError, AttributeError, TypeError):
                    good = False
            if verdict is not None and not good:
                reason = "verdict_binding_or_measurement_mismatch"
            def finalize():
                if good:
                    # The client's claimed calendar date NEVER sets order. This
                    # separate global policy uses trusted server acceptance time.
                    receipt.update(status="SERVER_VERIFIED", reason="verified_not_faster", server_verified=True,
                                   score_ms=verdict.measured_ms, verifier_id=verdict.verifier_id,
                                   verifier_revision=verdict.verifier_revision)
                    row = self._db.execute("SELECT * FROM ta_rows WHERE partition=? AND subject=?", (a.partition.key, principal.subject)).fetchone()
                    if row is None or verdict.measured_ms < row["ms"]:
                        self._db.execute("DELETE FROM ta_rows WHERE partition=? AND subject=?", (a.partition.key, principal.subject))
                        self._db.execute("INSERT INTO ta_rows(partition,subject,ms,recorded_ms,payload) VALUES (?,?,?,?,?)",
                                         (a.partition.key, principal.subject, verdict.measured_ms, now, canonical(a.wire()).decode()))
                        self._db.execute("DELETE FROM ta_rows WHERE partition=? AND sequence NOT IN (SELECT sequence FROM ta_rows WHERE partition=? ORDER BY ms ASC,recorded_ms DESC,sequence DESC LIMIT 100)", (a.partition.key, a.partition.key))
                        retained = self._db.execute("SELECT 1 FROM ta_rows WHERE partition=? AND subject=?", (a.partition.key, principal.subject)).fetchone()
                        if retained:
                            revision = self._db.execute("SELECT revision FROM ta_revisions WHERE partition=?", (a.partition.key,)).fetchone()
                            if revision and revision[0] >= (1 << 53)-1:
                                raise ContractError("revision_exhausted")
                            self._db.execute("INSERT INTO ta_revisions VALUES (?,1) ON CONFLICT(partition) DO UPDATE SET revision=revision+1", (a.partition.key,))
                            receipt.update(reason="verified_board_updated", board_changed=True)
                        else:
                            receipt["reason"] = "verified_outside_top100"
                else:
                    receipt["reason"] = reason
                self._db.execute("UPDATE ta_claims SET state='FINAL',receipt=? WHERE subject=? AND attempt=?",
                                 (canonical(receipt).decode(), principal.subject, a.attempt_id))
            self._transaction(finalize)
            return receipt

    def snapshot(self, partition):
        if type(partition) is not Partition:
            raise ContractError("invalid_partition")
        with self._lock:
            self._ensure()
            revision = self._db.execute("SELECT revision FROM ta_revisions WHERE partition=?", (partition.key,)).fetchone()
            rows = self._db.execute("SELECT * FROM ta_rows WHERE partition=? ORDER BY ms ASC,recorded_ms DESC,sequence DESC LIMIT 10", (partition.key,)).fetchall()
            count = self._db.execute("SELECT COUNT(*) FROM ta_rows WHERE partition=?", (partition.key,)).fetchone()[0]
            return dict(schema_version=1, partition=partition.wire(), server_instance=self._instance,
                        revision=revision[0] if revision else 0, real_count=count,
                        status="SERVER_VERIFIED_ROWS" if rows else "EMPTY_NO_AUTHORITY_CLAIM",
                        rows=[dict(position=i+1, subject=r["subject"], score_ms=r["ms"],
                                   recorded_at_ms=r["recorded_ms"], sequence=str(r["sequence"]),
                                   source="SERVER_VERIFIED", run=json.loads(r["payload"])["run"])
                              for i, r in enumerate(rows)])

    def close(self):
        with self._lock:
            if self._busy:
                raise ContractError("verification_in_progress")
            if not self._closed:
                self._db.close()
                self._closed = True

@dataclass
class SnapshotGuard:
    """Caller-owned request identity. No automatic trusted-server acceptance.

    Binding requires the caller to have authenticated the transport/receipt first;
    arbitrary JSON bearing SERVER_VERIFIED is never enough. Partition, request
    generation, server instance and monotonic revision reject stale/reordered UI.
    """
    partition: Partition
    request_generation: int
    server_instance: str
    revision: int = -1

    def accept(self, snapshot, *, request_generation, trusted_receipt_verified=False):
        if trusted_receipt_verified is not True or request_generation != self.request_generation:
            return False
        try:
            if snapshot["partition"] != self.partition.wire() or snapshot["server_instance"] != self.server_instance:
                return False
            revision = integer(snapshot["revision"])
            if revision <= self.revision:
                return False
        except (KeyError, ContractError, TypeError):
            return False
        self.revision = revision
        return True

@dataclass(frozen=True)
class LocalPendingProposal:
    """Typed copied C outbox cell. Local owner is privacy data, never auth."""
    owner_local: str
    attempt_id: str
    partition: Partition
    claimed_completed_at_ms: int
    run: Run

    def __post_init__(self):
        for value in (self.owner_local, self.attempt_id):
            hexvalue(value, 32)
            if int(value, 16) == 0:
                raise ContractError("zero_identity")
        if type(self.partition) is not Partition or type(self.run) is not Run:
            raise ContractError("invalid_pending_types")
        integer(self.claimed_completed_at_ms, 0, MAX_DATE)
        self.run.validate(self.partition)


def local_upload_request(pending, *, nonce, input_evidence=None):
    """Future adapter only: strip local owner; never fabricate missing replay proof.

    Current C queue has metadata/timing but NO full input evidence. Without those
    bytes there is deliberately no submit-ready Attempt and no invented digest.
    Provided bytes establish integrity only; trusted replay remains mandatory.
    """
    if type(pending) is not LocalPendingProposal:
        raise ContractError("invalid_pending_proposal")
    hexvalue(nonce, 32)
    if int(nonce, 16) == 0:
        raise ContractError("zero_identity")
    result = dict(schema_version=1, attempt_id=pending.attempt_id,
                  partition=pending.partition.wire(), source="LOCAL_UNVERIFIED",
                  status="LOCAL_UNVERIFIED_EVIDENCE_MISSING", input_sha256=None,
                  upload_payload=None, server_receipt=None, server_snapshot=None)
    if input_evidence is None:
        return result
    if type(input_evidence) is not bytes or not 1 <= len(input_evidence) <= MAX_INPUT_BYTES:
        raise ContractError("input_size_limit")
    candidate = Attempt(1, pending.attempt_id, nonce, pending.partition,
                        pending.claimed_completed_at_ms, sha256(input_evidence), pending.run)
    payload = canonical(candidate.wire())
    checked = parse_attempt(payload)
    result.update(status="LOCAL_UNVERIFIED_PENDING_PROPOSAL", input_sha256=checked.input_sha256,
                  upload_payload=checked.wire())
    return result


def local_pending(attempt):
    """Bounded offline proposal only; carries no server receipt or authority."""
    if type(attempt) is not Attempt:
        raise ContractError("invalid_attempt")
    encoded = canonical(attempt.wire())
    # Revalidate all mutable boundary assumptions before producing an outbox item.
    checked = parse_attempt(encoded)
    return dict(schema_version=1, status="LOCAL_UNVERIFIED_PENDING_PROPOSAL",
                attempt=checked.wire(), attempt_sha256=sha256(encoded),
                server_receipt=None, server_snapshot=None)
