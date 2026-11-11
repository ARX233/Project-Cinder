#!/usr/bin/env python3
"""Project Cinder public site: device approval, time attack board, store ghost kings.

Read-only views over the cinder-cloud SQLite state. The only write is the device
allowlist, performed through the supported server.device_registration helper.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

STATE_DIR = os.environ.get("CINDER_STATE", "/var/lib/cinder-cloud")
STATIC_DIR = os.environ.get("CINDER_STATIC", "/opt/cinder-web/static")
ADMIN_FILE = os.environ.get("CINDER_ADMIN", "/etc/cinder-web/admin.json")
CARS_FILE = os.environ.get("CINDER_CARS", "/opt/cinder-web/cars.json")
APP_ROOT = os.environ.get("CINDER_APP", "/opt/cinder-cloud")
CAPABILITIES = os.environ.get("CINDER_API", "http://127.0.0.1:8791/v1/capabilities")
HOST = os.environ.get("CINDER_BIND", "127.0.0.1")
PORT = int(os.environ.get("CINDER_PORT", "8792"))
MAX_BODY = 4096
TZ = timezone(timedelta(hours=8))

COMMUNITY_DB = os.path.join(STATE_DIR, "timing-community.sqlite3")
GHOSTS_DB = os.path.join(STATE_DIR, "shared-ghosts.sqlite3")
DEVICE_DB = os.path.join(STATE_DIR, "approved-devices.sqlite3")

DEVICE_RE = re.compile(r"[0-9a-f]{32}", re.ASCII)
ALLOWED_HOSTS = {"niceapi.net", "www.niceapi.net"}

# Native course IDs in menu order, with the labels from menu.c's COURSE_NAME sprites.
COURSES = {
    0: "C1 内回り",
    1: "C1 外回り",
    2: "新環状左回り",
    3: "新環状右回り",
    4: "湾岸線",
    6: "横羽線",
    8: "名古屋高速環状",
    9: "阪神高速環状",
    14: "福岡都市高速",
    10: "箱根",
    12: "首都高一周(東京エリア)",
    13: "首都高一周(神奈川エリア)",
}

# Replay area ID, original ghost display label, stable showcase tab ID.
CROWN_AREAS = (
    (0, "C1", (0, 1)),
    (1, "新環状", (2, 3)),
    (2, "湾岸線", (4,)),
    (3, "横羽線", (6,)),
    (4, "名古屋", (8,)),
    (5, "大阪", (9,)),
    (7, "福岡", (14,)),
    (6, "箱根", (10,)),
)

# ---------------------------------------------------------------- persistence
def connect(path):
    if not os.path.isfile(path):
        return None
    try:
        db = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=3.0)
    except sqlite3.Error:
        return None
    db.row_factory = sqlite3.Row
    return db


def read_rows(path, sql, args=()):
    db = connect(path)
    if db is None:
        return []
    try:
        return db.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []
    finally:
        db.close()


def scalar(path, sql, args=()):
    db = connect(path)
    if db is None:
        return None
    try:
        row = db.execute(sql, args).fetchone()
        return None if row is None else row[0]
    except sqlite3.Error:
        return None
    finally:
        db.close()


# ---------------------------------------------------------------- formatting
def fmt_time(ms):
    if ms is None:
        return "-"
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return "-"
    if ms <= 0:
        return "-"
    minutes, rest = divmod(ms, 60000)
    seconds, millis = divmod(rest, 1000)
    return "%d:%02d.%03d" % (minutes, seconds, millis)


def fmt_date(value):
    if not value:
        return "-"
    try:
        value = int(value)
    except (TypeError, ValueError):
        return "-"
    if value > 10 ** 11:
        value = value / 1000.0
    try:
        return datetime.fromtimestamp(value, TZ).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "-"


def decode_record(record):
    """Pull the display fields out of a stored 236 byte CTA1 row."""
    if not record or len(record) < 236:
        return {}
    glyphs = struct.unpack_from("<5I", record, 192)
    name = "".join(chr(g) for g in glyphs if 0 < g < 0x10000)
    title, klass, model, car_type, power, handling = struct.unpack_from("<6I", record, 212)
    return {
        "name": name or "—",
        "title": title,
        "class": klass,
        "model": model,
        "car_type": car_type,
        "power": power,
        "handling": handling,
    }


def course_meta(course):
    return COURSES.get(course, "赛道 %s" % course)


# ---------------------------------------------------------------- car catalogue
def load_cars(path):
    """model id -> {label, short, hp} from the arcade's own car select data."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {int(key): value for key, value in data.get("cars", {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}


CARS = load_cars(CARS_FILE)

# GetHorsePower (0x8568a44): the fixed tune ladder, stock horsepower at power 0.
TUNE_HP = (0, 360, 400, 420, 450, 470, 500, 530, 550, 580, 600, 620, 640,
           660, 680, 700, 720, 740, 760, 780, 800, 810, 815, 820, 825)


def tune_hp(stock, power):
    if not power or power <= 0:
        return stock
    return TUNE_HP[min(int(power), len(TUNE_HP) - 1)]


def apply_car(item):
    info = CARS.get(item.get("model")) or {}
    item["car"] = info.get("short") or ""
    item["car_full"] = info.get("label") or ""
    item["hp"] = tune_hp(info.get("hp", 0), item.get("power") or 0) if info else None
    return item


# ---------------------------------------------------------------- TA board
def ta_rows(course, traffic, limit=100):
    rows = read_rows(
        COMMUNITY_DB,
        "SELECT score, date, record FROM community_pb_v1 "
        "WHERE course=? AND traffic=? ORDER BY score ASC, date DESC, attempt ASC, subject ASC, owner ASC LIMIT ?",
        (course, traffic, limit),
    )
    out = []
    for rank, row in enumerate(rows, 1):
        item = decode_record(row["record"])
        item.update(
            rank=rank,
            ms=row["score"],
            time=fmt_time(row["score"]),
            date=fmt_date(row["date"]),
            course=course,
            course_name=course_meta(course),
            traffic=traffic,
        )
        out.append(apply_car(item))
    return out


def ta_summary(limit=3):
    boards = []
    for course in COURSES:
        boards.append({
            "course": course,
            "course_name": course_meta(course),
            "rows": ta_rows(course, 0, limit),
        })
    return boards


def crown_preview(record, model):
    key = "car-" + "-".join(map(str, (model, *struct.unpack_from("<8I", record, 192))))
    art_dir = os.path.join(STATIC_DIR, "crown")
    poster = key + "-still.webp"
    animation = key + ".webp"
    if os.path.isfile(os.path.join(art_dir, poster)):
        return ("/crown/" + animation if os.path.isfile(os.path.join(art_dir, animation)) else None,
                "/crown/" + poster)
    poster = f"stock-{model}.webp"
    return None, "/crown/" + poster if os.path.isfile(os.path.join(art_dir, poster)) else None


def ghost_kings():
    """Read the same per-area holder and recording the game downloads."""
    db = connect(GHOSTS_DB)
    if db is None:
        raise sqlite3.OperationalError("community crown database unavailable")
    try:
        rows = {row["area"]: row for row in db.execute("""
            SELECT area,id,display_name,raw_model,created_ms,substr(record,1,248) AS header
            FROM community_ghost_crowns_v1
        """)}
    finally:
        db.close()
    kings = []
    for area, name, courses in CROWN_AREAS:
        row = rows.get(area)
        king = {"course": courses[0], "course_name": name, "area": area, "idle": row is None}
        if row is not None:
            record = row["header"]
            item = apply_car({"model": row["raw_model"], "power": struct.unpack_from("<I", record, 100)[0]})
            animation, poster = crown_preview(record, row["raw_model"])
            king.update(id=row["id"], name=row["display_name"], car=item["car"], hp=item["hp"],
                        acquired_at=fmt_date(row["created_ms"]), acquired_at_ms=row["created_ms"],
                        preview=animation, preview_still=poster)
        kings.append(king)
    return kings


# ---------------------------------------------------------------- devices
def device_approved(device_id):
    if not DEVICE_RE.fullmatch(device_id):
        return None
    return bool(scalar(DEVICE_DB, "SELECT 1 FROM approved_devices WHERE id=?", (device_id,)))


def device_list():
    rows = read_rows(DEVICE_DB, "SELECT id FROM approved_devices ORDER BY id")
    return [row["id"] for row in rows]


def device_set(device_id, approved):
    if not DEVICE_RE.fullmatch(device_id):
        raise ValueError("设备 ID 必须是 32 位小写十六进制")
    command = [sys.executable, "-B", "-m", "server.device_registration",
               "allow" if approved else "revoke", DEVICE_DB, device_id]
    result = subprocess.run(command, cwd=APP_ROOT, capture_output=True, timeout=15)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()[:200]
        raise RuntimeError(message or "device_registration 失败")
    return True


# ---------------------------------------------------------------- admin auth
class Admin:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.sessions = {}
        self.failures = {}
        self.secret = None
        self.salt = None
        self.iterations = 240000
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.salt = bytes.fromhex(data["salt"])
            self.secret = bytes.fromhex(data["hash"])
            self.iterations = int(data.get("iterations", 240000))
        except (OSError, ValueError, KeyError):
            self.secret = None

    @property
    def enabled(self):
        return self.secret is not None

    def check(self, password):
        if not self.enabled or not password:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), self.salt, self.iterations)
        return hmac.compare_digest(digest, self.secret)

    def too_many(self, ip):
        now = time.time()
        with self.lock:
            hits = [t for t in self.failures.get(ip, []) if now - t < 300]
            self.failures[ip] = hits
            return len(hits) >= 6

    def note_failure(self, ip):
        with self.lock:
            self.failures.setdefault(ip, []).append(time.time())

    def open(self):
        token = secrets.token_urlsafe(32)
        with self.lock:
            now = time.time()
            for key, expiry in list(self.sessions.items()):
                if expiry < now:
                    self.sessions.pop(key, None)
            self.sessions[token] = now + 12 * 3600
        return token

    def valid(self, token):
        if not token:
            return False
        with self.lock:
            expiry = self.sessions.get(token)
            return bool(expiry and expiry > time.time())

    def close(self, token):
        with self.lock:
            self.sessions.pop(token, None)


ADMIN = Admin(ADMIN_FILE)


class RateLimiter:
    """Small in-memory guard so the open registration endpoint cannot be spammed."""

    def __init__(self, limit, window):
        self.limit = limit
        self.window = window
        self.lock = threading.Lock()
        self.hits = {}

    def allow(self, key):
        now = time.time()
        with self.lock:
            recent = [t for t in self.hits.get(key, []) if now - t < self.window]
            if len(recent) >= self.limit:
                self.hits[key] = recent
                return False
            recent.append(now)
            self.hits[key] = recent
            if len(self.hits) > 4096:
                for stale in [k for k, v in self.hits.items() if not v or now - v[-1] > self.window]:
                    self.hits.pop(stale, None)
            return True


REGISTRAR = RateLimiter(limit=6, window=3600)


def capabilities():
    try:
        with urllib.request.urlopen(CAPABILITIES, timeout=3) as response:
            return json.loads(response.read(4096).decode("utf-8"))
    except (OSError, ValueError):
        return {"online": False}


# ---------------------------------------------------------------- HTTP layer
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".webp": "image/webp",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "cinder-web/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def send_json(self, payload, status=200, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or []):
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_bytes(self, body, content_type, status=200, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or []):
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def cookie_token(self):
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "cinder_admin":
                return value
        return None

    def same_origin(self):
        source = self.headers.get("Origin") or self.headers.get("Referer") or ""
        if not source:
            return True
        return (urlparse(source).hostname or "") in ALLOWED_HOSTS

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        if path == "/api/status":
            return self.send_json({"capabilities": capabilities()})
        if path == "/api/courses":
            return self.send_json({"courses": list(COURSES.items())})
        if path == "/api/summary":
            try:
                kings = ghost_kings()
            except sqlite3.Error:
                kings = []
            return self.send_json({"boards": ta_summary(3), "kings": kings})
        if path == "/api/ta":
            try:
                course = int(query.get("course", ["0"])[0])
                limit = max(1, min(100, int(query.get("limit", ["100"])[0])))
            except ValueError:
                return self.send_json({"error": "bad query"}, 400)
            if course not in COURSES:
                return self.send_json({"error": "unknown course"}, 404)
            return self.send_json({
                "course": course,
                "course_name": course_meta(course),
                "rows": ta_rows(course, 0, limit),
            })
        if path == "/api/ghost":
            try:
                return self.send_json({"kings": ghost_kings()})
            except sqlite3.Error:
                return self.send_json({"error": "鬼王数据暂时不可用"}, 503)
        if path.startswith("/api/ghost/"):
            return self.send_json({"error": "not found"}, 404)
        if path.startswith("/api/device/"):
            device_id = path[len("/api/device/"):].strip().lower()
            approved = device_approved(device_id)
            if approved is None:
                return self.send_json({"valid": False, "error": "设备 ID 需要是 32 位小写十六进制"}, 400)
            return self.send_json({"id": device_id, "valid": True, "approved": approved})
        if path == "/api/admin/devices":
            if not ADMIN.valid(self.cookie_token()):
                return self.send_json({"error": "unauthorized"}, 401)
            return self.send_json({"devices": device_list()})
        if path in ("/", "/ta", "/ghost", "/device", "/admin"):
            return self.serve_file("index.html" if path == "/" else path[1:] + ".html")
        return self.serve_file(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.same_origin():
            return self.send_json({"error": "bad origin"}, 403)
        if path == "/api/device/register":
            payload = self.read_json() or {}
            device_id = str(payload.get("id", "")).strip().lower()
            if not DEVICE_RE.fullmatch(device_id):
                return self.send_json({"error": "设备 ID 需要是 32 位小写十六进制"}, 400)
            if not REGISTRAR.allow(self.client_address[0]):
                return self.send_json({"error": "开通过于频繁，请一小时后再试"}, 429)
            try:
                if not device_approved(device_id):
                    device_set(device_id, True)
            except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
                return self.send_json({"error": str(error)}, 500)
            return self.send_json({"ok": True, "id": device_id, "approved": True})
        if path == "/api/admin/login":
            payload = self.read_json() or {}
            ip = self.client_address[0]
            if ADMIN.too_many(ip):
                return self.send_json({"error": "尝试次数过多，请 5 分钟后再试"}, 429)
            if not ADMIN.enabled:
                return self.send_json({"error": "管理口令尚未配置"}, 503)
            if not ADMIN.check(str(payload.get("password", ""))):
                ADMIN.note_failure(ip)
                return self.send_json({"error": "口令错误"}, 401)
            token = ADMIN.open()
            cookie = ("cinder_admin=%s; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=43200"
                      % token)
            return self.send_json({"ok": True}, headers=[("Set-Cookie", cookie)])
        if path == "/api/admin/device":
            if not ADMIN.valid(self.cookie_token()):
                return self.send_json({"error": "unauthorized"}, 401)
            payload = self.read_json() or {}
            device_id = str(payload.get("id", "")).strip().lower()
            action = str(payload.get("action", ""))
            if action not in ("allow", "revoke"):
                return self.send_json({"error": "action 必须是 allow 或 revoke"}, 400)
            if not DEVICE_RE.fullmatch(device_id):
                return self.send_json({"error": "设备 ID 需要是 32 位小写十六进制"}, 400)
            try:
                device_set(device_id, action == "allow")
            except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
                return self.send_json({"error": str(error)}, 500)
            return self.send_json({"ok": True, "id": device_id, "approved": action == "allow"})
        return self.send_json({"error": "not found"}, 404)

    def serve_file(self, relative):
        relative = relative.lstrip("/")
        if not relative or relative.endswith("/"):
            relative += "index.html"
        target = os.path.normpath(os.path.join(STATIC_DIR, relative))
        if not target.startswith(os.path.join(STATIC_DIR, "")) or not os.path.isfile(target):
            return self.send_json({"error": "not found"}, 404)
        extension = os.path.splitext(target)[1].lower()
        content_type = CONTENT_TYPES.get(extension, "application/octet-stream")
        with open(target, "rb") as handle:
            body = handle.read()
        cache = "no-cache" if extension == ".html" else "public, max-age=300"
        headers = [("X-Content-Type-Options", "nosniff")]
        if extension == ".webp" and target.startswith(os.path.join(STATIC_DIR, "crown", "")):
            cache = "public, max-age=86400"
            etag = '"' + hashlib.sha256(body).hexdigest() + '"'
            headers.append(("ETag", etag))
            validators = self.headers.get("If-None-Match", "").split(",")
            if any(tag.strip().removeprefix("W/") in (etag, "*") for tag in validators):
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", cache)
                self.end_headers()
                return
        self.send_bytes(body, content_type, extra=[("Cache-Control", cache), *headers])


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    sys.stderr.write("cinder-web listening on %s:%d\n" % (HOST, PORT))
    server.serve_forever()


if __name__ == "__main__":
    main()
