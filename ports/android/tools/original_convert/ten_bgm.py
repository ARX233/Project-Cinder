"""Pack the arcade's 10-rival BGM as exact stereo PCM with a small track index."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory

from .archive import ArchiveSource
from .source import ConversionCancelled, FileTreeSource, MAIN_SHA256, ReviewedReadSet, check_cancel

BANK_NAME = 'ten-bgm.bin'
BANK_LENGTH = 159231744
BANK_SHA256 = '1a9cde4ea1e617a243a38a8c7f351ef78cf9e1b689056c650a6a079be72c8c87'
SOURCE_DIR = 'data/sound/bgm/maxi3/'
# Name, PCM rate, full WAV length, and SHA-256 of the original WAV.
TRACKS = (
    ('ten_a1', 28000, 3072044, 'b197e2d96b950606aa24bcad3504ef99243173959fc3e43925a65c7afde801ae'),
    ('ten_a2', 28000, 1536044, '4831a337bbc8c5cfb9d035073263ffb95ad653c0f5612f6243dafbca5b1702bf'),
    ('ten_a3', 28000, 1536044, '90486780618e00fbd953dc4e4cd8e63358857ff401a032a42dd74c3ff99ead45'),
    ('ten_a4', 28000, 1536044, '94a0b6512f55b2a4bd29ab371d55c5b3cb1d1d958829b656cf1ef588ec7b6af0'),
    ('ten_a5', 28000, 1536044, '568025c0088c6c58f04864159355d4baa64651de5be904141267bd1f288cfc55'),
    ('ten_a6', 28000, 1536044, 'f77eb6fe5b33f6857ecbcc9f6227413ced76cadb4cdaf7125cd9be37c96916fa'),
    ('ten_a7', 28000, 3072044, 'f245b09fa3e23c6bc3c12ccca2ad0c93bf7d2c417097b12acd321b4a0c8b8c7e'),
    ('ten_a8', 28000, 3264044, '88fa4b32044e41a2a21315ce3f3476851a5f58e78ab7fae5ee878ae6c717338b'),
    ('ten_a9', 28000, 6144044, '073818bd1aa76b80a983b9bc869ccdef263d57cf72a5b01a9460e3bfbf70c409'),
    ('ten_b1', 28000, 1536044, 'cf2381d42c568c77f10fb4e16ca1166a831f4095782b5c0e3488446d6ca2b6ae'),
    ('ten_b2', 28000, 1536044, '341c1f0e95a3d0664708727c7e48a94ae0b7b6a32a41107cf540d8902d113b3c'),
    ('ten_b3', 28000, 1536044, '63cbfd16c7b3bbffee69043c7fb144ed521eeecfa1e959ef47ac19a3f707a32b'),
    ('ten_b4', 28000, 1536044, 'df0b12c910538e2a53736594096956570480a540cde44b22ddd7303ee0332d7b'),
    ('ten_b5', 28000, 1536044, '320966c7c32d414f7521f27968f480ed839e3f630fd1c78347dfaff7c0b9f660'),
    ('ten_b6', 28000, 3072044, '2d4ef4cc8d572ee4ee0d12548da89f6e7c0a9303e84f7f8803dd42eeb5de75b3'),
    ('ten_b7', 28000, 3072044, 'f837529c2da573358173c325481133196da5e2065f10f2b4b3d135c904054507'),
    ('ten_b8', 28000, 6144044, '0f292a0a89287e95c21b4ac4ad4ec3d1f0fff54aeb553ba9a6f245fc75f92cd3'),
    ('ten_c1', 28000, 3072044, 'd9ba5fb2f37a7d02f758a4219fd15bf76ad6c1eb105ce5746bed4af97a1ec105'),
    ('ten_c2', 28000, 3072044, '8eb9ad2523ec64b2c3ed1103bbd6cb239f7e5babc6ad58e6cb0638f15e414877'),
    ('ten_c3', 28000, 6144044, '6072cea9aef743fbcb3dd8e7bf40d47e53eefdb1a106930a0047a04b880931b8'),
    ('ten_c4', 28000, 6144044, 'da31e40c87156e3404a4daac3eb57364316de64dccc4c5ed0585c4ccf16984f7'),
    ('ten_c5', 28000, 6144044, '833af7edc278213428108136e77deac5596ee4eaac13256b7d8007f7c7063fc4'),
    ('ten_c6', 28000, 3840044, 'a70bb6b17ab910f9af8b15d5a69a9ce718e46d51a5b4f5e8b89f24ea90426004'),
    ('ten_c7', 28000, 3072044, 'b11b47b6a4b25c8c1699d748e0e1070ce48b019ee9eed0ce98b891ecfeba2405'),
    ('ten_c8', 28000, 4608044, '2b8fd09d851c7391cf3f1406f4a3746daef9acb322217161e6f67c8b2ea8778d'),
    ('ten_d1', 44100, 4736940, '86feb990533102f15ab2fdd383fd396dd6411e0a50ddd1ee420b1c0327f39229'),
    ('ten_d2', 44100, 9473836, 'f505e53384c8ad4b1b72b88a18cf56041ba513c8b59ca40ddf8e172fc6bdf5ab'),
    ('ten_d3', 44100, 4736944, '9cebe46eab910aa828aa4650bea705df65cd47f0412bffce6339d15289c88241'),
    ('ten_d4', 44100, 9473836, 'bc7c9d6fc1a7e8185db40fe8e84dd8bd045ce039aef17c5b66f7338ad835228c'),
    ('ten_d5', 44100, 5329052, '92c35c0f010be4d55c456ea580d9f4c0c96d6174e1609c02c70b029c13ea590e'),
    ('ten_d6', 44100, 9473836, '6c611e3993f42245197eac01d4b551df9d42824579cce14613a791bbcd2203b9'),
    ('ten_e1', 44100, 4736940, 'ae6d2a32e877be2685db7a2bce539da68905437dc10f074cd8df3ebd7fca4bb9'),
    ('ten_e2', 44100, 4736940, 'ac693740ceaf70abe2d4c03644fc93bc887ec6fffc61aa9dc89a6d4672bd691a'),
    ('ten_e3', 44100, 7105388, 'f366d30c6344e769a3d647cc3c97defd045b0538f9426d1e85a1f9048d7110e5'),
    ('ten_e4', 44100, 4736940, '3fd96d0d200047feaa6cb81caa694cd270741d21b5938f79302d76ef9a2a9485'),
    ('ten_e5', 44100, 4736940, 'cb3672a112ecb927d2cdf9c2fbaeeb4939abc8c749c6803d7f695d9840219cbf'),
    ('ten_e6', 44100, 2368492, '21be37f752afe3f693438dae0ee6ee363afbe26a2962021a1e00cdc5642a55aa'),
    ('ten_e7', 44100, 8289616, '0cdb097cd06544550d6c294fd3735791165594f0ae19eff2fd0cc14c16f65806'),
)


def _source_path(name):
    return SOURCE_DIR + name + '.wav'


def _readset():
    files = [{'path': _source_path(name), 'bytes': length, 'sha256': digest}
             for name, _, length, digest in TRACKS]
    files.append({'path': 'main', 'bytes': 24855892, 'sha256': MAIN_SHA256})
    data = json.dumps({'schema': 'wmmt-original-readset-v1', 'main_sha256': MAIN_SHA256,
                       'files': files}).encode('utf-8')
    return ReviewedReadSet.parse(data, expected_sha256=hashlib.sha256(data).hexdigest())


def _pack(source, target, cancel, progress):
    header = bytearray(struct.pack('<4sI', b'WTB1', len(TRACKS)))
    for name, rate, length, _ in TRACKS:
        header += struct.pack('<8sII', name.encode('ascii'), rate, length - 44)
    digest = hashlib.sha256(header)
    with target.open('xb') as out:
        out.write(header)
        for index, (name, _, _, _) in enumerate(TRACKS, 1):
            chunks = source.chunks(_source_path(name), cancel=cancel)
            with closing(chunks):
                pcm = next(chunks)[44:]
                digest.update(pcm)
                out.write(pcm)
                for pcm in chunks:
                    digest.update(pcm)
                    out.write(pcm)
            if progress:
                progress('pack-ten-bgm', index, len(TRACKS))
        if out.tell() != BANK_LENGTH or digest.hexdigest() != BANK_SHA256:
            raise ValueError('Original 10-rival BGM bank differs from the reviewed PCM')
        out.flush()
        os.fsync(out.fileno())


def pack(original, target, *, cancel=None, progress=None):
    """Build the same bank from an original directory or its ZIP archive."""
    readset = _readset()
    source = (FileTreeSource(original, readset) if original.is_dir()
              else ArchiveSource(original, readset, cancel=cancel))
    with source:
        if progress:
            progress('pack-ten-bgm', 0, len(TRACKS))
        _pack(source, target, cancel, progress)


def convert(root, source_kind, *, cancel=None, progress=None):
    original = root / ('incoming.zip' if source_kind == 'zip' else 'incoming')
    try:
        with TemporaryDirectory(prefix='ten-bgm-', dir=root) as scratch:
            target = Path(scratch) / BANK_NAME
            pack(original, target, cancel=cancel, progress=progress)
            check_cancel(cancel)
            os.replace(target, root / BANK_NAME)
        return True
    except ConversionCancelled:
        raise
    except (OSError, ValueError):
        return False


if __name__ == '__main__':
    import argparse
    from shutil import copyfileobj
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('original', type=Path)
    cli.add_argument('output', type=Path, help='new ten-bgm.bin path')
    args = cli.parse_args()
    output = args.output.absolute()
    with TemporaryDirectory(prefix='ten-bgm-', dir=output.parent) as scratch:
        target = Path(scratch) / BANK_NAME
        pack(args.original.absolute(), target)
        with target.open('rb') as source, output.open('xb') as dest:
            copyfileobj(source, dest, 1024 * 1024)
