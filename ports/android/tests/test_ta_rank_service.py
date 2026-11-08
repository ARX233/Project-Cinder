"""Offline synthetic protocol/store proof ONLY; no original engine or network."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from server.ta_rank_service import (Attempt, ContractError, MAX_DATE, Metadata, Partition, Run,
    SnapshotGuard, TimingStore, TrustedPrincipal, TrustedTimingVerdict, canonical,
    LocalPendingProposal, elapsed_ms, local_pending, local_upload_request, parse_attempt, sha256)

P = Partition("01"*32, "02"*32, 0, 0)
ALICE = TrustedPrincipal("alice", "synthetic-auth-adapter")
BOB = TrustedPrincipal("bob", "synthetic-auth-adapter")
INPUT = b"SYNTHETIC complete inputs; not original-engine replay evidence"
def bits(f):
    return "%08x" % struct.unpack("<I", struct.pack("<f", f))[0]
def request(i=1, *, partition=P, seconds=120.0, date=1000):
    metadata = Metadata((0x6E7E, 0x5CB8, 0, 0, 0), 1, 0, 3, 11, 17, 17, 0, 0, 0, 0)
    stages = (363,364,365,366,367,0,369,0,376,371,372,0,374,375,377)
    run = Run(bits(seconds), (bits(seconds*.25),bits(seconds*.75)),
              ("%08x" % stages[partition.course_id], "00000000", "0000001c", bits(1000), bits(1000000), "00000000"), 6,2,8,1,metadata)
    return canonical(Attempt(1, "%032x" % i, "%032x" % (i+10000), partition, date, sha256(INPUT), run).wire())

class SyntheticTimingVerifier:
    """Test-only protocol authority. NOT a real replay validator/anti-cheat."""
    def __init__(self, change=None):
        self.calls = 0
        self.change = change
    def verify(self, request, *, deadline_monotonic):
        self.calls += 1
        a = request.attempt
        verdict = TrustedTimingVerdict(request.binding_sha256, a.partition, a.run,
                     elapsed_ms(a.run.native_elapsed_bits), "synthetic-test-verifier", "test-v1")
        return self.change(verdict, request, deadline_monotonic) if self.change else verdict

class TimingContractTests(unittest.TestCase):
    def store(self, verifier=None, **kwargs):
        s = TimingStore(verifier=verifier, now_ms=lambda: 5000, **kwargs)
        self.addCleanup(s.close)
        return s
    def test_no_verifier_never_global_and_no_client_authority_fields(self):
        s = self.store()
        result = s.submit(ALICE, request(date=MAX_DATE), INPUT)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertFalse(result["server_verified"])
        self.assertEqual(s.snapshot(P)["rows"], [])
        for field in ("verified", "server_verified", "score_ms", "rank", "player_id", "owner", "auth", "path", "url"):
            obj = json.loads(request())
            obj[field] = True
            with self.subTest(field=field), self.assertRaises(ContractError):
                s.submit(ALICE, canonical(obj), INPUT)
    def test_auth_context_required(self):
        s = self.store(SyntheticTimingVerifier())
        for value in ({"subject":"alice"}, "alice", True, None):
            with self.assertRaises(ContractError): s.submit(value, request(), INPUT)
        self.assertEqual(s.snapshot(P)["rows"], [])
    def test_original_f32_boundaries(self):
        self.assertEqual(elapsed_ms(bits(1048.574)),1048574)
        self.assertEqual(elapsed_ms(bits(1048.575)),1048574)
        for f in (0,-1,float("nan"),float("inf"),1048.576,1199.999,1e30):
            with self.subTest(f=f), self.assertRaises(ContractError): elapsed_ms(bits(f))
    def test_strict_json_fields_and_types(self):
        good = json.loads(request())
        for key in good:
            obj = dict(good);del obj[key]
            with self.subTest(key=key),self.assertRaises(ContractError):parse_attempt(canonical(obj))
        bad = [b"",b"{}",b"[]",b"null",b"\xff",b'{"schema_version":1,"schema_version":1}', b'{"__proto__":{}}', b'{"n":NaN}', b'{"n":1.0}', b'{"n":9007199254740992}', b"x"*8193]
        for value in bad:
            with self.subTest(value=value[:50]), self.assertRaises(ContractError):parse_attempt(value)
        for key,value in (("schema_version",True),("attempt_id",1),("nonce","F"*32),("claimed_completed_at_ms",MAX_DATE+1)):
            obj=dict(good);obj[key]=value
            with self.assertRaises(ContractError):parse_attempt(canonical(obj))
        obj=dict(good);obj["partition"]=dict(obj["partition"],traffic=True)
        with self.assertRaises(ContractError):parse_attempt(canonical(obj))
    def test_run_gates_checkpoint_metadata_and_cohort(self):
        for key,value in (("native_result_state",7),("native_game_mode",8),("frontend_game_mode",4),("eligible",True),
                          ("checkpoint_bits",[bits(121)]),("native_elapsed_bits",bits(float("nan")))):
            obj=json.loads(request());obj["run"][key]=value
            with self.subTest(key=key),self.assertRaises(ContractError):parse_attempt(canonical(obj))
        for name in ([0xD800,0,0,0,0],[0,1,0,0,0],[0x110000,0,0,0,0]):
            obj=json.loads(request());obj["run"]["metadata"]["name"]=name
            with self.assertRaises(ContractError):parse_attempt(canonical(obj))
        for course in (5,7,11,15):
            with self.assertRaises(ContractError):replace(P,course_id=course)
    def test_shared_canonical_metadata_and_reserved_field_bounds(self):
        for key,value in (("model_id",247),("model_id",224),("model_id",231),("car_type",45),
                          ("class_id",47),("title_id",0),("title_id",5200)):
            obj=json.loads(request());obj["run"]["metadata"][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ContractError):parse_attempt(canonical(obj))
        for index in (1,5):
            obj=json.loads(request());obj["run"]["race_field"][index]="00000001"
            with self.assertRaises(ContractError):parse_attempt(canonical(obj))
        for car_type in (42,43,44):
            obj=json.loads(request());obj["run"]["metadata"].update(model_id=246,car_type=car_type,class_id=46,title_id=5149)
            self.assertEqual(parse_attempt(canonical(obj)).run.metadata.title_id,5149)
        # Above is typed-format acceptance only, never server/vehicle-policy authority.
    def test_evidence_digest_and_byte_limits(self):
        s=self.store(SyntheticTimingVerifier())
        for evidence in (b"",b"wrong",None,b"x"*(8*1024*1024+1)):
            with self.assertRaises(ContractError):s.submit(ALICE,request(),evidence)
        self.assertEqual(s.snapshot(P)["real_count"],0)
    def test_verified_result_uses_server_time_not_claimed_date(self):
        s=self.store(SyntheticTimingVerifier())
        r=s.submit(ALICE,request(date=MAX_DATE),INPUT)
        self.assertEqual(r["status"],"SERVER_VERIFIED")
        self.assertEqual(r["score_ms"],120000)
        self.assertEqual(s.snapshot(P)["rows"][0]["recorded_at_ms"],5000)
        self.assertTrue(r["board_changed"])
    def test_bound_verdict_mismatch_never_ranks(self):
        changes=[lambda v,q,d:True,
          lambda v,q,d:replace(v,binding_sha256="00"*32),
          lambda v,q,d:replace(v,partition=replace(P,traffic=1)),
          lambda v,q,d:replace(v,measured_ms=v.measured_ms+1),
          lambda v,q,d:replace(v,measured_ms=True),
          lambda v,q,d:replace(v,measured_run=replace(v.measured_run,native_elapsed_bits=bits(119))),
          lambda v,q,d:replace(v,measured_run=replace(v.measured_run,native_result_state=7)),
          lambda v,q,d:replace(v,verifier_id="")]
        for change in changes:
            s=self.store(SyntheticTimingVerifier(change))
            r=s.submit(ALICE,request(),INPUT)
            self.assertFalse(r["server_verified"])
            self.assertEqual(s.snapshot(P)["rows"],[])
    def test_verifier_error_late_invalid_clock(self):
        def fail(*args):raise RuntimeError("synthetic")
        s=self.store(SyntheticTimingVerifier(fail))
        self.assertEqual(s.submit(ALICE,request(),INPUT)["reason"],"verifier_error")
        for clock in ([0,6],[0,-1],[0,float("nan")]):
            values=iter(clock);s=self.store(SyntheticTimingVerifier(),monotonic=lambda:next(values),timeout_s=5)
            self.assertFalse(s.submit(ALICE,request(),INPUT)["server_verified"])
            self.assertEqual(s.snapshot(P)["rows"],[])
    def test_idempotency_nonce_and_threaded_duplicates(self):
        verifier=SyntheticTimingVerifier();s=self.store(verifier)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:s.submit(ALICE,request(),INPUT),range(12)))
        self.assertTrue(all(r==results[0] for r in results));self.assertEqual(verifier.calls,1)
        with self.assertRaises(ContractError):s.submit(ALICE,request(seconds=119),INPUT)
        obj=json.loads(request(2));obj["nonce"]=json.loads(request())["nonce"]
        with self.assertRaises(ContractError):s.submit(ALICE,canonical(obj),INPUT)
        self.assertEqual(s.snapshot(P)["real_count"],1)
    def test_strictly_faster_owner_and_newer_sequence_ties(self):
        s=self.store(SyntheticTimingVerifier())
        s.submit(ALICE,request(),INPUT)
        for i,t in ((2,120),(3,121)):
            self.assertFalse(s.submit(ALICE,request(i,seconds=t),INPUT)["board_changed"])
        self.assertTrue(s.submit(ALICE,request(4,seconds=119),INPUT)["board_changed"])
        s.submit(BOB,request(5,seconds=119,date=0),INPUT)
        rows=s.snapshot(P)["rows"]
        self.assertEqual([r["subject"] for r in rows],["bob","alice"])
        self.assertEqual([r["position"] for r in rows],[1,2])
    def test_top100_all_partition_keys(self):
        s=self.store(SyntheticTimingVerifier())
        for i in range(110):
            r=s.submit(TrustedPrincipal("p%d"%i,"synthetic-auth"),request(i+1),INPUT)
            self.assertTrue(r["server_verified"])
        snap=s.snapshot(P);self.assertEqual(snap["real_count"],100)
        self.assertEqual(snap["rows"][0]["subject"],"p109")
        for course in range(15):
            for traffic in range(2):
                if course in (5,7,11):continue
                p=replace(P,course_id=course,traffic=traffic)
                s.submit(ALICE,request(1000+course*2+traffic,partition=p),INPUT)
                self.assertGreaterEqual(s.snapshot(p)["real_count"],1)
        other=replace(P,physics_sha256="03"*32)
        self.assertEqual(s.snapshot(other)["rows"],[])
    def test_disk_reopen_and_interrupted_verification(self):
        path=str(Path(tempfile.mkdtemp(prefix="ta-service-",dir=os.environ["TMPDIR"]))/"reference.sqlite")
        class Interrupted:
            def verify(self,*args,**kwargs):raise SystemExit("synthetic crash after durable reservation")
        s=TimingStore(path,verifier=Interrupted(),now_ms=lambda:5000)
        with self.assertRaises(SystemExit):s.submit(ALICE,request(),INPUT)
        s.close()
        verifier=SyntheticTimingVerifier();s=TimingStore(path,verifier=verifier,now_ms=lambda:5000);self.addCleanup(s.close)
        r=s.submit(ALICE,request(),INPUT)
        self.assertFalse(r["server_verified"]);self.assertEqual(r["reason"],"verification_interrupted")
        self.assertEqual(verifier.calls,0);self.assertEqual(s.snapshot(P)["real_count"],0)
        s.submit(ALICE,request(2),INPUT);s.close()
        s=TimingStore(path,now_ms=lambda:5000);self.addCleanup(s.close)
        self.assertEqual(s.snapshot(P)["real_count"],1)
    def test_outbox_adapter_missing_proof_and_local_identity_never_auth(self):
        a=parse_attempt(request())
        pending=LocalPendingProposal("12"*16,a.attempt_id,a.partition,a.claimed_completed_at_ms,a.run)
        missing=local_upload_request(pending,nonce=a.nonce)
        self.assertEqual(missing["status"],"LOCAL_UNVERIFIED_EVIDENCE_MISSING")
        self.assertIsNone(missing["input_sha256"])
        self.assertIsNone(missing["upload_payload"])
        self.assertNotIn("owner",canonical(missing).decode())
        ready=local_upload_request(pending,nonce=a.nonce,input_evidence=INPUT)
        self.assertEqual(ready["source"],"LOCAL_UNVERIFIED")
        self.assertIsNone(ready["server_receipt"])
        self.assertNotIn("owner",canonical(ready["upload_payload"]).decode())
        self.assertEqual(parse_attempt(canonical(ready["upload_payload"])),a)
        s=self.store()
        self.assertFalse(s.submit(ALICE,canonical(ready["upload_payload"]),INPUT)["server_verified"])
        self.assertEqual(s.snapshot(P)["rows"],[])
        for bad in (b"",True,b"x"*(8*1024*1024+1)):
            with self.assertRaises(ContractError):local_upload_request(pending,nonce=a.nonce,input_evidence=bad)
        with self.assertRaises(FrozenInstanceError):pending.owner_local="34"*16
    def test_pending_and_snapshot_stale_guards(self):
        a=parse_attempt(request());pending=local_pending(a)
        self.assertEqual(pending["status"],"LOCAL_UNVERIFIED_PENDING_PROPOSAL")
        self.assertIsNone(pending["server_receipt"])
        with self.assertRaises(FrozenInstanceError):a.partition=P
        s=self.store(SyntheticTimingVerifier());s.submit(ALICE,request(),INPUT);snap=s.snapshot(P)
        guard=SnapshotGuard(P,10,snap["server_instance"])
        self.assertFalse(guard.accept(snap,request_generation=10))
        self.assertFalse(guard.accept(snap,request_generation=9,trusted_receipt_verified=True))
        self.assertTrue(guard.accept(snap,request_generation=10,trusted_receipt_verified=True))
        self.assertFalse(guard.accept(snap,request_generation=10,trusted_receipt_verified=True))
        s.submit(BOB,request(2),INPUT);new=s.snapshot(P)
        self.assertTrue(guard.accept(new,request_generation=10,trusted_receipt_verified=True))
        new["server_instance"]="00"*16
        self.assertFalse(guard.accept(new,request_generation=10,trusted_receipt_verified=True))

if __name__=="__main__":unittest.main(verbosity=2)
