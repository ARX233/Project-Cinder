"""Online SQLite snapshots of active Cinder data, retaining three generations."""
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def backup(state, root):
    if shutil.disk_usage(root).free < 1024**3:
        raise OSError("Insufficient reserve for a Cinder snapshot")
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    with tempfile.TemporaryDirectory(prefix=".pending-", dir=root) as staging:
        snapshot = Path(staging) / name
        snapshot.mkdir(mode=0o700)
        for leaf in ("shared-ghosts.sqlite3", "timing-community.sqlite3"):
            target = snapshot / leaf
            with closing(sqlite3.connect((state / leaf).as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(target)) as out:
                    source.backup(out, pages=128)
                    if out.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                        raise sqlite3.DatabaseError("Invalid Cinder snapshot")
            with target.open("rb") as file:
                os.fsync(file.fileno())
        sync_dir(snapshot)
        snapshot.rename(root / name)
        sync_dir(root)
    committed = sorted(p for p in root.iterdir() if not p.is_symlink() and p.is_dir() and
                       re.fullmatch(r"\d{8}T\d{6}\.\d{6}Z", p.name))
    for expired in committed[:-3]:
        shutil.rmtree(expired)
    sync_dir(root)
    print("Cinder snapshot verified", flush=True)


if __name__ == "__main__":
    backup(Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2]).resolve(strict=True))
