"""Pack the arcade's stickers (vinyls) for the iPad port: data/vinyl/<folder>.vpk by car.

clCarModelData::constructBody (0x89466bc) makes a car's body textures with
clCarTextureReplace: for each page i (BaseTextureGet(body, i), the texture replaced) the paint
(BodyColorTextureGet, or BodyCustomTextureGet), the shadow (ShadowTextureGet: dummy.tga,
white) and the vinyl (VinylTextureGet(body, vinyl, carbon bonnet, i)), which
nsTextureReplace::TextureReplace (0x8515790) blends a pixel at a time:
rgb = paint * (1 - a / 255) + vinyl * a / 255, then * shadow / 255. Only page 1 has vinyls.
The vinyl's table entry is car.lua's VinylTexture.<body>[vinyl + 1] (entry 1 the dummy: no
vinyl); the works livery's entry holds one per WorksIndex (the paint's `works`, 1 black,
2 white), each with page1_cb, the one under a carbon bonnet (the bonnet > 1).

The port blends the same on the device (render.c wpk_texture_over), over its 512 x 512 page:
so the vinyls are packed at 512 x 512 (premultiplied 2 x 2 means of the 1024 x 1024 TGAs),
bottom-up rows like the IGB images (pack.load_image_file). A vinyl of one colour (the lines,
the tribals) keeps that colour and its alpha alone, and the same alpha (one design in its ten
colours) is stored once.

File: "VPK1", u32 n_entries, u32 n_planes, char page1[4][48] (the replaced texture's name in
the car's pack, by body; "" none), u8 works[32] (by paint, WorksIndex), then n_entries of
{u8 body, u8 vinyl, u8 works, u8 cb, u8 r, g, b, kind, u32 plane} (kind 0: plane is
premultiplied RGBA, 1: plane is alpha, colour r g b), then n_planes of {u32 off, u32 size}
(zlib, 512 x 512 x 4 or x 1 bytes inflated).

usage: pack_vinyl.py <arcade root> <out dir> [folder...]
"""
import hashlib
import os
import struct
import sys
import zlib

import numpy as np

import lualite
import pack

HERE = os.path.dirname(os.path.abspath(__file__))
BODIES = ["normal", "aero_a", "aero_b", "aero_c"]
SIZE = 512


def car_packs():
    src = open(os.path.join(HERE, "..", "..", "src", "cardb.h")).read()
    i = src.index("CARDB_PACKS[")
    import re
    return re.findall(r'"([^"]+)"', src[i:src.index("};", i)])


def decal(path):
    """premultiplied RGBA 512 x 512 (float), bottom-up"""
    a = np.asarray(pack.load_image_file(path), dtype=np.float32)
    rgb, al = a[..., :3] * (a[..., 3:4] / 255.0), a[..., 3:4]
    p = np.concatenate([rgb, al], axis=2)
    h, w = p.shape[:2]
    f = max(1, w // SIZE)
    if f > 1:
        p = p.reshape(h // f, f, w // f, f, 4).mean(axis=(1, 3))
    return p


def encode(p):
    """(kind, colour, plane bytes)"""
    al = p[..., 3]
    seen = al > 8
    if seen.any():
        col = p[..., :3][seen] / al[seen][:, None] * 255.0
        lo, hi = col.min(axis=0), col.max(axis=0)
        if (hi - lo).max() <= 6:
            c = tuple(int(round(v)) for v in (lo + hi) / 2)
            # Android's NumPy can read past the buffer when rounding strided alpha.
            alpha = np.ascontiguousarray(al)
            return 1, c, alpha.round().clip(0, 255).astype(np.uint8).tobytes()
    return 0, (0, 0, 0), p.round().clip(0, 255).astype(np.uint8).tobytes()


def pack_car(root, folder, out):
    car = lualite.load(f"{root}/data/car/{folder}/car.lua")
    vin = car.get("VinylTexture") or {}
    base = car.get("BaseTexture") or {}
    page1 = []
    for b in BODIES:
        t = base.get(b) or {}
        p = t.get("page1") or ""
        page1.append(os.path.basename(p.replace("\\", "/")).rsplit(".", 1)[0] if p else page1[0] if page1 else "")
    paints = (car.get("BodyColorTexture") or {}).get("normal") or []
    works = [int(p.get("works", 1)) if isinstance(p, dict) and p else 1 for p in paints][:32]
    entries, planes, by_hash, by_path, missing = [], [], {}, {}, []
    for bi, b in enumerate(BODIES):
        tbl = vin.get(b) or []
        for idx, e in enumerate(tbl):
            if idx == 0 or not e:
                continue
            subs = [(0, e)] if isinstance(e, dict) else [(k + 1, s) for k, s in enumerate(e) if isinstance(s, dict)]
            for wk, s in subs:
                for cb, key in ((0, "page1"), (1, "page1_cb")):
                    path = s.get(key) or ""
                    if not path:
                        continue
                    full = f"{root}/{path}"
                    if full not in by_path:
                        if not os.path.exists(full):
                            missing.append(path)
                            by_path[full] = None
                            continue
                        kind, col, data = encode(decal(full))
                        hsh = hashlib.md5(data).digest()
                        if hsh not in by_hash:
                            by_hash[hsh] = len(planes)
                            planes.append(zlib.compress(data, 9))
                        by_path[full] = (kind, col, by_hash[hsh])
                    v = by_path[full]
                    if v:
                        entries.append((bi, idx, wk, cb) + v[1] + (v[0], v[2]))
    head = struct.pack("<4sII", b"VPK1", len(entries), len(planes))
    head += b"".join(n.encode().ljust(48, b"\0")[:48] for n in page1)
    head += bytes(works + [1] * (32 - len(works)))
    head += b"".join(struct.pack("<8BI", *e) for e in entries)
    off = len(head) + 8 * len(planes)
    tbl = b""
    for z in planes:
        tbl += struct.pack("<II", off, len(z))
        off += len(z)
    with open(out, "wb") as f:
        f.write(head + tbl + b"".join(planes))
    print("  %s: %d vinyls, %d planes, %.1f MB%s" % (folder, len(entries), len(planes), off / 1e6,
                                                   ", %d missing" % len(missing) if missing else ""))


def main():
    root, out_dir = sys.argv[1], sys.argv[2]
    want = sys.argv[3:] or [p for p in car_packs() if os.path.exists(f"{root}/data/car/{p}/car.lua")]
    os.makedirs(out_dir, exist_ok=True)
    for folder in want:
        pack_car(root, folder, os.path.join(out_dir, folder + ".vpk"))


if __name__ == "__main__":
    main()
