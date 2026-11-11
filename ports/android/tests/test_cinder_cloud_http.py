import concurrent.futures
import hashlib
from http.client import HTTPConnection
import itertools
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

from server.cloud_service import BearerAccounts, CloudApplication, CloudHTTPServer
from server.cloud_ghosts import MAX_RECORD_BYTES
from server.device_registration import DeviceAccounts, set_approved
from server import community_timing
from test_ta_rank_service import INPUT, P, SyntheticTimingVerifier, request as timing_request


PHYSICS = "1" * 64
TOKEN_A, TOKEN_B, TOKEN_C = ("a" * 43, "b" * 43, "c" * 43)
ACCOUNTS = {TOKEN_A: "account-a", TOKEN_B: "account-b", TOKEN_C: "account-c"}


def _crc(record):
    struct.pack_into("<I", record, 24, 0)
    struct.pack_into("<I", record, 24, zlib.crc32(record))
    return bytes(record)


def _record(name="ＡＲＸ", area=0, timestamp=100, ta=None, step=3, count=2):
    raw_ramp, ramp = (18, 19) if area == 7 else (0, 2)
    stage, section, start, goal, mode = 123, 77, 0, 1000, 1
    if ta == 0:  # C1 inner, exact original field
        raw_ramp, ramp = 22, 23
        stage, section, start, goal, mode = 363, 28, 1535000, 15306708, 0
    elif ta == 10:  # 60 km Shuto Tokyo field
        raw_ramp, ramp = 32, 33
        stage, section, start, goal, mode = 374, 55, 3630000, 63428504, 0
    samples = [struct.pack("<4f4I3fI", start + (goal - start) * i / (count - 1),
                           2, 3, 4, 0, 0, 4, section, 0, 0, 0, 0)
               for i in range(count)]
    header = struct.pack("<7I", 0x070426A, 1, section, stage, 456, step, count)
    transposed = tuple(itertools.chain.from_iterable(zip(*samples)))
    delta = bytes((a - b) & 255 for a, b in zip(transposed, (0,) + transposed))
    payload = header + delta
    payload += struct.pack("<I", sum(payload))
    record = bytearray(248)
    record[:8] = b"W3GCROWN"
    struct.pack_into("<8I", record, 8, 1, 248, len(payload), 248 + len(payload), 0, 0, ramp, 0)
    struct.pack_into("<3I2fI", record, 40, stage, 0 if ta is not None else 1, section, start, goal, mode)
    struct.pack_into("<2I6f3I", record, 64, 1, 5, 1, 1, 1, 1, 1, 1, 6, 17, 17)
    record[108:172] = PHYSICS.encode("ascii")
    struct.pack_into("<Q", record, 172, timestamp)
    struct.pack_into("<12I", record, 184, 21, raw_ramp, 0, 0, 0, 0, 0, 143, 0, 0, 10, 1)
    name_bytes = name.encode("utf-16-le")
    record[232:232 + len(name_bytes)] = name_bytes
    record.extend(payload)
    return _crc(record)


def community_record(seconds=181.203, attempt=1, owner=2, traffic=0, date=1780000000000, model=21):
    record = bytearray(community_timing.ROW_BYTES)
    record[:68] = b"CTA1" + bytes.fromhex(community_timing.RULES + community_timing.PHYSICS)
    struct.pack_into("<II16s16sQfI", record, 68, 0, traffic, bytes([owner]) * 16, bytes([attempt]) * 16,
                     date, seconds, 1)
    struct.pack_into("<f", record, 124, 40.0)
    struct.pack_into("<3I2f5I", record, 152, 363, 0, 28, 1535000, 15306708, 0, 6, 2, 8, 1)
    struct.pack_into("<11I", record, 192, ord("Ａ"), ord("Ｒ"), ord("Ｘ"), 0, 0, 10, 1, model, 5, 17, 17)
    return bytes(record)


class CloudHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = self.server = self.worker = None
        self.addCleanup(self._stop)
        self._start()

    def _start(self, timing_verifier=None, retention_days=0, max_total=8, accounts=None):
        self.app = CloudApplication(self.directory.name, accounts or BearerAccounts(ACCOUNTS),
                                    timing_verifier=timing_verifier, max_per_subject=2, max_total=max_total,
                                    retention_days=retention_days)
        self.server = CloudHTTPServer(("127.0.0.1", 0), self.app)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.worker.start()

    def test_device_approval_gates_ghost_and_timing_and_can_be_revoked(self):
        self._stop()
        allowlist = Path(self.directory.name) / "devices.sqlite3"
        key = "e1" * 32
        device_id = hashlib.sha256(key.encode("ascii")).hexdigest()[:32]
        set_approved(allowlist, device_id, False)
        self._start(accounts=DeviceAccounts(allowlist))
        proof = {"Authorization": "CinderDevice " + key}
        ghost_path = "/v1/ghosts?physics_sha256=" + PHYSICS
        timing_path = ("/v1/ta/community?rules_sha256=" + community_timing.RULES +
                       "&physics_sha256=" + community_timing.PHYSICS + "&course_id=0&traffic=0")
        for path in ("/v1/device", ghost_path, timing_path):
            self.assertEqual(self.request("GET", path, headers=proof)[0], 403)
        set_approved(allowlist, device_id, True)
        status, payload, _ = self.request("GET", "/v1/device", headers=proof)
        self.assertEqual((status, payload), (200, {"approved": True, "device_id": device_id}))
        self.assertEqual(self.request("GET", ghost_path, headers=proof)[0], 200)
        self.assertEqual(self.request("GET", timing_path, headers=proof)[0], 200)
        self.assertEqual(self.request("GET", ghost_path)[0], 401)
        self.assertEqual(self.request("GET", ghost_path, headers={"Authorization": "CinderDevice " + device_id})[0], 401)
        set_approved(allowlist, device_id, False)
        self.assertEqual(self.request("POST", "/v1/ta/community", body=community_record(), headers=proof)[0], 403)
        self.assertEqual(self.request("POST", "/v1/ghosts?area=0", body=_record(), headers=proof)[0], 403)

    def _stop(self):
        if self.server:
            self.server.shutdown()
            self.worker.join(5)
            self.server.server_close()
            self.app.close()
            self.app = self.server = self.worker = None

    def request(self, method, path, *, token=TOKEN_A, body=None, headers=None):
        fields = {} if token is None else {"Authorization": "Bearer " + token}
        if body is not None:
            fields["Content-Type"] = "application/octet-stream"
        fields.update(headers or {})
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        try:
            connection.request(method, path, body, fields)
            response = connection.getresponse()
            payload = response.read()
            if response.getheader("Content-Type") == "application/json":
                payload = json.loads(payload)
            return response.status, payload, dict(response.getheaders())
        finally:
            connection.close()

    def upload(self, *, area=0, token=TOKEN_A, record=None, card_id=None):
        headers = {"X-Cinder-Card-ID": card_id} if card_id is not None else None
        return self.request("POST", f"/v1/ghosts?area={area}", token=token, headers=headers,
                            body=record if record is not None else _record(area=area))

    def page(self, *, token=TOKEN_B, more=""):
        status, obj, _ = self.request("GET", f"/v1/ghosts?physics_sha256={PHYSICS}{more}", token=token)
        self.assertEqual(200, status)
        return obj

    def test_complete_upload_list_download_restart_and_retry(self):
        raw = _record("Ａ　ＲＸ", area=7)
        status, view, _ = self.upload(area=7, record=raw)
        self.assertEqual(201, status)
        self.assertFalse(view["verified"])
        self.assertEqual("Ａ　ＲＸ", view["display_name"])
        self.assertNotIn("subject", view)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), view["sha256"])
        self.assertEqual([view], self.page(more="&area=7")["ghosts"])
        self.assertEqual([], self.page(more="&area=0")["ghosts"])
        status, downloaded, headers = self.request("GET", "/v1/ghosts/" + view["id"], token=TOKEN_B)
        self.assertEqual((200, raw), (status, downloaded))
        self.assertEqual(view["sha256"], headers["X-Content-SHA256"])
        self._stop()
        self._start()
        status, view_after_restart, _ = self.upload(area=7, record=raw)
        self.assertEqual((200, view), (status, view_after_restart))
        self.assertEqual([view], self.page()["ghosts"])

    def test_latest_per_account_pagination_snapshot_and_quota(self):
        _, a1, _ = self.upload(record=_record("Ａ１"))
        _, b1, _ = self.upload(token=TOKEN_B, record=_record("Ｂ１"))
        _, c1, _ = self.upload(token=TOKEN_C, record=_record("Ｃ１"))
        first = self.page(more="&limit=1")
        self.assertEqual([c1], first["ghosts"])
        self.assertIsNotNone(first["next_cursor"])
        _, a2, _ = self.upload(record=_record("Ａ２"))
        self.assertEqual(429, self.upload(record=_record("Ａ３"))[0])
        self.assertEqual(200, self.upload(record=_record("Ａ１"))[0])
        resumed = self.page(more="&limit=2&cursor=" + first["next_cursor"])
        self.assertEqual([b1, a1], resumed["ghosts"])
        self.assertIsNone(resumed["next_cursor"])
        self.assertEqual([a2, c1, b1], self.page()["ghosts"])
        self.assertEqual(200, self.request("GET", "/v1/ghosts/" + a1["id"])[0])

    def test_ghost_retention_expires_inactive_and_preserves_sequence(self):
        self._stop()
        self._start(retention_days=90, max_total=2)
        day = 86400 * 10**9
        with patch("server.cloud_ghosts.time.time_ns", return_value=100 * day):
            _, old, _ = self.upload(record=_record("Ａ１"))
        with patch("server.cloud_ghosts.time.time_ns", return_value=110 * day):
            _, kept, _ = self.upload(token=TOKEN_B, record=_record("Ｂ１"))
        before = self.page(more="&limit=1")["next_cursor"]
        with patch("server.cloud_ghosts.time.time_ns", return_value=120 * day):
            self.assertEqual(201, self.upload(token=TOKEN_C, record=_record("Ｃ１"))[0])
        self.assertEqual(404, self.request("GET", "/v1/ghosts/" + old["id"])[0])
        self.assertEqual(200, self.request("GET", "/v1/ghosts/" + kept["id"])[0])
        with patch("server.cloud_ghosts.time.time_ns", return_value=211 * day):
            self.app.ghosts.maintain()
            self.assertEqual([], self.page()["ghosts"])
            self.assertEqual(201, self.upload(record=_record("Ａ２"))[0])
        self.assertEqual([], self.page(more="&cursor=" + before)["ghosts"])

    def test_community_timing_cross_account_pb_and_verified_isolation(self):
        endpoint = "/v1/ta/community"
        query = f"?rules_sha256={community_timing.RULES}&physics_sha256={community_timing.PHYSICS}&course_id=0&traffic=0"
        raw = community_record()
        self.assertEqual(401, self.request("POST", endpoint, body=raw, token=None)[0])
        status, ack, _ = self.request("POST", endpoint, body=raw)
        self.assertEqual(200, status)
        self.assertEqual({"sha256": hashlib.sha256(raw).hexdigest(), "verified": False}, ack)
        self.assertEqual(200, self.request("POST", endpoint, body=raw)[0])
        self.assertEqual(200, self.request("POST", endpoint, body=community_record(190, 2))[0])
        fast = community_record(175, 3, 4)
        self.assertEqual(200, self.request("POST", endpoint, body=fast, token=TOKEN_B)[0])
        self.assertEqual(200, self.request("POST", endpoint, body=community_record(160, 4, traffic=1))[0])
        self._stop()
        self._start()
        status, board, _ = self.request("GET", endpoint + query, token=TOKEN_C)
        self.assertEqual(200, status)
        self.assertEqual(b"CTB1\x02\x00\x00\x00", board[:8])
        self.assertEqual(175.0, struct.unpack_from("<f", board, 8+116)[0])
        self.assertNotEqual(fast[76:92], board[8+76:8+92])
        self.assertEqual(raw[116:120], board[8+236+116:8+236+120])
        status, official, _ = self.request("GET", "/v1/ta/leaderboard" + query)
        self.assertEqual(200, status)
        self.assertEqual([], official["rows"])
        self.assertEqual(503, self.request("POST", "/v1/ta/attempts", body=raw)[0])

    def test_community_result_uses_original_model_class_and_card_best(self):
        endpoint = "/v1/ta/community/result"

        def finish(body, token=TOKEN_A):
            status, receipt, _ = self.request("POST", endpoint, body=body, token=token)
            self.assertEqual(status, 200)
            self.assertEqual(receipt["sha256"], hashlib.sha256(body).hexdigest())
            self.assertFalse(receipt["verified"])
            result = receipt["result"]
            return tuple(result[k] for k in ("course_best_ms", "car_best_ms", "personal_best_ms", "rank", "new_records"))

        self.assertEqual(finish(community_record(180, 1)), (180000, 180000, 180000, 1, 7))
        self.assertEqual(finish(community_record(177, 2, model=0), TOKEN_B), (177000, 177000, 177000, 1, 7))
        self.assertEqual(finish(community_record(190, 3, model=22), TOKEN_C), (177000, 180000, 190000, 3, 4))
        self.assertEqual(finish(community_record(185, 4, model=22)), (177000, 180000, 180000, 0, 0))
        self.assertEqual(finish(community_record(175, 5, traffic=1)), (175000, 175000, 175000, 1, 7))
        self._stop()
        self._start()
        self.assertEqual(finish(community_record(179, 6, model=22)), (177000, 179000, 179000, 2, 6))

    def test_community_crown_time_changes_only_on_a_faster_new_holder(self):
        path = "/v1/ta/community"
        first_date = 1780000000000
        for token, seconds, attempt, owner, traffic in (
                (TOKEN_A, 180, 1, 2, 0),
                (TOKEN_A, 170, 2, 2, 0),
                (TOKEN_B, 170, 3, 4, 0),
                (TOKEN_B, 160, 4, 4, 1)):
            body = community_record(seconds, attempt, owner, traffic, first_date + attempt)
            self.assertEqual(200, self.request("POST", path, body=body, token=token)[0])
        database = Path(self.directory.name) / "timing-community.sqlite3"
        with sqlite3.connect(database) as state:
            self.assertEqual(("account-a", first_date + 1), state.execute(
                "SELECT subject, acquired_at FROM community_crown_v1 WHERE course=0").fetchone())
        body = community_record(169, 5, 4, date=first_date + 5)
        self.assertEqual(200, self.request("POST", path, body=body, token=TOKEN_B)[0])
        self._stop()
        self._start()
        with sqlite3.connect(database) as state:
            self.assertEqual(("account-b", first_date + 5), state.execute(
                "SELECT subject, acquired_at FROM community_crown_v1 WHERE course=0").fetchone())

    def test_community_ghost_crown_is_shared_by_web_and_game(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cinder_site", Path(__file__).parents[1] / "site/app.py")
        site = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(site)
        site.GHOSTS_DB = str(Path(self.directory.name) / "shared-ghosts.sqlite3")
        site.CARS = site.load_cars(Path(__file__).parents[1] / "site/cars.json")
        board = "/v1/ghosts/crowns?physics_sha256=" + PHYSICS
        claim = "/v1/ghosts/crowns?area=0&previous="
        seed = "0" * 32
        card = {"X-Cinder-Card-ID": "a" * 32}
        first, next_record = _record(), _record(name="ＢＢ")
        self.assertEqual(self.request("GET", board)[1], b"\0\0")
        self.assertTrue(site.ghost_kings()[0]["idle"])
        self.assertEqual(self.upload(record=first)[0], 201)
        self.assertEqual(self.request("GET", board)[1], b"\0\0")
        self.assertEqual(self.request("POST", claim + seed, body=first)[0], 400)
        self.assertEqual(self.request("POST", claim + seed, body=_record(ta=0), headers=card)[0], 422)
        status, king, _ = self.request("POST", claim + seed, body=first, headers=card)
        self.assertEqual(status, 200)
        self.assertFalse(king["verified"])
        self.assertEqual(self.request("POST", claim + seed, body=first, headers=card)[1], king)
        self.assertEqual(self.request("GET", board, headers=card)[1],
                         struct.pack("<3B16sI", 1, 1, 0, bytes.fromhex(king["id"]), len(first)) + first)
        self.assertEqual(self.request("GET", board, token=TOKEN_B, headers=card)[1][0], 0)
        self.assertEqual(self.request("GET", board.replace(PHYSICS, "f" * 64))[1],
                         struct.pack("<3B16sI", 0, 1, 0, bytes.fromhex(king["id"]), 0))
        self.assertEqual((site.ghost_kings()[0]["id"], site.ghost_kings()[0]["name"]), (king["id"], "ＡＲＸ"))
        self.assertEqual(self.request("POST", claim + seed, token=TOKEN_B, body=next_record, headers=card)[0], 409)
        wrong_route = bytearray(next_record)
        struct.pack_into("<I", wrong_route, 36, 1)
        self.assertEqual(self.request("POST", claim + king["id"], token=TOKEN_B,
                                      body=_crc(wrong_route), headers=card)[0], 422)
        status, winner, _ = self.request("POST", claim + king["id"], token=TOKEN_B, body=next_record, headers=card)
        self.assertEqual(status, 200)
        self.assertNotEqual(king["id"], winner["id"])
        self.assertEqual(self.request("POST", claim + king["id"], token=TOKEN_C, body=first, headers=card)[0], 409)
        self._stop()
        self._start()
        self.assertEqual(self.request("GET", board, token=TOKEN_B, headers=card)[1][23:], next_record)
        self.assertEqual((site.ghost_kings()[0]["id"], site.ghost_kings()[0]["name"]), (winner["id"], "ＢＢ"))

        def try_win(name):
            return self.request("POST", claim + winner["id"], body=_record(name=name), headers=card)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as workers:
            responses = list(workers.map(try_win, ("ＣＣ", "ＤＤ")))
        self.assertEqual(sorted(response[0] for response in responses), [200, 409])
        new_id = next(response[1]["id"] for response in responses if response[0] == 200)
        self.assertEqual(site.ghost_kings()[0]["id"], new_id)


    def test_archive_search_and_distinct_card_discovery(self):
        card_a, card_b = "1" * 32, "2" * 32
        _, a, _ = self.upload(record=_record("ルージュ"), card_id=card_a)
        _, b, _ = self.upload(record=_record("ホーク"), card_id=card_b)
        self.assertNotIn("card_id", a)
        self.assertEqual([b], self.page(more="&limit=1")["ghosts"])
        self.assertEqual([b, a], self.page(more="&others=1")["ghosts"])
        self.assertEqual([], self.page(token=TOKEN_A, more="&others=1")["ghosts"])
        self.assertEqual([a], self.page(more="&limit=1&name_hex=" + "ージ".encode().hex())["ghosts"])
        self.assertEqual([a], self.page(more="&id=" + a["id"])["ghosts"])
        self.assertEqual([], self.page(more="&name_hex=" + "ROUGE".encode().hex())["ghosts"])
        self.assertEqual(400, self.request("GET", f"/v1/ghosts?physics_sha256={PHYSICS}&name_hex=ff")[0])
        self.assertEqual(409, self.upload(record=_record("ルージュ"), card_id=card_b)[0])

    def test_time_attack_is_a_separate_shared_course(self):
        key = "1" * 32
        _, arcade, _ = self.upload(record=_record(), card_id=key)
        raw = _record(ta=0)
        status, ta, _ = self.upload(record=raw, card_id=key)
        self.assertEqual(201, status)
        self.assertEqual(22, ta["raw_ramp"])
        self.assertFalse(ta["verified"])
        self.assertEqual([ta, arcade], self.page(more="&area=0")["ghosts"])
        self.assertEqual(400, self.upload(area=7, record=raw, card_id=key)[0])
        invalid = bytearray(raw)
        struct.pack_into("<f", invalid, 56, 15306709)
        self.assertEqual(400, self.upload(record=_crc(invalid), card_id=key)[0])

    def test_only_shuto_tokyo_shared_field_allows_a_longer_trail(self):
        raw = _record(ta=10, step=12, count=4401)
        self.assertEqual(201, self.upload(area=2, record=raw)[0])
        self.assertEqual(400, self.upload(record=_record(ta=0, step=12, count=4401))[0])
        self.assertEqual(400, self.upload(area=2, record=_record(ta=10, step=12, count=6002))[0])

    def test_authenticated_private_defense_snapshot_and_nonce(self):
        key, other = "1" * 32, "2" * 32
        _, a, _ = self.upload(record=_record("ルージュ"), card_id=key)
        _, b, _ = self.upload(record=_record("ホーク"), card_id=other)
        path = "/v1/ghosts/" + a["id"] + "/battles"
        defense = "/v1/ghosts/defense?card_id=" + key
        for n in range(1, 11):
            won = n % 2
            report = struct.pack("<16sBBHi10s", bytes([n]) * 16, won, 21, 740,
                                 -15 if won else 5, "ＷＩＮ".encode("utf-16-le"))
            self.assertEqual(201, self.request("POST", path, token=TOKEN_B, body=report)[0])
            self.assertEqual(200, self.request("POST", path, token=TOKEN_B, body=report)[0])
        self.assertEqual(401, self.request("POST", path, token=None, body=report)[0])
        self.assertEqual(409, self.request("POST", path, token=TOKEN_A, body=report)[0])
        self.assertEqual(409, self.request("POST", "/v1/ghosts/" + b["id"] + "/battles",
                                           token=TOKEN_B, body=report)[0])
        status, result, _ = self.request("GET", defense)
        self.assertEqual((200, 10, 5, False), (status, result["battles"], result["wins"], result["verified"]))
        self.assertEqual([5, -15] * 4, [row["gap"] for row in result["recent"]])
        self.assertTrue(all(row["area"] == 0 and row["hp"] == 740 and row["name"] == "ＷＩＮ"
                            for row in result["recent"]))
        for target, token in ((defense, TOKEN_B), ("/v1/ghosts/defense?card_id=" + other, TOKEN_A)):
            self.assertEqual({"battles": 0, "wins": 0, "recent": [], "verified": False},
                             self.request("GET", target, token=token)[1])
        self.assertEqual(401, self.request("GET", defense, token=None)[0])
        self._stop()
        self._start()
        self.assertEqual(result, self.request("GET", defense)[1])

    def test_idempotent_concurrent_retries(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.upload(), range(8)))
        self.assertEqual([200] * 7 + [201], sorted(r[0] for r in results))
        self.assertEqual(1, len({r[1]["id"] for r in results}))

    def test_auth_and_authority_boundaries(self):
        self.assertEqual((401, {"error": "authentication_required"}),
                         self.request("GET", f"/v1/ghosts?physics_sha256={PHYSICS}", token=None)[:2])
        self.assertEqual(401, self.upload(token="z" * 43)[0])
        self.assertEqual(400, self.request("POST", "/v1/ghosts?area=0&subject=other", body=_record())[0])
        capabilities = self.request("GET", "/v1/capabilities", token=None)[1]
        self.assertTrue(capabilities["ghost_sharing"])
        self.assertFalse(capabilities["world_crown_verified"])
        self.assertFalse(capabilities["ta_verifier_available"])
        self.assertEqual(404, self.request("POST", "/v1/ghost-crowns", body=_record())[0])
        self.assertEqual((503, {"error": "timing_verifier_unconfigured"}),
                         self.request("POST", "/v1/ta/attempts", body=b"fake")[:2])
        ta = (f"/v1/ta/leaderboard?rules_sha256={'2' * 64}&physics_sha256={PHYSICS}"
              "&course_id=0&traffic=0")
        self.assertEqual(401, self.request("GET", ta, token=None)[0])
        status, timing, _ = self.request("GET", ta)
        self.assertEqual((200, "EMPTY_NO_AUTHORITY_CLAIM", []), (status, timing["status"], timing["rows"]))

    def test_same_credential_works_for_both_modes_with_injected_timing_verifier(self):
        self._stop()
        verifier = SyntheticTimingVerifier()
        self._start(timing_verifier=verifier)
        self.assertTrue(self.request("GET", "/v1/capabilities", token=None)[1]["ta_verifier_available"])
        self.assertEqual(201, self.upload()[0])
        packet = timing_request()
        wire = struct.pack(">I", len(packet)) + packet + INPUT
        status, receipt, _ = self.request("POST", "/v1/ta/attempts", body=wire)
        self.assertEqual(200, status)
        self.assertTrue(receipt["server_verified"])
        self.assertEqual(1, verifier.calls)
        path = (f"/v1/ta/leaderboard?rules_sha256={P.rules_sha256}&physics_sha256={P.physics_sha256}"
                f"&course_id={P.course_id}&traffic={P.traffic}")
        self.assertEqual("account-a", self.request("GET", path, token=TOKEN_B)[1]["rows"][0]["subject"])

    def test_bad_or_unbounded_transport_and_record_are_refused(self):
        raw = _record()
        self.assertEqual(413, self.request("POST", "/v1/ghosts?area=0", body=raw,
                                           headers={"Content-Length": str(MAX_RECORD_BYTES + 1)})[0])
        self.assertEqual(415, self.request("POST", "/v1/ghosts?area=0", body=raw,
                                           headers={"Content-Type": "application/json"})[0])
        self.assertEqual(400, self.upload(record=raw[:-1])[0])
        self.assertEqual(400, self.upload(record=raw[:-1] + bytes([raw[-1] ^ 1]))[0])
        self.assertEqual(400, self.upload(record=_record("Ａ\x00Ｂ"))[0])
        self.assertEqual(400, self.upload(area=7, record=raw)[0])
        self.assertEqual(400, self.request("GET", "/v1/ghosts/../../etc/passwd")[0])
        self.assertEqual(400, self.request("GET", f"/v1/ghosts?physics_sha256={PHYSICS}&limit=100")[0])
        self.assertEqual(400, self.request("GET", f"/v1/ghosts?physics_sha256={PHYSICS}&cursor=9.10")[0])
        self.assertEqual([], self.page()["ghosts"])

    def test_credential_file_mode_and_no_nonlocal_cleartext(self):
        path = Path(self.directory.name) / "credentials.json"
        path.write_text(json.dumps(ACCOUNTS), encoding="utf-8")
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            BearerAccounts.from_file(path)
        path.chmod(0o600)
        self.assertEqual("account-a", BearerAccounts.from_file(path).authenticate("Bearer " + TOKEN_A).subject)
        with self.assertRaises(ValueError):
            CloudHTTPServer(("0.0.0.0", 0), self.app)


if __name__ == "__main__":
    unittest.main()
