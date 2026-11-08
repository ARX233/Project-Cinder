"""Future cloud ghost contract and single-owner SQLite reference store.

No network listener, authentication implementation, or game-engine verifier is
included. TrustedPrincipal/TrustedAdministrator are SERVER integration objects,
not wire credentials. SHA-256 binds bytes; it does not establish a fair race.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from typing import Callable, Optional, Protocol


SCHEMA_VERSION = 1
ORIGINAL_BLOB_FORMAT = "opaque-original070426a"
MAX_JSON_BYTES = 8192
MAX_BLOB_BYTES = 4 * 1024 * 1024
MAX_INPUT_EVIDENCE_BYTES = 8 * 1024 * 1024
MAX_SAFE_INTEGER = (1 << 53) - 1
MAX_CHALLENGE_TTL_MS = 60 * 60 * 1000
_TOKEN = re.compile(r"[A-Za-z0-9_-]{16,96}\Z", re.ASCII)
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class ContractError(ValueError):
    """Stable, non-sensitive API error; an HTTP adapter may use http_status."""

    def __init__(self, code: str, http_status: int = 400):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def _integer(value: object, minimum: int = 1, maximum: int = MAX_SAFE_INTEGER) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContractError("invalid_integer")
    return value


def _text(value: object, pattern: re.Pattern, code: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ContractError(code)
    return value


def _object(value: object, required: set, optional: frozenset = frozenset()) -> dict:
    if type(value) is not dict:
        raise ContractError("expected_object")
    keys = set(value)
    if not required <= keys or keys - required - optional:
        raise ContractError("unknown_or_missing_fields")
    return value


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bounded_bytes(value: object, limit: int) -> bytes:
    if type(value) is not bytes:
        raise ContractError("expected_bytes")
    if not 1 <= len(value) <= limit:
        raise ContractError("invalid_byte_length", 413 if len(value) > limit else 400)
    return value


@dataclass(frozen=True)
class TrustedPrincipal:
    """Created only by a trusted auth adapter after authentication, never JSON."""
    subject: str
    auth_source: str

    def __post_init__(self):
        _text(self.subject, _LABEL, "invalid_principal")
        _text(self.auth_source, _LABEL, "invalid_auth_source")


@dataclass(frozen=True)
class TrustedAdministrator:
    """Server-only provisioning authority; constructing this is privileged."""
    subject: str
    authority: str

    def __post_init__(self):
        _text(self.subject, _LABEL, "invalid_administrator")
        _text(self.authority, _LABEL, "invalid_admin_authority")


def _principal(value: object) -> TrustedPrincipal:
    if type(value) is not TrustedPrincipal:
        raise ContractError("trusted_auth_context_required", 401)
    return value


@dataclass(frozen=True)
class RaceIdentity:
    course_id: str
    route_id: str
    rules_sha256: str
    physics_sha256: str

    def __post_init__(self):
        _text(self.course_id, _LABEL, "invalid_course_id")
        _text(self.route_id, _LABEL, "invalid_route_id")
        _text(self.rules_sha256, _SHA256, "invalid_rules_digest")
        _text(self.physics_sha256, _SHA256, "invalid_physics_digest")

    def to_dict(self) -> dict:
        return {"course_id": self.course_id, "route_id": self.route_id,
                "rules_sha256": self.rules_sha256, "physics_sha256": self.physics_sha256}

    @classmethod
    def from_dict(cls, value: object) -> RaceIdentity:
        obj = _object(value, {"course_id", "route_id", "rules_sha256", "physics_sha256"})
        return cls(**obj)

    @property
    def key(self) -> str:
        return _canonical(self.to_dict()).decode("ascii")


@dataclass(frozen=True)
class GhostMetadata:
    display_name: Optional[str] = None

    def __post_init__(self):
        value = self.display_name
        if value is not None:
            if (type(value) is not str or not 1 <= len(value) <= 64
                    or any(not ch.isprintable() or ch in "/\\" for ch in value)):
                raise ContractError("invalid_display_name")
            try:
                if len(value.encode("utf-8")) > 128:
                    raise ContractError("invalid_display_name")
            except UnicodeError:
                raise ContractError("invalid_display_name") from None

    def to_dict(self) -> dict:
        return {} if self.display_name is None else {"display_name": self.display_name}

    @classmethod
    def from_dict(cls, value: object) -> GhostMetadata:
        obj = _object(value, set(), frozenset({"display_name"}))
        if "display_name" in obj and obj["display_name"] is None:
            raise ContractError("invalid_display_name")
        return cls(**obj)


@dataclass(frozen=True)
class Claim:
    schema_version: int
    claim_id: str
    challenge_id: str
    nonce: str
    old_king_revision: int
    identity: RaceIdentity
    king_blob_sha256: str
    original_blob_format: str
    original_blob_sha256: str
    input_evidence_sha256: str
    metadata: GhostMetadata

    def to_dict(self) -> dict:
        return {"schema_version": self.schema_version, "claim_id": self.claim_id,
                "challenge_id": self.challenge_id, "nonce": self.nonce,
                "old_king_revision": self.old_king_revision, "identity": self.identity.to_dict(),
                "king_blob_sha256": self.king_blob_sha256,
                "original_blob_format": self.original_blob_format,
                "original_blob_sha256": self.original_blob_sha256,
                "input_evidence_sha256": self.input_evidence_sha256,
                "metadata": self.metadata.to_dict()}


def parse_claim_json(payload: bytes) -> Claim:
    """Only public JSON decoder: bounded UTF-8 bytes, exact keys/types, no paths.

    Blob/evidence bytes are supplied separately, not base64 or filesystem names.
    All floating-point literals, non-finite constants and duplicate keys fail.
    """
    _bounded_bytes(payload, MAX_JSON_BYTES)

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError("duplicate_json_key")
            result[key] = value
        return result

    def number(text):
        if len(text.lstrip("-")) > 16:
            raise ContractError("invalid_integer")
        return _integer(int(text), 0)

    def no_float(_):
        raise ContractError("floating_point_not_allowed")

    try:
        obj = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs,
                         parse_int=number, parse_float=no_float, parse_constant=no_float)
    except ContractError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise ContractError("invalid_json") from None
    obj = _object(obj, set(Claim.__dataclass_fields__))
    if type(obj["schema_version"]) is not int or obj["schema_version"] != SCHEMA_VERSION:
        raise ContractError("unsupported_schema_version")
    for key in ("claim_id", "challenge_id", "nonce"):
        _text(obj[key], _TOKEN, "invalid_" + key)
    _integer(obj["old_king_revision"])
    for key in ("king_blob_sha256", "original_blob_sha256", "input_evidence_sha256"):
        _text(obj[key], _SHA256, "invalid_" + key)
    if type(obj["original_blob_format"]) is not str or obj["original_blob_format"] != ORIGINAL_BLOB_FORMAT:
        raise ContractError("unsupported_blob_format")
    return Claim(**{**obj, "identity": RaceIdentity.from_dict(obj["identity"]),
                    "metadata": GhostMetadata.from_dict(obj["metadata"])})


@dataclass(frozen=True)
class KingSnapshot:
    identity: RaceIdentity
    revision: int
    player_id: str
    blob: bytes
    blob_sha256: str
    input_evidence_sha256: str
    metadata: GhostMetadata
    recorded_at_ms: int
    source: str
    originating_receipt_id: Optional[str]

    def __post_init__(self):
        try:
            if type(self.identity) is not RaceIdentity or type(self.metadata) is not GhostMetadata:
                raise ContractError("invalid_snapshot_types")
            _integer(self.revision)
            _integer(self.recorded_at_ms, 0)
            _text(self.player_id, _LABEL, "invalid_principal")
            _text(self.blob_sha256, _SHA256, "invalid_blob_digest")
            _text(self.input_evidence_sha256, _SHA256, "invalid_input_digest")
            _bounded_bytes(self.blob, MAX_BLOB_BYTES)
            if sha256(self.blob) != self.blob_sha256 or self.source not in ("TRUSTED_SEED", "REPLAY_VERIFIED"):
                raise ContractError("corrupt_snapshot")
            if self.originating_receipt_id is not None:
                _text(self.originating_receipt_id, _TOKEN, "invalid_receipt_id")
        except ContractError:
            raise ContractError("stored_snapshot_corrupt", 503) from None

    def to_dict(self) -> dict:
        return {"identity": self.identity.to_dict(), "king_revision": self.revision,
                "player_id": self.player_id, "king_blob_sha256": self.blob_sha256,
                "original_blob_format": ORIGINAL_BLOB_FORMAT,
                "input_evidence_sha256": self.input_evidence_sha256,
                "metadata": self.metadata.to_dict(), "recorded_at_ms": self.recorded_at_ms,
                "source": self.source, "originating_receipt_id": self.originating_receipt_id}


@dataclass(frozen=True)
class ChallengeSnapshot:
    challenge_id: str
    player_id: str
    king: KingSnapshot
    issued_at_ms: int
    expires_at_ms: int

    def __post_init__(self):
        try:
            _text(self.challenge_id, _TOKEN, "invalid_challenge_id")
            _text(self.player_id, _LABEL, "invalid_principal")
            _integer(self.issued_at_ms, 0)
            _integer(self.expires_at_ms)
            if (type(self.king) is not KingSnapshot
                    or not 1 <= self.expires_at_ms - self.issued_at_ms <= MAX_CHALLENGE_TTL_MS):
                raise ContractError("corrupt_challenge")
        except ContractError:
            raise ContractError("stored_snapshot_corrupt", 503) from None

    @property
    def identity(self) -> RaceIdentity:
        return self.king.identity

    @property
    def king_revision(self) -> int:
        return self.king.revision

    @property
    def king_blob_sha256(self) -> str:
        return self.king.blob_sha256

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "challenge_id": self.challenge_id,
                "player_id": self.player_id, "identity": self.identity.to_dict(),
                "king_revision": self.king_revision, "king_blob_sha256": self.king_blob_sha256,
                "original_blob_format": ORIGINAL_BLOB_FORMAT,
                "king_player_id": self.king.player_id, "king_metadata": self.king.metadata.to_dict(),
                "issued_at_ms": self.issued_at_ms, "expires_at_ms": self.expires_at_ms}


class ReplayOutcome(Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    INVALID = "INVALID"


@dataclass(frozen=True)
class VerificationRequest:
    """Immutable server-bound request, including the pinned ORIGINAL king bytes."""
    principal: TrustedPrincipal
    challenge: ChallengeSnapshot
    claim: Claim
    original_blob: bytes
    input_evidence: bytes
    binding_sha256: str


@dataclass(frozen=True)
class ReplayVerdict:
    binding_sha256: str
    outcome: ReplayOutcome
    verifier_id: str
    verifier_revision: str


class ReplayVerifier(Protocol):
    """Trusted SERVER adapter; must independently replay the original engine.

    Implementations must enforce the supplied deadline and return only after
    checking identities, complete input evidence, both original blobs, rules,
    physics, race validity and the authoritative win condition. Never forward
    a client-provided result/boolean as a verdict. The store also rejects late
    returns, but cannot forcibly interrupt an arbitrary in-process Python call.
    """

    def verify(self, request: VerificationRequest, *, deadline_monotonic: float) -> ReplayVerdict:
        ...


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    claim_id: str
    challenge_id: str
    player_id: str
    identity: RaceIdentity
    request_sha256: str
    old_king_revision: int
    king_blob_sha256: str
    original_blob_sha256: str
    input_evidence_sha256: str
    status: str
    reason: str
    verified_win: bool
    promotion_applied: bool
    resulting_king_revision: int
    recorded_at_ms: int
    http_status: int
    verifier_id: Optional[str] = None
    verifier_revision: Optional[str] = None

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, **{
            field: (getattr(self, field).to_dict() if field == "identity" else getattr(self, field))
            for field in self.__dataclass_fields__}}

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    @classmethod
    def _from_stored_json(cls, text: str) -> Receipt:
        # Only this store's bounded, canonical output reaches this private decoder.
        obj = json.loads(text)
        obj.pop("schema_version")
        obj["identity"] = RaceIdentity.from_dict(obj["identity"])
        return cls(**obj)


class GhostStore:
    """Reference implementation, one active instance/owner per SQLite file.

    Default :memory: is volatile. An explicit absolute db_path is TRUSTED server
    configuration, never a wire field. Disk mode retains an SQLite exclusive
    lock until close, deliberately rejecting a second owner. Verification runs
    outside the Python lock; reservation/final receipt/king CAS are transactions.
    A restart finalizes interrupted reservations UNVERIFIED, never retries them.
    """

    def __init__(self, db_path: str = ":memory:", *, verifier: Optional[ReplayVerifier] = None,
                 now_ms: Optional[Callable[[], int]] = None,
                 monotonic: Optional[Callable[[], float]] = None,
                 verification_timeout_s: float = 5.0):
        if type(db_path) is not str or (db_path != ":memory:" and (
                not os.path.isabs(db_path) or "\x00" in db_path)):
            raise ContractError("trusted_absolute_database_path_required")
        if (type(verification_timeout_s) not in (int, float)
                or not 0 < verification_timeout_s <= 60
                or not math.isfinite(verification_timeout_s)):
            raise ContractError("invalid_verification_timeout")
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._active_claims = set()
        self._closed = False
        self._failed = False
        self._verifier = verifier
        self._clock = now_ms or (lambda: int(time.time() * 1000))
        self._monotonic = monotonic or time.monotonic
        self._timeout = verification_timeout_s
        self._db = sqlite3.connect(db_path, timeout=0, check_same_thread=False,
                                   isolation_level=None)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA locking_mode=EXCLUSIVE")
            self._db.execute("PRAGMA journal_mode=DELETE")
            self._db.execute("PRAGMA synchronous=FULL")
            with self._transaction():
                version = self._db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, SCHEMA_VERSION):
                    raise ContractError("unsupported_database_version", 503)
                self._db.execute("""CREATE TABLE IF NOT EXISTS kings (
                    identity_key TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    player_id TEXT NOT NULL, blob BLOB NOT NULL, blob_sha256 TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL, display_name TEXT, recorded_at_ms INTEGER NOT NULL,
                    source TEXT NOT NULL, receipt_id TEXT)""")
                self._db.execute("""CREATE TABLE IF NOT EXISTS challenges (
                    challenge_id TEXT PRIMARY KEY, player_id TEXT NOT NULL,
                    identity_key TEXT NOT NULL REFERENCES kings(identity_key),
                    king_revision INTEGER NOT NULL, king_player_id TEXT NOT NULL,
                    king_blob BLOB NOT NULL, king_blob_sha256 TEXT NOT NULL,
                    king_input_sha256 TEXT NOT NULL, king_display_name TEXT,
                    king_recorded_at_ms INTEGER NOT NULL, king_source TEXT NOT NULL,
                    king_receipt_id TEXT, issued_at_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL, cancelled_at_ms INTEGER)""")
                self._db.execute("""CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    challenge_id TEXT NOT NULL UNIQUE REFERENCES challenges(challenge_id),
                    player_id TEXT NOT NULL, nonce TEXT NOT NULL,
                    submission_sha256 TEXT NOT NULL, request_sha256 TEXT NOT NULL,
                    submission_json TEXT NOT NULL, original_blob BLOB NOT NULL,
                    input_evidence BLOB NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('VERIFYING','FINAL')),
                    receipt_json TEXT NOT NULL, UNIQUE(player_id, nonce))""")
                self._db.execute("PRAGMA user_version=1")
                # The reservation receipt was never returned while VERIFYING.
                # Fail closed after a crash instead of guessing/replaying work.
                self._db.execute("UPDATE claims SET state='FINAL' WHERE state='VERIFYING'")
        except BaseException:
            self._db.close()
            self._closed = True
            raise

    @contextmanager
    def _transaction(self):
        try:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.execute("COMMIT")
            except BaseException:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        except sqlite3.Error:
            self._failed = True
            raise ContractError("storage_unavailable", 503) from None

    def _ensure_open(self):
        if self._closed or self._failed:
            raise ContractError("storage_unavailable", 503)

    def _now(self) -> int:
        return _integer(self._clock(), 0)

    def _tick(self) -> float:
        value = self._monotonic()
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ContractError("invalid_server_clock", 503)
        return value

    @staticmethod
    def _king(row: sqlite3.Row) -> KingSnapshot:
        return KingSnapshot(RaceIdentity.from_dict(json.loads(row["identity_key"])),
                            row["revision"], row["player_id"], bytes(row["blob"]),
                            row["blob_sha256"], row["input_sha256"],
                            GhostMetadata(row["display_name"]), row["recorded_at_ms"],
                            row["source"], row["receipt_id"])

    @staticmethod
    def _challenge(row: sqlite3.Row) -> ChallengeSnapshot:
        king = KingSnapshot(RaceIdentity.from_dict(json.loads(row["identity_key"])),
                            row["king_revision"], row["king_player_id"], bytes(row["king_blob"]),
                            row["king_blob_sha256"], row["king_input_sha256"],
                            GhostMetadata(row["king_display_name"]), row["king_recorded_at_ms"],
                            row["king_source"], row["king_receipt_id"])
        return ChallengeSnapshot(row["challenge_id"], row["player_id"], king,
                                 row["issued_at_ms"], row["expires_at_ms"])

    def _king_row(self, identity: RaceIdentity):
        row = self._db.execute("SELECT * FROM kings WHERE identity_key=?", (identity.key,)).fetchone()
        if row is None:
            raise ContractError("king_not_seeded", 409)
        return row

    def _challenge_row(self, principal: TrustedPrincipal, challenge_id: str):
        row = self._db.execute("SELECT * FROM challenges WHERE challenge_id=?", (challenge_id,)).fetchone()
        if row is None or row["player_id"] != principal.subject:
            raise ContractError("challenge_not_found", 404)
        return row

    @staticmethod
    def _active_challenge(row, now: int):
        if row["cancelled_at_ms"] is not None:
            raise ContractError("challenge_cancelled", 410)
        if now < row["issued_at_ms"] or now >= row["expires_at_ms"]:
            raise ContractError("challenge_expired", 410)

    def seed_king(self, administrator: TrustedAdministrator, identity: RaceIdentity,
                  holder: TrustedPrincipal, original_blob: bytes, input_evidence: bytes,
                  metadata: GhostMetadata = GhostMetadata()) -> KingSnapshot:
        """Privileged first-king provisioning only; never a client claim endpoint."""
        if type(administrator) is not TrustedAdministrator:
            raise ContractError("trusted_admin_context_required", 403)
        _principal(holder)
        if type(identity) is not RaceIdentity or type(metadata) is not GhostMetadata:
            raise ContractError("invalid_seed_types")
        _bounded_bytes(original_blob, MAX_BLOB_BYTES)
        _bounded_bytes(input_evidence, MAX_INPUT_EVIDENCE_BYTES)
        with self._lock:
            self._ensure_open()
            with self._transaction():
                if self._db.execute("SELECT 1 FROM kings WHERE identity_key=?", (identity.key,)).fetchone():
                    raise ContractError("king_already_seeded", 409)
                self._db.execute("INSERT INTO kings VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (identity.key, 1, holder.subject, original_blob, sha256(original_blob),
                                  sha256(input_evidence), metadata.display_name, self._now(),
                                  "TRUSTED_SEED", None))
            return self._king(self._king_row(identity))

    def get_king(self, identity: RaceIdentity) -> KingSnapshot:
        if type(identity) is not RaceIdentity:
            raise ContractError("invalid_identity")
        with self._lock:
            self._ensure_open()
            return self._king(self._king_row(identity))

    def issue_challenge(self, principal: TrustedPrincipal, identity: RaceIdentity,
                        *, ttl_ms: int = 300000) -> ChallengeSnapshot:
        _principal(principal)
        if type(identity) is not RaceIdentity:
            raise ContractError("invalid_identity")
        _integer(ttl_ms, 1, MAX_CHALLENGE_TTL_MS)
        with self._lock:
            self._ensure_open()
            with self._transaction():
                king = self._king(self._king_row(identity))
                issued = self._now()
                expires = _integer(issued + ttl_ms)
                challenge_id = secrets.token_urlsafe(24)
                self._db.execute("INSERT INTO challenges VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (challenge_id, principal.subject, identity.key, king.revision,
                                  king.player_id, king.blob, king.blob_sha256,
                                  king.input_evidence_sha256, king.metadata.display_name,
                                  king.recorded_at_ms, king.source, king.originating_receipt_id,
                                  issued, expires, None))
            return self._challenge(self._challenge_row(principal, challenge_id))

    def get_challenge(self, principal: TrustedPrincipal, challenge_id: str) -> ChallengeSnapshot:
        """Owner-only immutable historical snapshot, including pinned king bytes."""
        _principal(principal)
        _text(challenge_id, _TOKEN, "invalid_challenge_id")
        with self._lock:
            self._ensure_open()
            return self._challenge(self._challenge_row(principal, challenge_id))

    def cancel_challenge(self, principal: TrustedPrincipal, challenge_id: str) -> None:
        _principal(principal)
        _text(challenge_id, _TOKEN, "invalid_challenge_id")
        with self._lock:
            self._ensure_open()
            with self._transaction():
                self._challenge_row(principal, challenge_id)
                claim = self._db.execute("SELECT state FROM claims WHERE challenge_id=?",
                                         (challenge_id,)).fetchone()
                if claim and claim["state"] == "FINAL":
                    raise ContractError("challenge_consumed", 409)
                self._db.execute("UPDATE challenges SET cancelled_at_ms=COALESCE(cancelled_at_ms,?) "
                                 "WHERE challenge_id=?", (self._now(), challenge_id))

    @staticmethod
    def _match_challenge(claim: Claim, challenge: ChallengeSnapshot):
        if (claim.identity != challenge.identity or claim.old_king_revision != challenge.king_revision
                or claim.king_blob_sha256 != challenge.king_blob_sha256):
            raise ContractError("challenge_binding_mismatch", 409)

    def submit_claim(self, principal: TrustedPrincipal, payload: bytes,
                     original_blob: bytes, input_evidence: bytes) -> Receipt:
        """Synchronous idempotent claim. Only a trusted bound verdict can promote.

        Duplicate in-flight requests wait for the very same final receipt. The
        supplied verifier must be deadline-bounded; no default verifier exists.
        """
        _principal(principal)
        claim = parse_claim_json(payload)
        _bounded_bytes(original_blob, MAX_BLOB_BYTES)
        _bounded_bytes(input_evidence, MAX_INPUT_EVIDENCE_BYTES)
        if (sha256(original_blob) != claim.original_blob_sha256
                or sha256(input_evidence) != claim.input_evidence_sha256):
            raise ContractError("evidence_digest_mismatch", 422)
        submission_sha = sha256(_canonical({"player_id": principal.subject, "claim": claim.to_dict()}))
        with self._condition:
            self._ensure_open()
            while True:
                existing = self._db.execute("SELECT * FROM claims WHERE claim_id=?",
                                            (claim.claim_id,)).fetchone()
                if existing is None:
                    break
                if (existing["player_id"] != principal.subject
                        or existing["submission_sha256"] != submission_sha):
                    raise ContractError("idempotency_conflict", 409)
                if existing["state"] == "FINAL":
                    return Receipt._from_stored_json(existing["receipt_json"])
                self._condition.wait()
                self._ensure_open()
            with self._transaction():
                row = self._challenge_row(principal, claim.challenge_id)
                challenge = self._challenge(row)
                self._match_challenge(claim, challenge)
                self._active_challenge(row, self._now())
                if self._db.execute("SELECT 1 FROM claims WHERE player_id=? AND nonce=?",
                                    (principal.subject, claim.nonce)).fetchone():
                    raise ContractError("nonce_replay", 409)
                if self._db.execute("SELECT 1 FROM claims WHERE challenge_id=?",
                                    (claim.challenge_id,)).fetchone():
                    raise ContractError("challenge_consumed", 409)
                binding = sha256(_canonical({"player_id": principal.subject,
                                             "challenge": challenge.to_dict(),
                                             "claim": claim.to_dict()}))
                request = VerificationRequest(principal, challenge, claim, original_blob,
                                              input_evidence, binding)
                receipt = Receipt(secrets.token_urlsafe(24), claim.claim_id, claim.challenge_id,
                                  principal.subject, claim.identity, binding, claim.old_king_revision,
                                  claim.king_blob_sha256, claim.original_blob_sha256,
                                  claim.input_evidence_sha256, "UNVERIFIED", "verification_interrupted",
                                  False, False, self._king_row(claim.identity)["revision"],
                                  self._now(), 503)
                self._db.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                 (claim.claim_id, claim.challenge_id, principal.subject, claim.nonce,
                                  submission_sha, binding, _canonical(claim.to_dict()).decode("ascii"),
                                  original_blob, input_evidence, "VERIFYING",
                                  receipt.to_json().decode("ascii")))
            self._active_claims.add(claim.claim_id)

        verdict = None
        reason = "verifier_unconfigured"
        fatal = None
        try:
            if self._verifier is not None:
                started = self._tick()
                deadline = started + self._timeout
                candidate = self._verifier.verify(request, deadline_monotonic=deadline)
                finished = self._tick()
                if finished < started or finished >= deadline:
                    reason = "verifier_timeout"
                elif (type(candidate) is not ReplayVerdict
                      or type(candidate.binding_sha256) is not str
                      or candidate.binding_sha256 != binding
                      or type(candidate.outcome) is not ReplayOutcome):
                    reason = "invalid_verifier_response"
                else:
                    _text(candidate.verifier_id, _LABEL, "invalid_verifier_identity")
                    _text(candidate.verifier_revision, _LABEL, "invalid_verifier_revision")
                    verdict = candidate
                    reason = "replay_invalid" if candidate.outcome is ReplayOutcome.INVALID else "verified"
        except TimeoutError:
            reason = "verifier_timeout"
        except Exception:
            # Never expose verifier exception strings, which may contain paths/secrets.
            reason = "verifier_exception"
        except BaseException as exc:
            reason = "verification_interrupted"
            fatal = exc

        with self._condition:
            try:
                self._ensure_open()
                with self._transaction():
                    current = self._king_row(claim.identity)
                    self._king(current)  # Corrupt stored bytes must never reach the king CAS.
                    row = self._challenge_row(principal, claim.challenge_id)
                    now = self._now()
                    receipt = replace(receipt, resulting_king_revision=current["revision"],
                                      recorded_at_ms=now, reason=reason,
                                      verifier_id=verdict.verifier_id if verdict else None,
                                      verifier_revision=verdict.verifier_revision if verdict else None)
                    try:
                        self._active_challenge(row, now)
                    except ContractError as exc:
                        receipt = replace(receipt, status="REJECTED", reason=exc.code, http_status=410)
                    else:
                        if verdict is not None and verdict.outcome is ReplayOutcome.LOSS:
                            receipt = replace(receipt, status="VERIFIED_LOSS", http_status=200)
                        elif verdict is not None and verdict.outcome is ReplayOutcome.WIN:
                            if (current["revision"] == challenge.king_revision
                                    and current["blob_sha256"] == challenge.king_blob_sha256):
                                revision = _integer(current["revision"] + 1)
                                changed = self._db.execute(
                                    "UPDATE kings SET revision=?,player_id=?,blob=?,blob_sha256=?,"
                                    "input_sha256=?,display_name=?,recorded_at_ms=?,source=?,receipt_id=? "
                                    "WHERE identity_key=? AND revision=? AND blob_sha256=?",
                                    (revision, principal.subject, original_blob, claim.original_blob_sha256,
                                     claim.input_evidence_sha256, claim.metadata.display_name, now,
                                     "REPLAY_VERIFIED", receipt.receipt_id, claim.identity.key,
                                     challenge.king_revision, challenge.king_blob_sha256)).rowcount
                                if changed != 1:
                                    raise ContractError("storage_cas_failure", 503)
                                receipt = replace(receipt, status="PROMOTED", verified_win=True,
                                                  promotion_applied=True, resulting_king_revision=revision,
                                                  http_status=200)
                            else:
                                receipt = replace(receipt, status="VERIFIED_WIN_STALE", verified_win=True,
                                                  reason="king_revision_changed", http_status=200)
                        elif verdict is not None:
                            receipt = replace(receipt, http_status=422)
                    self._db.execute("UPDATE claims SET state='FINAL',receipt_json=? WHERE claim_id=?",
                                     (receipt.to_json().decode("ascii"), claim.claim_id))
            except BaseException:
                # A local finalization failure cannot leave duplicate callers waiting
                # forever or permit further work on an uncertain in-process store.
                self._failed = True
                raise
            finally:
                self._active_claims.discard(claim.claim_id)
                self._condition.notify_all()
        if fatal is not None:
            raise fatal
        return receipt

    def close(self):
        with self._lock:
            if self._active_claims:
                raise ContractError("verification_in_progress", 409)
            if not self._closed:
                self._db.close()
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
