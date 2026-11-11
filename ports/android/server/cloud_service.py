"""Run Cinder's shared Ghost and timing HTTP service with python -m server.cloud_service."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import ssl
import stat
import threading
import time
from urllib.parse import parse_qsl, urlsplit

from . import ta_rank_service as timing
from . import community_timing as community
from .cloud_ghosts import BATTLE_BYTES, GHOST_ID, MAX_RECORD_BYTES, SHA256, SharedGhosts, decode_query_name
from .ghost_service import ContractError, TrustedPrincipal
from .device_registration import DeviceAccounts


_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}", re.ASCII)
_SMALL_INTEGER = re.compile(r"0|[1-9][0-9]{0,2}", re.ASCII)
_CREDENTIAL_BYTES = 256 * 1024
_LOG = logging.getLogger("cinder.cloud")


class BearerAccounts:
    """Operator-provisioned credentials shared by every mode. Only token digests are retained."""
    challenge = "Bearer"

    def __init__(self, accounts):
        if type(accounts) is not dict or not accounts:
            raise ValueError("empty or invalid credential map")
        self._subjects = {}
        for token, subject in accounts.items():
            if type(token) is not str or not _TOKEN.fullmatch(token):
                raise ValueError("invalid token in credential map")
            principal = TrustedPrincipal(subject, "cinder-bearer-v1")
            self._subjects[hashlib.sha256(token.encode("ascii")).digest()] = principal

    @classmethod
    def from_file(cls, path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077):
                raise ValueError("credential file must be owned and private (mode 0600)")
            payload = source.read(_CREDENTIAL_BYTES + 1)
        if len(payload) > _CREDENTIAL_BYTES:
            raise ValueError("credential file too large")

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate credential")
                result[key] = value
            return result
        try:
            return cls(json.loads(payload, object_pairs_hook=pairs))
        except (ValueError, RecursionError):
            raise ValueError("invalid credential file") from None

    def authenticate(self, authorization):
        if authorization is not None and authorization[:7].lower() == "bearer ":
            token = authorization[7:]
            if _TOKEN.fullmatch(token):
                principal = self._subjects.get(hashlib.sha256(token.encode("ascii")).digest())
                if principal is not None:
                    return principal
        raise ContractError("authentication_required", 401)


class CloudApplication:
    """One identity service with isolated Ghost and TA stores in an owned state directory."""
    def __init__(self, state_dir, accounts, *, timing_verifier=None,
                 max_per_subject=1024, max_total=16384, retention_days=0):
        state = Path(state_dir).resolve(strict=True)
        if not state.is_dir():
            raise ValueError("state directory required")
        self.accounts = accounts
        self.state = state
        self.retention_days = retention_days
        self.ghosts = SharedGhosts(str(state / "shared-ghosts.sqlite3"),
                                  max_per_subject=max_per_subject, max_total=max_total, retention_days=retention_days)
        try:
            self.timing = timing.TimingStore(str(state / "timing.sqlite3"), verifier=timing_verifier)
            try:
                self.community = community.CommunityTiming(state / "timing-community.sqlite3")
            except BaseException:
                self.timing.close()
                raise
        except BaseException:
            self.ghosts.close()
            raise
        self.timing_available = timing_verifier is not None

    def capabilities(self):
        return {"schema_version": 1, "ghost_sharing": True, "world_crown_verified": False,
                "ghost_community_crowns": True, "ghost_search": True, "ghost_defense_reported": True, "ta_leaderboard": True,
                "ta_community": True, "ta_verifier_available": self.timing_available}

    def write_guard(self):
        if shutil.disk_usage(self.state).free < 512 * 1024 * 1024:
            raise ContractError("storage_reserve", 503)

    def close(self):
        try:
            self.community.close()
        finally:
            try:
                self.timing.close()
            finally:
                self.ghosts.close()


def _small(value, low, high, field):
    if value is None or not _SMALL_INTEGER.fullmatch(value) or not low <= int(value) <= high:
        raise ContractError("invalid_" + field)
    return int(value)


def _sha(value, field):
    if value is None or not SHA256.fullmatch(value):
        raise ContractError("invalid_" + field)
    return value


def _fields(query, *, required=(), optional=()):
    if not set(required) <= query.keys() or query.keys() - set(required) - set(optional):
        raise ContractError("unknown_or_missing_query_fields")


class _Handler(BaseHTTPRequestHandler):
    server_version = "CinderCloud/1"
    sys_version = ""

    def log_message(self, _format, *args):
        # Never emit credentials, IDs, names, request URIs or uploaded content.
        return

    def _one_header(self, key):
        values = self.headers.get_all(key, ())
        if len(values) > 1:
            raise ContractError("duplicate_header")
        return values[0] if values else None

    def _body(self, limit):
        if self.headers.get_all("Transfer-Encoding") or self.headers.get_all("Content-Encoding"):
            raise ContractError("unsupported_content_encoding")
        if self._one_header("Content-Type") != "application/octet-stream":
            raise ContractError("unsupported_content_type", 415)
        count = self._one_header("Content-Length")
        if count is None:
            raise ContractError("content_length_required", 411)
        if not re.fullmatch(r"[1-9][0-9]{0,8}", count):
            raise ContractError("invalid_content_length")
        size = int(count)
        if size > limit:
            raise ContractError("request_too_large", 413)
        body = self.rfile.read(size)
        if len(body) != size:
            raise ContractError("incomplete_body")
        return body

    def _target(self):
        if (len(self.path) > 768 or not self.path.startswith("/") or self.path.startswith("//")
                or "#" in self.path or "%" in self.path or not self.path.isascii()):
            raise ContractError("invalid_request_target")
        path = urlsplit(self.path)
        try:
            pairs = parse_qsl(path.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8) if path.query else []
        except ValueError:
            raise ContractError("invalid_query") from None
        query = dict(pairs)
        if len(query) != len(pairs):
            raise ContractError("duplicate_query_field")
        return path.path, query

    def _send(self, status, content, media, headers=None):
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def _json(self, status, obj, headers=None):
        self._send(status, json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii"),
                   "application/json", headers)

    def _dispatch(self, method):
        path, query = self._target()
        app = self.server.app
        if path == "/v1/capabilities" and method == "GET":
            _fields(query)
            self._json(200, app.capabilities())
            return

        principal = app.accounts.authenticate(self._one_header("Authorization"))
        if path == "/v1/device" and method == "GET" and principal.auth_source == "cinder-device-v1":
            _fields(query)
            self._json(200, {"approved": True, "device_id": principal.subject.removeprefix("device:")})
            return
        if method == "POST":
            app.write_guard()
        if path == "/v1/ghosts" and method == "POST":
            _fields(query, required=("area",))
            area = _small(query["area"], 0, 7, "area")
            view, created = app.ghosts.publish(principal, area, self._body(MAX_RECORD_BYTES),
                                               self._one_header("X-Cinder-Card-ID"))
            self._json(201 if created else 200, view)
        elif path == "/v1/ghosts" and method == "GET":
            _fields(query, required=("physics_sha256",),
                    optional=("area", "limit", "cursor", "name_hex", "id", "others"))
            physics = _sha(query["physics_sha256"], "physics_sha256")
            area = _small(query["area"], 0, 7, "area") if "area" in query else None
            limit = _small(query.get("limit", "20"), 1, 50, "limit")
            ghost_id = query.get("id")
            if ghost_id is not None and not GHOST_ID.fullmatch(ghost_id):
                raise ContractError("invalid_ghost_id")
            if "others" in query and query["others"] != "1":
                raise ContractError("invalid_others")
            name = decode_query_name(query["name_hex"]) if "name_hex" in query else None
            self._json(200, app.ghosts.list(physics, area, limit, query.get("cursor"), name=name,
                                           ghost_id=ghost_id,
                                           exclude_subject=principal.subject if "others" in query else None))
        elif path == "/v1/ghosts/crowns" and method == "GET":
            _fields(query, required=("physics_sha256",))
            physics = _sha(query["physics_sha256"], "physics_sha256")
            card_id = self._one_header("X-Cinder-Card-ID")
            if card_id is not None and not GHOST_ID.fullmatch(card_id):
                raise ContractError("invalid_card_id")
            self._send(200, app.ghosts.crowns(physics, principal, card_id), "application/octet-stream")
        elif path == "/v1/ghosts/crowns" and method == "POST":
            _fields(query, required=("area", "previous"))
            area = _small(query["area"], 0, 7, "area")
            self._json(200, app.ghosts.claim_crown(principal, area, query["previous"],
                       self._body(MAX_RECORD_BYTES), self._one_header("X-Cinder-Card-ID")))
        elif path == "/v1/ghosts/defense" and method == "GET":
            _fields(query, required=("card_id",))
            if not GHOST_ID.fullmatch(query["card_id"]):
                raise ContractError("invalid_card_id")
            self._json(200, app.ghosts.defense(principal, query["card_id"]))
        elif path.startswith("/v1/ghosts/") and path.endswith("/battles") and method == "POST":
            _fields(query)
            ghost_id = path.removeprefix("/v1/ghosts/").removesuffix("/battles")
            if not GHOST_ID.fullmatch(ghost_id):
                raise ContractError("invalid_ghost_id")
            created = app.ghosts.battle(principal, ghost_id, self._body(BATTLE_BYTES))
            self._json(201 if created else 200, {"id": ghost_id, "verified": False})
        elif path.startswith("/v1/ghosts/") and method == "GET":
            _fields(query)
            ghost_id = path.removeprefix("/v1/ghosts/")
            if not GHOST_ID.fullmatch(ghost_id):
                raise ContractError("invalid_ghost_id")
            record, digest = app.ghosts.download(ghost_id)
            self._send(200, record, "application/octet-stream",
                       {"ETag": '"' + digest + '"', "X-Content-SHA256": digest})
        elif path in ("/v1/ta/community", "/v1/ta/community/result") and method == "POST":
            _fields(query)
            self._json(200, app.community.submit(principal.subject, self._body(community.ROW_BYTES),
                                                 include_result=path.endswith("/result")))
        elif path == "/v1/ta/community" and method == "GET":
            _fields(query, required=("rules_sha256", "physics_sha256", "course_id", "traffic"))
            course, traffic = community.partition(query["rules_sha256"], query["physics_sha256"],
                                                  _small(query["course_id"], 0, 14, "course_id"),
                                                  _small(query["traffic"], 0, 1, "traffic"))
            self._send(200, app.community.board(course, traffic), "application/octet-stream")
        elif path == "/v1/ta/leaderboard" and method == "GET":
            _fields(query, required=("rules_sha256", "physics_sha256", "course_id", "traffic"))
            partition = timing.Partition(
                _sha(query["rules_sha256"], "rules_sha256"),
                _sha(query["physics_sha256"], "physics_sha256"),
                _small(query["course_id"], 0, 14, "course_id"),
                _small(query["traffic"], 0, 1, "traffic"))
            self._json(200, app.timing.snapshot(partition))
        elif path == "/v1/ta/attempts" and method == "POST":
            _fields(query)
            if not app.timing_available:
                raise ContractError("timing_verifier_unconfigured", 503)
            body = self._body(4 + timing.MAX_JSON_BYTES + timing.MAX_INPUT_BYTES)
            n = int.from_bytes(body[:4], "big")
            if not 1 <= n <= timing.MAX_JSON_BYTES or len(body) <= n + 4:
                raise ContractError("invalid_timing_attempt_length")
            receipt = app.timing.submit(timing.TrustedPrincipal(principal.subject, principal.auth_source),
                                        body[4:4+n], body[4+n:])
            self._json(200 if receipt["server_verified"] else 422, receipt)
        else:
            raise ContractError("not_found", 404)

    def _handle(self, method):
        try:
            try:
                self._dispatch(method)
            except ContractError as exc:
                headers = {"WWW-Authenticate": self.server.app.accounts.challenge} if exc.http_status == 401 else None
                self._json(exc.http_status, {"error": exc.code}, headers)
            except timing.ContractError as exc:
                self._json(400, {"error": str(exc)})
            except sqlite3.Error:
                _LOG.error("storage unavailable")
                self._json(503, {"error": "storage_unavailable"})
            except TimeoutError:
                self._json(408, {"error": "request_timeout"})
        except OSError:
            return

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


class CloudHTTPServer(ThreadingHTTPServer):
    """Bound concurrent connections before starting worker threads."""
    daemon_threads = False
    request_queue_size = 32

    def __init__(self, address, app, *, tls=None, workers=16, timeout=8):
        if not ipaddress.ip_address(address[0]).is_loopback and tls is None:
            raise ValueError("TLS required outside loopback")
        if not 1 <= workers <= 64 or not 0 < timeout <= 60:
            raise ValueError("invalid listener bounds")
        self.app, self.tls = app, tls
        self._slots = threading.BoundedSemaphore(workers)
        self._timeout = timeout
        self._maintenance_at = time.monotonic() + 300
        super().__init__(address, _Handler)

    def service_actions(self):
        if self.app.retention_days and time.monotonic() >= self._maintenance_at:
            self._maintenance_at = time.monotonic() + 300
            try:
                self.app.ghosts.maintain()
            except sqlite3.Error:
                _LOG.exception("ghost retention maintenance failed")

    def get_request(self):
        client, address = super().get_request()
        client.settimeout(self._timeout)
        if self.tls:
            try:
                client = self.tls.wrap_socket(client, server_side=True, do_handshake_on_connect=False)
            except BaseException:
                client.close()
                raise
        return client, address

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        _LOG.warning("HTTP connection failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument("--credentials", type=Path)
    auth.add_argument("--device-allowlist", type=Path)
    parser.add_argument("--bind", default="127.0.0.1", help="numeric IPv4 bind address")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    parser.add_argument("--ghost-retention-days", default=90, type=int)
    parser.add_argument("--ghost-max-records", default=1000, type=int)
    parser.add_argument("--ghost-max-per-account", default=128, type=int)
    args = parser.parse_args()
    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error("specify both --tls-cert and --tls-key")
    try:
        bind = ipaddress.IPv4Address(args.bind)
        if not bind.is_loopback and not args.tls_cert:
            raise ValueError("TLS required outside loopback")
        tls = None
        if args.tls_cert:
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.minimum_version = ssl.TLSVersion.TLSv1_2
            tls.load_cert_chain(args.tls_cert, args.tls_key)
        os.umask(0o077)
        accounts = (DeviceAccounts(args.device_allowlist) if args.device_allowlist
                    else BearerAccounts.from_file(args.credentials))
        app = CloudApplication(args.state_dir, accounts,
                               retention_days=args.ghost_retention_days, max_total=args.ghost_max_records,
                               max_per_subject=args.ghost_max_per_account)
        try:
            with CloudHTTPServer((str(bind), args.port), app, tls=tls) as server:
                def stop(_signum, _frame):
                    raise KeyboardInterrupt
                signal.signal(signal.SIGTERM, stop)
                app.ghosts.maintain()
                print(f"Cinder Cloud listening on {bind}:{server.server_port}", flush=True)
                server.serve_forever()
        finally:
            app.close()
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(2, "Unable to start Cinder Cloud: " + type(exc).__name__ + "\n")


if __name__ == "__main__":
    main()
