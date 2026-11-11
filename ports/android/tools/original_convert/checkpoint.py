"""Private restart state for one sealed conversion job."""
import errno
import hashlib
import json
import os
import stat
import uuid

from .source import (ConversionCancelled, OwnedOutput, OriginalInputError, SourceEntry,
                     check_cancel, _directory, _unique_object)

MAX_RECORD = 2 * 1024 * 1024


def _read_record(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise OriginalInputError('Unsafe conversion checkpoint')
        data = file.read(MAX_RECORD + 1)
    if len(data) > MAX_RECORD:
        raise OriginalInputError('Conversion checkpoint exceeds its size budget')
    try:
        return json.loads(data, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as exc:
        raise OriginalInputError('Invalid conversion checkpoint') from exc


def write_record(path, data, *, replace=True):
    temp = path.with_name(path.name + '-' + uuid.uuid4().hex + '.tmp')
    try:
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        # The service holds the job's converter.lock across the whole run.
        # Android app data permits rename but SELinux denies hard links.
        if not replace and os.path.lexists(path):
            raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), path)
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temp.unlink(missing_ok=True)


def _entry(root, name, target, cancel):
    path = root / name
    _directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as file:
        before = os.fstat(file.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > target['max_bytes']:
            raise OriginalInputError('Invalid checkpoint output: ' + name)
        digest = hashlib.sha256()
        size = 0
        while True:
            check_cancel(cancel)
            data = file.read(128 * 1024)
            if not data:
                break
            size += len(data)
            if size > before.st_size:
                raise OriginalInputError('Checkpoint output grew during read: ' + name)
            digest.update(data)
        after = os.fstat(file.fileno())
        if size != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise OriginalInputError('Checkpoint output changed: ' + name)
        return SourceEntry(size, digest.hexdigest())


class ConversionCheckpoint:
    def __init__(self, root, job, targets, cancel):
        self.path = root / 'checkpoint.json'
        self.outputs = root / 'outputs'
        self.targets = targets
        self.cancel = cancel
        # Identity binds this cache to its original owner and signed recipe.
        identity = [job[key] for key in ('job_id', 'nonce', 'profile_sha256', 'readset_sha256', 'recipe_sha256')]
        self.record = {'version': 1, 'job': identity, 'snapshot': None, 'output': None, 'stages': {}}
        if os.path.lexists(self.path):
            record = _read_record(self.path)
            if (not isinstance(record, dict) or record.keys() != self.record.keys()
                    or record['version'] != 1 or record['job'] != identity
                    or not isinstance(record['stages'], dict)):
                raise OriginalInputError('Conversion checkpoint does not match this job')
            self.record = record
        self.output = None
        self.saved = set()

    def _write(self):
        check_cancel(self.cancel)
        data = json.dumps(self.record, sort_keys=True, separators=(',', ':')).encode('utf-8')
        if len(data) > MAX_RECORD:
            raise OriginalInputError('Conversion checkpoint exceeds its size budget')
        write_record(self.path, data)

    def set_snapshot(self, snapshot):
        self.record['snapshot'] = snapshot.root.name
        self._write()

    def open_output(self):
        name = self.record['output']
        self.output = OwnedOutput(self.outputs) if name is None else OwnedOutput.resume(self.outputs, name)
        if name is None:
            self.record['output'] = self.output.root.name
            self._write()
            return self.output

        invalid = []
        seen = set()
        for stage, rows in self.record['stages'].items():
            if not isinstance(rows, dict) or not rows:
                raise OriginalInputError('Invalid checkpoint stage')
            verified = {}
            for name, expected in rows.items():
                if name in seen or name not in self.targets:
                    raise OriginalInputError('Unknown or duplicate checkpoint output: ' + name)
                seen.add(name)
                target = self.targets[name]
                try:
                    actual = _entry(self.output.root, name, target, self.cancel)
                except ConversionCancelled:
                    raise
                except (FileNotFoundError, OriginalInputError):
                    continue
                fixed = target['sha256']
                if expected == [actual.size, actual.sha256] and (fixed is None or fixed == actual.sha256):
                    verified[name] = actual
            if len(verified) == len(rows):
                self.output.files.update(verified)
                self.saved.update(verified)
            else:
                invalid.append(stage)
        for stage in invalid:
            del self.record['stages'][stage]
        if invalid:
            self._write()
        # An interrupted component may have created some output files without
        # completing a checkpoint. Re-run only those uncommitted files.
        for directory, children, files in os.walk(self.output.root, followlinks=False):
            path = _directory(directory)
            for child in children:
                _directory(path / child)
            for file in files:
                check_cancel(self.cancel)
                item = path / file
                name = item.relative_to(self.output.root).as_posix()
                if name not in self.targets or not stat.S_ISREG(item.lstat().st_mode):
                    raise OriginalInputError('Unknown file in resumed conversion output: ' + name)
                if name not in self.saved:
                    item.unlink()
        return self.output

    def has(self, stage):
        return stage in self.record['stages']

    def save(self, stage, names=None):
        if names is None:
            names = sorted(self.output.files.keys() - self.saved)
        if not names:
            return
        rows = {}
        for name in names:
            check_cancel(self.cancel)
            entry = self.output.files[name]
            fd = os.open(self.output.root / name, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            rows[name] = [entry.size, entry.sha256]
        self.record['stages'][stage] = rows
        self._write()
        self.saved.update(rows)
