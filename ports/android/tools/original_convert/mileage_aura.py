"""Optional, APK-pinned original mileage aura artwork beside the main conversion."""
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from .archive import ArchiveSource
from .source import ConversionCancelled, FileTreeSource, MAIN_SHA256, ReviewedReadSet, check_cancel

AURA_SOURCE_PINS = (
    ('data/effect/car_aura_blue.igb', 305263, '90b4357981687e4fe588dbcf5cfec6385637bae1b89fd7086e91d6cab83ddee1'),
    ('data/effect/car_aura_glow_blue.igb', 24707, '8d7c9903a4cd5bc90a482a3b34da8c4176a5c4c6d61207a5d6a9973e39825b8a'),
    ('data/effect/car_aura_glow_green.igb', 24708, '4764d76f6266f8a964c9025309d2afe2c59f4ee814d1d7db051c3599a64dc4fe'),
    ('data/effect/car_aura_glow_purple.igb', 24716, '4c5a024263485b4c657b79889d6d0731c864ce5c0268211aca7791426fdfd274'),
    ('data/effect/car_aura_glow_red.igb', 24706, 'da64fddf97f044ec78b15c1dce320511f8a2bb1f92c403b284fc54c487f97dd2'),
    ('data/effect/car_aura_green.igb', 305266, '7f197cba7d06833efcdc7a1e40ada449710ed2a8b9b519e39c625cf88be42d86'),
    ('data/effect/car_aura_purple.igb', 305283, '90c13e5978a4d818ac5147ac9d231708f63a2048b883fb75df4c6b5344256b32'),
    ('data/effect/car_aura_red.igb', 305260, 'a5fa7cec21222fd3bcf5357358211880aee3e09e03d9ace9be2d50d2050cfcae'),
)
AURA_PACK = 'mileage-aura.wpk'


def _aura_readset():
    # This read-set is compiled into the APK, never provided by the archive or
    # the job. Main lets the archive use its usual exact-root selection.
    rows = [*AURA_SOURCE_PINS, ('main', 24855892, MAIN_SHA256)]
    data = json.dumps({'schema': 'wmmt-original-readset-v1', 'main_sha256': MAIN_SHA256,
                       'files': [{'path': name, 'bytes': size, 'sha256': digest}
                                 for name, size, digest in rows]}).encode('utf-8')
    return ReviewedReadSet.parse(data, expected_sha256=hashlib.sha256(data).hexdigest())


def convert(root, source_kind, *, cancel=None, progress=None):
    """A missing/older optional source does not prevent the 0.74 profile publishing."""
    from pack_mileage_aura import pack

    if progress:
        progress('pack-mileage-aura', 0, len(AURA_SOURCE_PINS))
    try:
        readset = _aura_readset()
        if source_kind == 'zip':
            source = ArchiveSource(root / 'incoming.zip', readset, cancel=cancel)
        else:
            source = FileTreeSource(root / 'incoming', readset)
        with source, TemporaryDirectory(prefix='mileage-aura-', dir=root) as scratch:
            staged = Path(scratch)
            for index, (name, size, _) in enumerate(AURA_SOURCE_PINS, 1):
                target = staged / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read(name, max_bytes=size, cancel=cancel))
                if progress:
                    progress('pack-mileage-aura', index, len(AURA_SOURCE_PINS))
            check_cancel(cancel)
            temp = staged / AURA_PACK
            pack(staged, temp)
            check_cancel(cancel)
            fd = os.open(temp, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            # Java independently verifies the exact bank before publishing.
            # Final completion fsyncs the job directory after this rename.
            os.replace(temp, root / AURA_PACK)
        return True
    except ConversionCancelled:
        raise
    except (OSError, ValueError):
        return False
