"""Approve or revoke Cinder installation IDs from the service host."""
import argparse
from contextlib import closing
import hashlib
import os
from pathlib import Path
import re
import sqlite3

from .ghost_service import ContractError, TrustedPrincipal


DEVICE_ID = re.compile(r"[0-9a-f]{32}", re.ASCII)
DEVICE_KEY = re.compile(r"[0-9a-f]{64}", re.ASCII)


def set_approved(path, device_id, approved):
    device_id = device_id.strip().lower()
    if not DEVICE_ID.fullmatch(device_id):
        raise ValueError("expected a 32-character device ID")
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS approved_devices (id TEXT PRIMARY KEY) WITHOUT ROWID")
        if approved:
            db.execute("INSERT OR IGNORE INTO approved_devices(id) VALUES (?)", (device_id,))
        else:
            db.execute("DELETE FROM approved_devices WHERE id=?", (device_id,))


class DeviceAccounts:
    challenge = "CinderDevice"

    def __init__(self, path):
        self._database = Path(path).resolve(strict=True).as_uri() + "?mode=ro"
        with closing(sqlite3.connect(self._database, uri=True)) as db:
            db.execute("SELECT id FROM approved_devices LIMIT 1").fetchone()

    def authenticate(self, authorization):
        if authorization is None or authorization[:13].lower() != "cinderdevice ":
            raise ContractError("authentication_required", 401)
        key = authorization[13:]
        if not DEVICE_KEY.fullmatch(key):
            raise ContractError("authentication_required", 401)
        device_id = hashlib.sha256(key.encode("ascii")).hexdigest()[:32]
        with closing(sqlite3.connect(self._database, uri=True, timeout=2.0)) as db:
            approved = db.execute("SELECT 1 FROM approved_devices WHERE id=?", (device_id,)).fetchone()
        if approved is None:
            raise ContractError("device_not_approved", 403)
        return TrustedPrincipal("device:" + device_id, "cinder-device-v1")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("allow", "revoke"))
    parser.add_argument("allowlist", type=Path)
    parser.add_argument("device_id")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        set_approved(args.allowlist, args.device_id, args.action == "allow")
    except (ValueError, sqlite3.Error) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
