"""Lossless original image708 -> TSM1 in a fresh controlled MAIN output.
Only VerifiedSnapshot/OwnedOutput capabilities and the literal signed plan are
accepted. No caller path, dictionary, Lua execution, fallback, resize or codec
pin relaxation. Source configuration bytes are authenticated, never executed.
"""
from dataclasses import dataclass, field
import hashlib
import io
import json
import os
import stat
import struct
import zlib
from PIL import Image
from .source import (VerifiedSnapshot, OwnedOutput, FileTreeSource, SourceEntry,
                     OriginalInputError, check_cancel, _unique_object)

DEST = 'tiresmoke.bin'
SOURCES = (
    ('data/effect_config.lua', 2602, 'b372fd1da5c8368a6cd0b405b0b80a8d99f57f00f15d4ec9bb94299820b811ca'),
    ('data/sprite/tiresmoke_all.tga', 262188, '6c0683e00b69404c3bab8eba22f4f89e93312fa02343e2f47c016bb900fe18f2'),
)
PIXEL_SHA256 = 'b5efd85e0bad26dfc6c48a59a19a0fd9e02c1206af6646d4f427df0535f6e108'
OUTPUT_SHA256 = '5a0a2d31d64583fc2dd7a8cda2bc81f9bdf80ae07cdad3981d0409ea11748e92'
PIXEL_CRC32 = 1929019831
OUTPUT_BYTES = 262160
_TOKEN = object()


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def reviewed_plan_bytes():
    return _canonical({
        'schema': 'TSM1-original-image708-plan-v1',
        'source_files': [{'path': n, 'bytes': b, 'sha256': h} for n, b, h in SOURCES],
        'image_id': 708, 'width': 256, 'height': 256, 'pixel_format': 'bottom-up-straight-RGBA8',
        'pixel_bytes': 262144, 'pixel_sha256': PIXEL_SHA256, 'pixel_crc32': PIXEL_CRC32,
        'output': {'path': DEST, 'bytes': OUTPUT_BYTES, 'sha256': OUTPUT_SHA256},
    })


@dataclass(frozen=True)
class SmokePlan:
    data: bytes
    sha256: str
    _seal: object = field(repr=False, compare=False)


def parse_plan(data, *, expected_sha256):
    if (type(data) is not bytes or not 0 < len(data) <= 4096 or
            type(expected_sha256) is not str or
            hashlib.sha256(data).hexdigest() != expected_sha256):
        raise OriginalInputError('Smoke plan is not APK-pinned')
    try:
        value = json.loads(data.decode('utf-8', 'strict'), object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise OriginalInputError('Invalid smoke plan') from exc
    if _canonical(value) != data or data != reviewed_plan_bytes():
        raise OriginalInputError('Unreviewed smoke paths, image, pixels or output')
    return SmokePlan(data, expected_sha256, _TOKEN)


def validate_blob(blob):
    """Exact TSM1 structure, CRC, pixels and full file; no draft RGBA4444."""
    if type(blob) is not bytes or len(blob) != OUTPUT_BYTES:
        raise OriginalInputError('Smoke TSM1 byte bound')
    if struct.unpack('<4sHHII', blob[:16]) != (b'TSM1', 256, 256, 262144, PIXEL_CRC32):
        raise OriginalInputError('Smoke TSM1 header')
    pixels = blob[16:]
    if (zlib.crc32(pixels) != PIXEL_CRC32 or hashlib.sha256(pixels).hexdigest() != PIXEL_SHA256 or
            hashlib.sha256(blob).hexdigest() != OUTPUT_SHA256):
        raise OriginalInputError('Smoke TSM1 pixel/CRC/output pin')
    return SourceEntry(OUTPUT_BYTES, OUTPUT_SHA256)


def convert(snapshot, output, plan, *, cancel=None, progress=None):
    if (type(snapshot) is not VerifiedSnapshot or type(output) is not OwnedOutput or
            type(plan) is not SmokePlan or plan._seal is not _TOKEN or
            plan.data != reviewed_plan_bytes() or hashlib.sha256(plan.data).hexdigest() != plan.sha256):
        raise OriginalInputError('Smoke requires verified snapshot/owned output/sealed plan')
    check_cancel(cancel)
    for name, size, digest in SOURCES:
        if snapshot.readset.files.get(name) != SourceEntry(size, digest):
            raise OriginalInputError('Smoke dependency not bound to reviewed snapshot')
    # Context manager closes the owned root FD for success and every exception.
    with FileTreeSource(snapshot.root, snapshot.readset) as reader:
        reader.read(SOURCES[0][0], max_bytes=2602, cancel=cancel)
        image = reader.read(SOURCES[1][0], max_bytes=262188, cancel=cancel)
        check_cancel(cancel)
        with Image.open(io.BytesIO(image)) as im:
            if im.format != 'TGA' or im.size != (256, 256):
                raise OriginalInputError('Smoke original TGA dimensions/format')
            rgba = im.convert('RGBA')
            try:
                flipped = rgba.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                try:
                    pixels = flipped.tobytes()
                finally:
                    flipped.close()
            finally:
                rgba.close()
        check_cancel(cancel)
        blob = struct.pack('<4sHHII', b'TSM1', 256, 256, 262144, PIXEL_CRC32) + pixels
        entry = validate_blob(blob)
        # Revalidate both authenticated sources after decoder use, before writing.
        for name, _, _ in SOURCES:
            for _ in reader.chunks(name, cancel=cancel):
                pass
        target = output.target(DEST)
        fd = None
        identity = None
        try:
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            st = os.fstat(fd)
            identity = (st.st_dev, st.st_ino)
            view = memoryview(blob)
            while view:
                check_cancel(cancel)
                count = os.write(fd, view[:131072])
                if count <= 0:
                    raise OriginalInputError('Smoke output short write')
                view = view[count:]
            os.fsync(fd)
            check_cancel(cancel)
            if progress:
                progress('convert-original-tire-smoke', 1, 1)
            check_cancel(cancel)
            output.files[DEST] = entry
            return entry
        except BaseException:
            # Only our newly created inode may be rolled back. Never adopt/delete
            # a caller's file or follow a replaced symlink. No tree is removed.
            if identity is not None:
                try:
                    current = os.lstat(target)
                except FileNotFoundError:
                    current = None
                if current is not None and stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == identity:
                    os.unlink(target)
            raise
        finally:
            if fd is not None:
                os.close(fd)
