"""Synthetic protocol/state-model tests, NOT original-engine verification.

MockVerifier authority ends at this contract. No game assets, real replay,
network listener, dependencies, or default passing production verifier exist.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.ghost_service import (  # noqa: E402
    ContractError, GhostMetadata, GhostStore, MAX_BLOB_BYTES, MAX_INPUT_EVIDENCE_BYTES,
    MAX_JSON_BYTES, ORIGINAL_BLOB_FORMAT, RaceIdentity, ReplayOutcome, ReplayVerdict,
    TrustedAdministrator, TrustedPrincipal, parse_claim_json, sha256,
)


ADMIN = TrustedAdministrator("test-admin", "synthetic-test-provisioning")
SEED = TrustedPrincipal("seed-owner", "test-auth-adapter")
ALICE = TrustedPrincipal("alice", "test-auth-adapter")
BOB = TrustedPrincipal("bob", "test-auth-adapter")
IDENTITY = RaceIdentity("synthetic-course", "synthetic-route", sha256(b"rules-v1"), sha256(b"physics-v1"))
SEED_BLOB = b"synthetic opaque original070426a seed; not a game asset"
BLOB = b"synthetic opaque original070426a candidate"
INPUTS = b"synthetic timestamped input evidence"


class Clock:
    def __init__(self):
        self.value = 1700000000000

    def __call__(self):
        return self.value


class MockVerifier:
    """Test-only model authority, NEVER an original-engine anti-cheat oracle."""

    def __init__(self, outcome=ReplayOutcome.WIN, behavior=None):
        self.outcome = outcome
        self.behavior = behavior
        self.calls = []
        self.lock = threading.Lock()

    def verify(self, request, *, deadline_monotonic):
        with self.lock:
            self.calls.append(request)
        if self.behavior:
            return self.behavior(request, deadline_monotonic)
        return self.verdict(request)

    def verdict(self, request):
        return ReplayVerdict(request.binding_sha256, self.outcome,
                             "synthetic-model-verifier", "protocol-test-v1")


def envelope(challenge, index=1, blob=BLOB, inputs=INPUTS):
    return {"schema_version": 1, "claim_id": "claim-" + str(index).zfill(20),
            "challenge_id": challenge.challenge_id, "nonce": "nonce-" + str(index).zfill(20),
            "old_king_revision": challenge.king_revision,
            "identity": challenge.identity.to_dict(), "king_blob_sha256": challenge.king_blob_sha256,
            "original_blob_format": ORIGINAL_BLOB_FORMAT, "original_blob_sha256": sha256(blob),
            "input_evidence_sha256": sha256(inputs), "metadata": {"display_name": "Synthetic driver"}}


def encode(obj):
    return json.dumps(obj, separators=(",", ":")).encode("utf-8")


class GhostCloudContractHostTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()

    def store(self, verifier=None, *, seeded=True, path=":memory:", **kwargs):
        result = GhostStore(path, verifier=verifier, now_ms=self.clock, **kwargs)
        self.addCleanup(result.close)
        if seeded:
            result.seed_king(ADMIN, IDENTITY, SEED, SEED_BLOB, b"synthetic seed evidence")
        return result

    def assert_error(self, code, action, status=None):
        with self.assertRaises(ContractError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)
        if status is not None:
            self.assertEqual(caught.exception.http_status, status)

    def test_empty_partition_cannot_be_claimed_or_client_seeded(self):
        store = self.store(seeded=False)
        self.assert_error("king_not_seeded", lambda: store.issue_challenge(ALICE, IDENTITY), 409)
        self.assert_error("trusted_admin_context_required", lambda: store.seed_king(
            ALICE, IDENTITY, ALICE, BLOB, INPUTS), 403)
        store.seed_king(ADMIN, IDENTITY, SEED, SEED_BLOB, INPUTS)
        self.assert_error("king_already_seeded", lambda: store.seed_king(
            ADMIN, IDENTITY, ALICE, BLOB, INPUTS), 409)
        self.assertEqual(store.get_king(IDENTITY).player_id, SEED.subject)

    def test_partition_is_full_course_route_rules_physics_identity(self):
        store = self.store(MockVerifier())
        identities = [IDENTITY, replace(IDENTITY, course_id="other-course"),
                      replace(IDENTITY, route_id="other-route"),
                      replace(IDENTITY, rules_sha256=sha256(b"rules-v2")),
                      replace(IDENTITY, physics_sha256=sha256(b"physics-v2"))]
        for identity in identities[1:]:
            store.seed_king(ADMIN, identity, SEED, SEED_BLOB, INPUTS)
        challenge = store.issue_challenge(ALICE, IDENTITY)
        receipt = store.submit_claim(ALICE, encode(envelope(challenge)), BLOB, INPUTS)
        self.assertEqual(receipt.status, "PROMOTED")
        self.assertEqual([store.get_king(x).revision for x in identities], [2, 1, 1, 1, 1])

    def test_authentication_is_separate_from_uploaded_json(self):
        store = self.store(MockVerifier())
        for context in (None, "alice", {"subject": "alice", "auth_source": "trusted"}):
            with self.subTest(context=context):
                self.assert_error("trusted_auth_context_required",
                                  lambda: store.issue_challenge(context, IDENTITY), 401)
        challenge = store.issue_challenge(ALICE, IDENTITY)
        payload = encode(envelope(challenge))
        self.assert_error("trusted_auth_context_required",
                          lambda: store.submit_claim({"player_id": "alice"}, payload, BLOB, INPUTS), 401)
        self.assert_error("challenge_not_found", lambda: store.submit_claim(BOB, payload, BLOB, INPUTS), 404)
        self.assert_error("challenge_not_found", lambda: store.get_challenge(BOB, challenge.challenge_id), 404)
        self.assert_error("challenge_not_found", lambda: store.cancel_challenge(BOB, challenge.challenge_id), 404)
        self.assertEqual(store.get_king(IDENTITY).revision, 1)

    def test_issue_pins_immutable_original_snapshot_and_server_times(self):
        store = self.store(MockVerifier())
        challenge = store.issue_challenge(ALICE, IDENTITY, ttl_ms=1234)
        before = challenge.to_dict()
        self.assertEqual(before["player_id"], ALICE.subject)
        self.assertEqual(before["issued_at_ms"], self.clock.value)
        self.assertEqual(before["expires_at_ms"], self.clock.value + 1234)
        self.assertEqual(challenge.king.blob, SEED_BLOB)
        self.assertEqual(challenge.king_blob_sha256, sha256(SEED_BLOB))
        with self.assertRaises(FrozenInstanceError):
            challenge.king.revision = 99
        before["king_metadata"]["display_name"] = "changed copy"
        self.assertNotEqual(before, store.get_challenge(ALICE, challenge.challenge_id).to_dict())
        self.assertEqual(store.get_challenge(ALICE, challenge.challenge_id), challenge)

    def test_unconfigured_verifier_is_fail_closed_and_idempotent_503(self):
        store = self.store()
        challenge = store.issue_challenge(ALICE, IDENTITY)
        payload = encode(envelope(challenge))
        receipt = store.submit_claim(ALICE, payload, BLOB, INPUTS)
        self.assertEqual((receipt.status, receipt.reason, receipt.http_status),
                         ("UNVERIFIED", "verifier_unconfigured", 503))
        self.assertFalse(receipt.verified_win)
        self.assertFalse(receipt.promotion_applied)
        self.assertIsNone(receipt.verifier_id)
        self.assertEqual(store.get_king(IDENTITY).revision, 1)
        self.assertEqual(store.submit_claim(ALICE, payload, BLOB, INPUTS).to_json(), receipt.to_json())

    def test_verified_win_replaces_same_revision_and_records_receipt(self):
        verifier = MockVerifier()
        store = self.store(verifier)
        challenge = store.issue_challenge(ALICE, IDENTITY)
        receipt = store.submit_claim(ALICE, encode(envelope(challenge)), BLOB, INPUTS)
        self.assertEqual(receipt.status, "PROMOTED")
        self.assertTrue(receipt.verified_win and receipt.promotion_applied)
        self.assertEqual(receipt.resulting_king_revision, 2)
        king = store.get_king(IDENTITY)
        self.assertEqual((king.revision, king.player_id, king.blob), (2, ALICE.subject, BLOB))
        self.assertEqual(king.source, "REPLAY_VERIFIED")
        self.assertEqual(king.originating_receipt_id, receipt.receipt_id)
        request = verifier.calls[0]
        self.assertEqual(request.principal, ALICE)
        self.assertEqual(request.challenge.king.blob, SEED_BLOB)
        self.assertEqual(request.original_blob, BLOB)
        self.assertEqual(request.input_evidence, INPUTS)
        self.assertEqual(request.binding_sha256, receipt.request_sha256)
        self.assertEqual(request.claim.identity, IDENTITY)
        self.assertEqual(store.get_challenge(ALICE, challenge.challenge_id), challenge)

    def test_loss_and_invalid_replay_never_promote(self):
        for outcome, status, http in ((ReplayOutcome.LOSS, "VERIFIED_LOSS", 200),
                                      (ReplayOutcome.INVALID, "UNVERIFIED", 422)):
            with self.subTest(outcome=outcome):
                store = self.store(MockVerifier(outcome))
                challenge = store.issue_challenge(ALICE, IDENTITY)
                receipt = store.submit_claim(ALICE, encode(envelope(challenge)), BLOB, INPUTS)
                self.assertEqual((receipt.status, receipt.http_status), (status, http))
                self.assertFalse(receipt.verified_win or receipt.promotion_applied)
                self.assertEqual(store.get_king(IDENTITY).revision, 1)

    def test_exception_timeout_and_malformed_verdict_are_fail_closed(self):
        def crash(*_):
            raise RuntimeError("secret /private/server/engine.bin")

        def timeout(*_):
            raise TimeoutError("sensitive timeout details")

        cases = [(crash, "verifier_exception"), (timeout, "verifier_timeout"),
                 (lambda *_: True, "invalid_verifier_response"),
                 (lambda req, _: {"verified": True, "win": True}, "invalid_verifier_response"),
                 (lambda req, _: ReplayVerdict("0" * 64, ReplayOutcome.WIN, "model", "v1"),
                  "invalid_verifier_response"),
                 (lambda req, _: ReplayVerdict(req.binding_sha256, "WIN", "model", "v1"),
                  "invalid_verifier_response")]
        for behavior, reason in cases:
            with self.subTest(reason=reason):
                store = self.store(MockVerifier(behavior=behavior))
                challenge = store.issue_challenge(ALICE, IDENTITY)
                receipt = store.submit_claim(ALICE, encode(envelope(challenge)), BLOB, INPUTS)
                self.assertEqual((receipt.status, receipt.reason, receipt.http_status),
                                 ("UNVERIFIED", reason, 503))
                self.assertNotIn(b"secret", receipt.to_json())
                self.assertNotIn(b"private", receipt.to_json())
                self.assertEqual(store.get_king(IDENTITY).revision, 1)

    def test_late_verifier_return_is_not_a_win_without_sleeping(self):
        ticks = iter([10.0, 11.0])
        store = self.store(MockVerifier(), monotonic=lambda: next(ticks), verification_timeout_s=1.0)
        challenge = store.issue_challenge(ALICE, IDENTITY)
        receipt = store.submit_claim(ALICE, encode(envelope(challenge)), BLOB, INPUTS)
        self.assertEqual(receipt.reason, "verifier_timeout")
        self.assertEqual(store.get_king(IDENTITY).revision, 1)

    def test_client_result_auth_and_path_fields_are_rejected(self):
        verifier = MockVerifier()
        store = self.store(verifier)
        challenge = store.issue_challenge(ALICE, IDENTITY)
        for field in ("win", "rank", "verified", "player_id", "auth", "path", "file_path",
                      "blob_path", "input_path", "original_blob", "input_evidence", "verifier"):
            with self.subTest(field=field):
                obj = envelope(challenge)
                obj[field] = True if field in ("win", "verified") else "../arbitrary/path"
                self.assert_error("unknown_or_missing_fields", lambda: store.submit_claim(
                    ALICE, encode(obj), BLOB, INPUTS))
        for parent in ("identity", "metadata"):
            obj = envelope(challenge)
            obj[parent]["path"] = "/etc/passwd"
            self.assert_error("unknown_or_missing_fields", lambda: store.submit_claim(
                ALICE, encode(obj), BLOB, INPUTS))
        self.assertEqual(verifier.calls, [])
        self.assertEqual(store.get_king(IDENTITY).revision, 1)

    def test_exact_field_presence_and_types(self):
        store = self.store(MockVerifier())
        challenge = store.issue_challenge(ALICE, IDENTITY)
        good = envelope(challenge)
        for field in good:
            with self.subTest(missing=field):
                obj = dict(good)
                obj.pop(field)
                self.assert_error("unknown_or_missing_fields", lambda: parse_claim_json(encode(obj)))
        bad_values = {"schema_version": [True, "1", 2, None],
                      "claim_id": [1, {}, "short", "../../etc/passwd"],
                      "nonce": [False, [], "x" * 97],
                      "challenge_id": [None, "short"],
                      "old_king_revision": [True, 0, -1, "1", 1.0, 9007199254740992],
                      "king_blob_sha256": [1, "F" * 64, "a" * 63],
                      "original_blob_format": [1, "renamed-format"],
                      "original_blob_sha256": [None, "zz" * 32],
                      "input_evidence_sha256": [False, []],
                      "metadata": [None, [], {"display_name": None}],
                      "identity": [None, [], "course"]}
        for field, values in bad_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    obj = dict(good)
                    obj[field] = value
                    with self.assertRaises(ContractError):
                        parse_claim_json(encode(obj))
        for field in good["identity"]:
            obj = envelope(challenge)
            obj["identity"][field] = []
            with self.subTest(identity=field), self.assertRaises(ContractError):
                parse_claim_json(encode(obj))
        self.assertEqual(parse_claim_json(encode(good)).to_dict(), good)

    def test_json_decoder_rejects_duplicate_nonfinite_huge_and_invalid_bytes(self):
        store = self.store()
        challenge = store.issue_challenge(ALICE, IDENTITY)
        raw = encode(envelope(challenge))
        malformed = [b"", b"\xff", b"{} trailing", b"[]", b"null", b"true", b'"text"',
                     b"1", b"[" * 1100 + b"0" + b"]" * 1100,
                     raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'),
                     raw.replace(b'"old_king_revision":1', b'"old_king_revision":' + b"9" * 5000),
                     raw.replace(b'"metadata":{', b'"metadata":{"display_name":"a",'),
                     b" " * (MAX_JSON_BYTES + 1)]
        for token in (b"NaN", b"Infinity", b"-Infinity", b"1e9999", b"1.25", b"-0.0"):
            malformed.append(raw.replace(b'"old_king_revision":1', b'"old_king_revision":' + token))
        for data in malformed:
            with self.subTest(size=len(data), preview=data[:30]), self.assertRaises(ContractError):
                parse_claim_json(data)
        for value in (raw.decode(), bytearray(raw), memoryview(raw), {}):
            self.assert_error("expected_bytes", lambda: parse_claim_json(value))

    def test_metadata_is_bounded_printable_display_only(self):
        store = self.store()
        challenge = store.issue_challenge(ALICE, IDENTITY)
        for name in ("", "x" * 65, "界" * 64, "line\nbreak", "../path", "C:\\path",
                     "\ud800", "\x00", 123, True):
            with self.subTest(name=repr(name)):
                obj = envelope(challenge)
                obj["metadata"] = {"display_name": name}
                with self.assertRaises(ContractError):
                    parse_claim_json(json.dumps(obj, ensure_ascii=True).encode())
        obj = envelope(challenge)
        obj["metadata"] = {}
        self.assertEqual(parse_claim_json(encode(obj)).metadata, GhostMetadata())
        self.assertEqual(GhostMetadata("测试车手").to_dict(), {"display_name": "测试车手"})

    def test_blobs_and_input_evidence_are_bounded_bytes_and_digest_bound(self):
        verifier = MockVerifier()
        store = self.store(verifier)
        challenge = store.issue_challenge(ALICE, IDENTITY)
        payload = encode(envelope(challenge))
        cases = [(BLOB + b"corrupt", INPUTS, "evidence_digest_mismatch"),
                 (BLOB, INPUTS + b"corrupt", "evidence_digest_mismatch"),
                 (BLOB.decode(), INPUTS, "expected_bytes"),
                 (BLOB, bytearray(INPUTS), "expected_bytes"),
                 (b"", INPUTS, "invalid_byte_length"),
                 (BLOB, b"", "invalid_byte_length"),
                 (b"x" * (MAX_BLOB_BYTES + 1), INPUTS, "invalid_byte_length"),
                 (BLOB, b"x" * (MAX_INPUT_EVIDENCE_BYTES + 1), "invalid_byte_length")]
        for blob, inputs, code in cases:
            with self.subTest(code=code):
                self.assert_error(code, lambda: store.submit_claim(ALICE, payload, blob, inputs))
        self.assertEqual(verifier.calls, [])
        self.assertEqual(store.get_king(IDENTITY).revision, 1)

    def test_all_challenge_bindings_must_match_server_snapshot(self):
        verifier = MockVerifier()
        store = self.store(verifier)
        challenge = store.issue_challenge(ALICE, IDENTITY)
        replacements = [("old_king_revision", 2), ("king_blob_sha256", "0" * 64),
                        ("identity", replace(IDENTITY, course_id="another-course").to_dict()),
                        ("identity", replace(IDENTITY, route_id="another-route").to_dict()),
                        ("identity", replace(IDENTITY, rules_sha256="0" * 64).to_dict()),
                        ("identity", replace(IDENTITY, physics_sha256="0" * 64).to_dict())]
        for field, value in replacements:
            with self.subTest(field=field, value=value):
                obj = envelope(challenge)
                obj[field] = value
                self.assert_error("challenge_binding_mismatch", lambda: store.submit_claim(
                    ALICE, encode(obj), BLOB, INPUTS), 409)
        obj = envelope(challenge)
        obj["challenge_id"] = "unknown-challenge-0000000000"
        self.assert_error("challenge_not_found", lambda: store.submit_claim(
            ALICE, encode(obj), BLOB, INPUTS), 404)
        self.assertEqual(verifier.calls, [])

    def test_same_digest_and_matching_format_are_not_verification(self):
        store = self.store()
        challenge = store.issue_challenge(ALICE, IDENTITY)
        receipt = store.submit_claim(ALICE, encode(envelope(challenge)), BLOB, INPUTS)
        self.assertEqual(receipt.original_blob_sha256, sha256(BLOB))
        self.assertEqual(receipt.status, "UNVERIFIED")
        self.assertFalse(receipt.verified_win)
        self.assertEqual(store.get_king(IDENTITY).blob, SEED_BLOB)

    def test_exact_duplicates_return_same_receipt_even_after_expiry(self):
        verifier = MockVerifier()
        store = self.store(verifier)
        challenge = store.issue_challenge(ALICE, IDENTITY, ttl_ms=50)
        obj = envelope(challenge)
        receipt = store.submit_claim(ALICE, encode(obj), BLOB, INPUTS)
        self.clock.value += 50
        duplicate = store.submit_claim(ALICE, json.dumps(obj, indent=2).encode(), BLOB, INPUTS)
        self.assertEqual(duplicate, receipt)
        self.assertEqual(duplicate.to_json(), receipt.to_json())
        self.assertEqual(len(verifier.calls), 1)
        self.assertEqual(store.get_king(IDENTITY).revision, 2)
        with self.assertRaises(FrozenInstanceError):
            duplicate.status = "hijacked"
        changed_copy = duplicate.to_dict()
        changed_copy["status"] = "hijacked"
        self.assertEqual(store.submit_claim(ALICE, encode(obj), BLOB, INPUTS), receipt)

    def test_idempotency_key_conflicts_and_cross_user_reuse_do_not_reverify(self):
        verifier = MockVerifier()
        store = self.store(verifier)
        challenge = store.issue_challenge(ALICE, IDENTITY)
        obj = envelope(challenge)
        receipt = store.submit_claim(ALICE, encode(obj), BLOB, INPUTS)
        for field, value in (("nonce", "other-nonce-000000000000"),
                             ("metadata", {"display_name": "Different"}),
                             ("original_blob_sha256", sha256(BLOB + b"other")),
                             ("input_evidence_sha256", sha256(INPUTS + b"other"))):
            modified = dict(obj)
            modified[field] = value
            blob = BLOB + b"other" if field == "original_blob_sha256" else BLOB
            inputs = INPUTS + b"other" if field == "input_evidence_sha256" else INPUTS
            self.assert_error("idempotency_conflict", lambda: store.submit_claim(
                ALICE, encode(modified), blob, inputs), 409)
        self.assert_error("idempotency_conflict", lambda: store.submit_claim(
            BOB, encode(obj), BLOB, INPUTS), 409)
        self.assertEqual(len(verifier.calls), 1)
        self.assertEqual(store.submit_claim(ALICE, encode(obj), BLOB, INPUTS), receipt)

    def test_nonce_replay_and_second_claim_for_challenge_are_rejected(self):
        verifier = MockVerifier(ReplayOutcome.LOSS)
        store = self.store(verifier)
        first = store.issue_challenge(ALICE, IDENTITY)
        obj = envelope(first)
        store.submit_claim(ALICE, encode(obj), BLOB, INPUTS)
        second = store.issue_challenge(ALICE, IDENTITY)
        replay = envelope(second, 2)
        replay["nonce"] = obj["nonce"]
        self.assert_error("nonce_replay", lambda: store.submit_claim(ALICE, encode(replay), BLOB, INPUTS), 409)
        self.assert_error("challenge_consumed", lambda: store.submit_claim(
            ALICE, encode(envelope(first, 3)), BLOB, INPUTS), 409)
        self.assertEqual(len(verifier.calls), 1)

    def test_nonce_scope_is_authenticated_user_not_global(self):
        verifier = MockVerifier(ReplayOutcome.LOSS)
        store = self.store(verifier)
        first = store.issue_challenge(ALICE, IDENTITY)
        second = store.issue_challenge(BOB, IDENTITY)
        a, b = envelope(first, 1), envelope(second, 2)
        b["nonce"] = a["nonce"]
        self.assertEqual(store.submit_claim(ALICE, encode(a), BLOB, INPUTS).status, "VERIFIED_LOSS")
        self.assertEqual(store.submit_claim(BOB, encode(b), BLOB, INPUTS).status, "VERIFIED_LOSS")

    def test_cancelled_and_expired_challenges_reject_before_verifier(self):
        verifier = MockVerifier()
        store = self.store(verifier)
        expired = store.issue_challenge(ALICE, IDENTITY, ttl_ms=1)
        self.clock.value += 1  # Expiry is exclusive: equality is already expired.
        self.assert_error("challenge_expired", lambda: store.submit_claim(
            ALICE, encode(envelope(expired)), BLOB, INPUTS), 410)
        cancelled = store.issue_challenge(ALICE, IDENTITY)
        store.cancel_challenge(ALICE, cancelled.challenge_id)
        store.cancel_challenge(ALICE, cancelled.challenge_id)
        self.assert_error("challenge_cancelled", lambda: store.submit_claim(
            ALICE, encode(envelope(cancelled, 2)), BLOB, INPUTS), 410)
        self.assertEqual(verifier.calls, [])
        self.assertEqual(store.get_king(IDENTITY).revision, 1)

    def test_clock_rollback_and_invalid_ttl_reject(self):
        store = self.store(MockVerifier())
        for ttl in (True, 0, -1, 3600001, "100", 1.0):
            self.assert_error("invalid_integer", lambda: store.issue_challenge(ALICE, IDENTITY, ttl_ms=ttl))
        challenge = store.issue_challenge(ALICE, IDENTITY)
        self.clock.value -= 1
        self.assert_error("challenge_expired", lambda: store.submit_claim(
            ALICE, encode(envelope(challenge)), BLOB, INPUTS), 410)

    def test_expiry_during_verification_is_rejected_and_receipt_is_stable(self):
        def expire(request, _):
            self.clock.value = request.challenge.expires_at_ms
            return ReplayVerdict(request.binding_sha256, ReplayOutcome.WIN, "model", "v1")

        store = self.store(MockVerifier(behavior=expire))
        challenge = store.issue_challenge(ALICE, IDENTITY)
        payload = encode(envelope(challenge))
        receipt = store.submit_claim(ALICE, payload, BLOB, INPUTS)
        self.assertEqual((receipt.status, receipt.reason, receipt.http_status),
                         ("REJECTED", "challenge_expired", 410))
        self.assertFalse(receipt.verified_win or receipt.promotion_applied)
        self.assertEqual(store.get_king(IDENTITY).revision, 1)
        self.assertEqual(store.submit_claim(ALICE, payload, BLOB, INPUTS), receipt)

    def test_cancellation_during_verification_is_rejected(self):
        entered, release = threading.Event(), threading.Event()

        def blocked(request, _):
            entered.set()
            if not release.wait(3):
                raise TimeoutError()
            return ReplayVerdict(request.binding_sha256, ReplayOutcome.WIN, "model", "v1")

        store = self.store(MockVerifier(behavior=blocked))
        challenge = store.issue_challenge(ALICE, IDENTITY)
        payload = encode(envelope(challenge))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(store.submit_claim, ALICE, payload, BLOB, INPUTS)
            try:
                self.assertTrue(entered.wait(3))
                self.assert_error("verification_in_progress", store.close, 409)
                store.cancel_challenge(ALICE, challenge.challenge_id)
            finally:
                release.set()
            receipt = future.result(timeout=3)
        self.assertEqual((receipt.status, receipt.reason), ("REJECTED", "challenge_cancelled"))
        self.assertEqual(store.get_king(IDENTITY).revision, 1)
        self.assertEqual(store.submit_claim(ALICE, payload, BLOB, INPUTS), receipt)

    def test_two_concurrent_challenges_only_one_can_take_same_revision(self):
        barrier = threading.Barrier(2, timeout=3)

        def simultaneous(request, _):
            barrier.wait()
            return ReplayVerdict(request.binding_sha256, ReplayOutcome.WIN, "model", "v1")

        verifier = MockVerifier(behavior=simultaneous)
        store = self.store(verifier)
        challenges = [store.issue_challenge(ALICE, IDENTITY), store.issue_challenge(BOB, IDENTITY)]
        blobs = [BLOB + b"alice", BLOB + b"bob"]
        payloads = [encode(envelope(challenges[i], i + 1, blobs[i])) for i in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(store.submit_claim, player, payloads[i], blobs[i], INPUTS)
                       for i, player in enumerate((ALICE, BOB))]
            receipts = [future.result(timeout=5) for future in futures]
        self.assertCountEqual([r.status for r in receipts], ["PROMOTED", "VERIFIED_WIN_STALE"])
        self.assertTrue(all(r.verified_win for r in receipts))
        self.assertEqual(sum(r.promotion_applied for r in receipts), 1)
        winner = next(i for i, r in enumerate(receipts) if r.promotion_applied)
        king = store.get_king(IDENTITY)
        self.assertEqual((king.revision, king.blob), (2, blobs[winner]))
        for i, player in enumerate((ALICE, BOB)):
            self.assertEqual(store.get_challenge(player, challenges[i].challenge_id), challenges[i])
            self.assertEqual(store.submit_claim(player, payloads[i], blobs[i], INPUTS), receipts[i])
        self.assertEqual(len(verifier.calls), 2)

    def test_concurrent_duplicate_waits_for_identical_receipt_and_one_verifier_call(self):
        entered, release, duplicate_waiting = threading.Event(), threading.Event(), threading.Event()

        def blocked(request, _):
            entered.set()
            if not release.wait(3):
                raise TimeoutError()
            return ReplayVerdict(request.binding_sha256, ReplayOutcome.WIN, "model", "v1")

        verifier = MockVerifier(behavior=blocked)
        store = self.store(verifier)
        challenge = store.issue_challenge(ALICE, IDENTITY)
        payload = encode(envelope(challenge))

        condition_wait = store._condition.wait

        def observed_wait(*args, **kwargs):
            duplicate_waiting.set()  # Prove the duplicate reaches the in-flight wait branch.
            return condition_wait(*args, **kwargs)

        store._condition.wait = observed_wait

        def duplicate():
            return store.submit_claim(ALICE, payload, BLOB, INPUTS)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(store.submit_claim, ALICE, payload, BLOB, INPUTS)
            try:
                self.assertTrue(entered.wait(3))
                second = pool.submit(duplicate)
                self.assertTrue(duplicate_waiting.wait(3))
            finally:
                release.set()
            a, b = first.result(timeout=3), second.result(timeout=3)
        self.assertEqual(a.to_json(), b.to_json())
        self.assertEqual(a.status, "PROMOTED")
        self.assertEqual(len(verifier.calls), 1)
        self.assertEqual(store.get_king(IDENTITY).revision, 2)

    def test_old_snapshot_win_is_recorded_without_overwriting_new_king(self):
        store = self.store(MockVerifier())
        old = store.issue_challenge(BOB, IDENTITY)
        first = store.issue_challenge(ALICE, IDENTITY)
        store.submit_claim(ALICE, encode(envelope(first)), BLOB, INPUTS)
        king = store.get_king(IDENTITY)
        receipt = store.submit_claim(BOB, encode(envelope(old, 2, BLOB + b"bob")), BLOB + b"bob", INPUTS)
        self.assertEqual((receipt.status, receipt.old_king_revision, receipt.resulting_king_revision),
                         ("VERIFIED_WIN_STALE", 1, 2))
        self.assertTrue(receipt.verified_win)
        self.assertFalse(receipt.promotion_applied)
        self.assertEqual(store.get_king(IDENTITY), king)
        new = store.issue_challenge(BOB, IDENTITY)
        receipt2 = store.submit_claim(BOB, encode(envelope(new, 3, BLOB + b"new")), BLOB + b"new", INPUTS)
        self.assertEqual((receipt2.status, receipt2.resulting_king_revision), ("PROMOTED", 3))

    def test_final_receipt_cannot_be_cancelled_retroactively(self):
        store = self.store(MockVerifier())
        challenge = store.issue_challenge(ALICE, IDENTITY)
        payload = encode(envelope(challenge))
        receipt = store.submit_claim(ALICE, payload, BLOB, INPUTS)
        self.assert_error("challenge_consumed", lambda: store.cancel_challenge(ALICE, challenge.challenge_id), 409)
        self.assertEqual(store.submit_claim(ALICE, payload, BLOB, INPUTS), receipt)
        self.assertEqual(store.get_king(IDENTITY).revision, 2)

    def test_receipt_and_king_update_are_one_rollback_transaction(self):
        store = self.store(MockVerifier())
        challenge = store.issue_challenge(ALICE, IDENTITY)
        store._db.execute("""CREATE TRIGGER synthetic_receipt_failure BEFORE UPDATE OF receipt_json
                            ON claims BEGIN SELECT RAISE(ABORT, 'synthetic receipt failure'); END""")
        self.assert_error("storage_unavailable", lambda: store.submit_claim(
            ALICE, encode(envelope(challenge)), BLOB, INPUTS), 503)
        row = store._db.execute("SELECT revision,player_id,blob FROM kings").fetchone()
        self.assertEqual(tuple(row), (1, SEED.subject, SEED_BLOB))
        self.assert_error("storage_unavailable", lambda: store.get_king(IDENTITY), 503)

    def test_corrupt_pinned_blob_is_rejected_before_verifier(self):
        verifier = MockVerifier()
        store = self.store(verifier)
        challenge = store.issue_challenge(ALICE, IDENTITY)
        store._db.execute("UPDATE challenges SET king_blob=? WHERE challenge_id=?",
                          (b"synthetic corruption", challenge.challenge_id))
        self.assert_error("stored_snapshot_corrupt", lambda: store.submit_claim(
            ALICE, encode(envelope(challenge)), BLOB, INPUTS), 503)
        self.assertEqual(store.get_king(IDENTITY).revision, 1)
        self.assertEqual(verifier.calls, [])

    def test_corrupt_current_blob_during_verification_cannot_be_replaced(self):
        def corrupt(request, _):
            store._db.execute("UPDATE kings SET blob=?", (b"synthetic corruption",))
            return ReplayVerdict(request.binding_sha256, ReplayOutcome.WIN, "model", "v1")

        store = self.store(MockVerifier(behavior=corrupt))
        challenge = store.issue_challenge(ALICE, IDENTITY)
        self.assert_error("stored_snapshot_corrupt", lambda: store.submit_claim(
            ALICE, encode(envelope(challenge)), BLOB, INPUTS), 503)
        row = store._db.execute("SELECT revision,player_id FROM kings").fetchone()
        self.assertEqual(tuple(row), (1, SEED.subject))

    def test_disk_restart_preserves_receipt_snapshot_king_and_nonce(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            path = str(Path(directory) / "synthetic-contract.sqlite3")
            first = self.store(MockVerifier(), path=path)
            challenge = first.issue_challenge(ALICE, IDENTITY)
            obj = envelope(challenge)
            receipt = first.submit_claim(ALICE, encode(obj), BLOB, INPUTS)
            first.close()
            verifier = MockVerifier()
            second = self.store(verifier, seeded=False, path=path)
            self.assertEqual(second.get_challenge(ALICE, challenge.challenge_id), challenge)
            self.assertEqual(second.get_king(IDENTITY).revision, 2)
            self.assertEqual(second.submit_claim(ALICE, encode(obj), BLOB, INPUTS).to_json(), receipt.to_json())
            newer = envelope(second.issue_challenge(ALICE, IDENTITY), 2)
            newer["nonce"] = obj["nonce"]
            self.assert_error("nonce_replay", lambda: second.submit_claim(ALICE, encode(newer), BLOB, INPUTS), 409)
            self.assertEqual(verifier.calls, [])
            second.close()

    def test_unconfigured_receipt_stays_unverified_after_restart_with_verifier(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            path = str(Path(directory) / "synthetic-contract.sqlite3")
            first = self.store(path=path)
            challenge = first.issue_challenge(ALICE, IDENTITY)
            payload = encode(envelope(challenge))
            receipt = first.submit_claim(ALICE, payload, BLOB, INPUTS)
            first.close()
            verifier = MockVerifier()
            second = self.store(verifier, seeded=False, path=path)
            self.assertEqual(second.submit_claim(ALICE, payload, BLOB, INPUTS), receipt)
            self.assertEqual(verifier.calls, [])
            self.assertEqual(second.get_king(IDENTITY).revision, 1)
            second.close()

    def test_interrupted_reservation_recovers_unverified_without_reexecution(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            path = str(Path(directory) / "synthetic-contract.sqlite3")
            first = self.store(path=path)
            challenge = first.issue_challenge(ALICE, IDENTITY)
            payload = encode(envelope(challenge))
            receipt = first.submit_claim(ALICE, payload, BLOB, INPUTS)
            interrupted = replace(receipt, reason="verification_interrupted")
            # Inject an on-disk post-reservation/pre-verdict crash fixture.
            first._db.execute("UPDATE claims SET state='VERIFYING',receipt_json=?",
                              (interrupted.to_json().decode("ascii"),))
            first.close()
            verifier = MockVerifier()
            second = self.store(verifier, seeded=False, path=path)
            self.assertEqual(second.submit_claim(ALICE, payload, BLOB, INPUTS), interrupted)
            self.assertEqual(second.get_king(IDENTITY).revision, 1)
            self.assertEqual(verifier.calls, [])
            second.close()

    def test_disk_store_rejects_second_active_owner(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            path = str(Path(directory) / "synthetic-contract.sqlite3")
            first = self.store(path=path)
            with self.assertRaises((ContractError, sqlite3.OperationalError)):
                GhostStore(path)
            self.assertEqual(first.get_king(IDENTITY).revision, 1)
            first.close()

    def test_server_configuration_rejects_relative_paths_and_nonfinite_deadlines(self):
        for path in ("relative.sqlite3", "file:memory?cache=shared", {}, "\x00/bad"):
            self.assert_error("trusted_absolute_database_path_required", lambda: GhostStore(path))
        for timeout in (True, 0, -1, 61, 10 ** 1000, float("nan"), float("inf"), "5"):
            self.assert_error("invalid_verification_timeout", lambda: GhostStore(verification_timeout_s=timeout))


if __name__ == "__main__":
    unittest.main(verbosity=2)
