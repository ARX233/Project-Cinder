#!/usr/bin/env python3
"""Export crown display artwork from the original arcade files and local game packs.

Pillow exports the attract screen. Turntables also use NumPy and Numba.
Pass repeated --car options to render multiple verified build keys in one run.
WPKs, the WPPAINT1 bank, and original game inputs are private. Only publish WebPs.

Example for the observed BNR32:
    python3 build_crown_art.py --out static/crown --data /private/game-data \
        --generated-src /private/generated/src --car 77 0 1 0 0 2 0 0 0

The game's clSeqChampionDispThread loads ANM 180 for the area plates at
0x87a0e76 and sets the selected clMenuCar's yaw matrix in yield (0x87a06a8).
The web preview keeps the original geometry and materials with a shorter
turntable loop and simple lighting for the browser.
"""
import argparse
import hashlib
import math
import re
import struct
import zlib
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

ARCADE_SHA256 = "2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6"
SPRITE_TABLE = 0x9551560
AREA_SPRITES = (4675, 4680, 4681, 4682, 4678, 4679, 4676, 4677)
SOURCE = Path(__file__).resolve().parents[1] / "src"
WHEEL, LAMP_OFF, MIRROR, WING, BONNET, CUSTOM_TIRE = 0x100, 0x110, 0x120, 0x122, 0x126, 0x12A


def sprite_paths(main):
    data = main.read_bytes()
    if hashlib.sha256(data).hexdigest() != ARCADE_SHA256:
        raise ValueError("unsupported arcade executable")
    header = struct.unpack_from("<16sHHIIIIIHHHHHH", data)
    programs = [struct.unpack_from("<8I", data, header[5] + i * header[9])
                for i in range(header[10])]

    def offset(va):
        for kind, off, addr, _, size, *_ in programs:
            if kind == 1 and addr <= va < addr + size:
                return off + va - addr
        raise ValueError(f"unmapped arcade sprite pointer {va:#x}")

    ids = (6200, 7915, *AREA_SPRITES)
    paths = {}
    for sid in ids:
        address, = struct.unpack_from("<I", data, offset(SPRITE_TABLE + 44 * sid))
        start = offset(address)
        paths[sid] = data[start:data.index(b"\0", start)].decode("ascii")
    return paths


def frame_zero(path):
    data = path.read_bytes()
    frames, _ = struct.unpack_from("<II", data)
    start, count = struct.unpack_from("<II", data, 8)
    origin = 8 + frames * 8
    return [struct.unpack_from("<i6f9i", data, origin + 64 * (start + i))
            for i in range(count)]


def export_plates(root, out):
    paths = sprite_paths(root / "main")
    records = frame_zero(root / "data/anime/menu_g_crown_atract.anm")
    positions = {r[0]: (int(r[5]), int(r[6])) for r in records}

    def sprite(sid):
        with Image.open(root / paths[sid]) as image:
            return image.convert("RGBA")

    # The authored art is already curved in perspective. Keep its native
    # registration instead of flattening its eight plates into rectangles.
    crop = (0, 26, 640, 360)
    gray = sprite(6200)
    gray.crop(crop).save(out / "backdrop.webp", quality=88)
    for area, sid in enumerate(AREA_SPRITES):
        selected = gray.copy()
        selected.alpha_composite(sprite(sid), positions[sid])
        selected.crop(crop).save(out / f"plate-{area}.webp", quality=88)
    banner = sprite(7915)
    banner.crop(banner.getbbox()).save(out / "banner.webp", quality=92)


@cache
def model_paints():
    pattern = r"\{\s*(" + r"\d+\s*,\s*" * 8 + r"\d+)\s*\}"
    table = (SOURCE / "cardb.h").read_text().split("CARDB_PACKS", 1)[1].split("};", 1)[0]
    folders = re.findall(r'"([A-Za-z0-9_]+)"', table)
    models = {}
    for match in re.findall(pattern, (SOURCE / "ghost_arcade_models.inc").read_text()):
        model, _, _, _, _, _, pack, paint, _ = map(int, match.split(","))
        models[model] = (pack, folders[pack], paint)
    return models


def wheel_info(raw_wheel, folder, aero, tables):
    rows = re.findall(r'\{\s*(\d+),\s*(\d+),\s*"([A-Za-z0-9_]+)",\s*"[A-Za-z0-9_]+"\s*\}',
                      (tables / "dressdb.h").read_text().split("DRESS_WHEELS[]", 1)[1])
    for ident, tex, name in rows:
        if int(ident) == raw_wheel:
            break
    else:
        raise ValueError(f"unknown wheel {raw_wheel}")
    block = (tables / "carwheel.h").read_text().split(f"/* {folder} */", 1)[1].split("\n  },", 1)[0]
    values = [float(v) for v in re.findall(r"(-?\d+(?:\.\d+)?)f", block)]
    return f"{name}_{int(tex)}.wpk", values[aero * 8:aero * 8 + 8]


def paint_texture(pixels, w, h, fmt, np):
    if fmt == 0:  # RGB565
        channels = ((pixels >> 11, 31), ((pixels >> 5) & 63, 63), (pixels & 31, 31),
                    (np.ones_like(pixels), 1))
    elif fmt == 1:  # RGBA4444
        channels = tuple(((pixels >> shift) & 15, 15) for shift in (12, 8, 4, 0))
    elif fmt == 2:  # RGB5551
        channels = ((pixels >> 11, 31), ((pixels >> 6) & 31, 31),
                    ((pixels >> 1) & 31, 31), (pixels & 1, 1))
    else:
        raise ValueError("preview requires uncompressed WPK textures")
    return np.stack([v * 255 // largest for v, largest in channels], axis=-1).astype("u1").reshape(h, w, 4)


class Pack:
    def __init__(self, path):
        self.data = path.read_bytes()
        magic, nt, self.nc, _, _, to, self.co, self.bo = struct.unpack_from("<4sIIIfIII", self.data)
        if magic != b"WPK3" and not (magic == b"WPK2" and self.nc == 0):
            raise ValueError(f"unsupported WPK format: {path.name}")
        self.names = []
        self.textures = {}
        for i in range(nt):
            name, w, h, fmt, off, size = struct.unpack_from("<48sHHIII", self.data, to + 64 * i)
            name = name.split(b"\0")[0].decode("latin1")
            self.names.append(name)
            if size:
                self.textures[name] = (w, h, fmt, off, size)

    def texture(self, key, np):
        w, h, fmt, off, size = self.textures[key]
        if size != 2 * w * h:
            raise ValueError("incomplete WPK texture")
        raw = np.frombuffer(self.data, "<u2", w * h, off)
        return paint_texture(raw, w, h, fmt, np)

    def meshes(self, groups, np, paint=0, base=None, transform=None, materials=None):
        dtype = np.dtype([("pos", "<f4", 3), ("uv", "<f4", 2), ("rgba", "u1", 4),
                          ("normal", "<i2", 3), ("pad", "<i2")])
        texture_cache = {}
        for i in range(self.nc):
            *_, first, count, group = struct.unpack_from("<6fIII", self.data, self.co + 36 * i)
            if group not in groups:
                continue
            for b in range(first, first + count):
                tex, flags, vo, nv, io, ni = struct.unpack_from("<HHIIII", self.data, self.bo + 28 * b)
                verts = np.frombuffer(self.data, dtype, nv, vo)
                pos = np.array(verts["pos"])
                normal = np.array(verts["normal"], dtype=np.float32) / 32767
                if transform:
                    scale, shift = transform
                    pos = pos * scale + shift
                    normal = normal / scale
                if tex not in texture_cache:
                    if tex >= len(self.names):
                        texture_cache[tex] = np.full((1, 1, 4), 255, "u1")
                    else:
                        name = self.names[tex]
                        material = name.rsplit(".", 1)[0]
                        candidates = [f"p{paint}:{name}", name] if paint else [name]
                        for key in candidates:
                            owner = self if key in self.textures else base
                            if owner is not None and key in owner.textures:
                                pixels = owner.texture(key, np)
                                texture_cache[tex] = materials(material, pixels) if materials else pixels
                                break
                        else:
                            raise ValueError(f"missing texture {name}")
                yield (pos, np.array(verts["uv"]), np.array(verts["rgba"]), normal,
                       np.frombuffer(self.data, "<u2", ni, io).reshape(-1, 3),
                       texture_cache[tex], flags & 3)


def inflate(data, size):
    decoder = zlib.decompressobj()
    payload = decoder.decompress(data, size + 1)
    if len(payload) != size or not decoder.eof or decoder.unused_data:
        raise ValueError("invalid original material payload")
    return payload


def custom_pages(path, pack, color, aero, np):
    """Read only the selected pages from the private original converter's WPPAINT1 bank."""
    pages = {}
    with path.open("rb") as bank:
        header = bank.read(128)
        magic, version, header_size, stride, count, *_ = struct.unpack_from("<8sIIIIIIQQQ", header)
        if (magic, version, header_size, stride) != (b"WPPAINT1", 1, 128, 320) or count > 10000:
            raise ValueError("invalid custom paint bank")
        if header[88:120].hex() != ARCADE_SHA256:
            raise ValueError("custom paint bank targets a different executable")
        directory = bank.read(stride * count)
        for i in range(count):
            row = directory[i * stride:(i + 1) * stride]
            model, tint, body, _, _, w, h, _, raw, compressed, crc, offset = struct.unpack_from(
                "<HBBBBHHHIIIQ", row
            )
            if (model, tint, body) != (pack, color, aero):
                continue
            if not (1 <= w <= 2048 and 1 <= h <= 2048 and raw == w * h * 4 and 0 < compressed <= raw + 65536):
                raise ValueError("invalid custom paint dimensions")
            bank.seek(offset)
            pixels = inflate(bank.read(compressed), raw)
            if zlib.crc32(pixels) != crc or hashlib.sha256(pixels).digest() != row[32:64]:
                raise ValueError("custom paint payload digest mismatch")
            material = row[128:176].split(b"\0")[0].decode("ascii")
            pages[material] = np.frombuffer(pixels, "u1").reshape(h, w, 4)
    if not pages:
        raise ValueError("selected custom paint is missing")
    return pages


def vinyl_page(path, aero, vinyl, paint, bonnet, np):
    data = path.read_bytes()
    magic, count, planes = struct.unpack_from("<4sII", data)
    if magic != b"VPK1" or not (0 < count <= 4096 and 0 < planes <= 4096):
        raise ValueError("invalid vinyl pack")
    name = data[12 + 48 * aero:60 + 48 * aero].split(b"\0")[0].decode("ascii")
    works = data[204 + paint]
    chosen = None
    for i in range(count):
        body, ident, kind, carbon, r, g, b, mask, plane = struct.unpack_from("<8BI", data, 236 + 12 * i)
        if body == aero and ident == vinyl and kind in (0, works):
            matches_bonnet = carbon == (bonnet > 1)
            if chosen is None or matches_bonnet:
                chosen = (r, g, b, mask, plane)
            if matches_bonnet:
                break
    if chosen is None:
        raise ValueError("selected vinyl is missing")
    r, g, b, mask, plane = chosen
    if plane >= planes:
        raise ValueError("invalid vinyl plane")
    offset, length = struct.unpack_from("<II", data, 236 + 12 * count + 8 * plane)
    payload = np.frombuffer(inflate(data[offset:offset + length], 512 * 512 * (1 if mask else 4)), "u1")
    if mask:
        alpha = payload.reshape(512, 512, 1).astype("u2")
        rgb = alpha * np.array([r, g, b], "u2") // 255
    else:
        rgba = payload.reshape(512, 512, 4)
        rgb, alpha = rgba[..., :3], rgba[..., 3:]
    return name, rgb, alpha


def compose_materials(pages, vinyl, np):
    applied = set()

    def material(name, pixels):
        applied.add(name)
        pixels = pages.get(name, pixels)
        if vinyl is None or vinyl[0] != name:
            return pixels
        _, rgb, alpha = vinyl
        if pixels.shape[:2] != (512, 512):
            size = (pixels.shape[1], pixels.shape[0])
            rgb = np.asarray(Image.fromarray(rgb.astype("u1")).resize(size, Image.Resampling.BILINEAR))
            alpha = np.asarray(Image.fromarray(alpha[..., 0].astype("u1")).resize(size, Image.Resampling.BILINEAR))[..., None]
        composite = pixels.copy()
        composite[..., :3] = np.minimum(255, pixels[..., :3].astype("u2") * (255 - alpha) // 255 + rgb)
        return composite

    return material, applied


def neon_mesh(path, table, folder, aero, neon, np):
    entries = next(line for line in table.read_text().splitlines() if f"/* {folder} (car " in line)
    values = [float(v) for v in re.findall(r"(-?\d+(?:\.\d+)?)f", entries)]
    x, y, z, scale_x, _, scale_z = values[aero * 6:aero * 6 + 6]
    y -= 3.1  # the menu car applies this additional offset before drawing neon
    rx, rz = 29 * scale_x, 29 * scale_z
    points = np.array([[x - rx, y, z + rz], [x + rx, y, z + rz],
                       [x + rx, y, z - rz], [x - rx, y, z - rz]], "f4")
    pack = Pack(path)
    tex = pack.texture(pack.names[neon - 1], np)
    # The original neon pack stores premultiplied additive light. Represent
    # the same colours and footprint as translucent pixels in the WebP.
    rgb = tex[..., :3].astype("u2")
    alpha = rgb.max(axis=-1, keepdims=True)
    tex[..., :3] = rgb * 255 // np.maximum(1, alpha)
    tex[..., 3:4] = alpha
    return (points, np.array([[0, 0], [1, 0], [1, 1], [0, 1]], "f4"),
            np.full((4, 4), 255, "u1"), np.zeros((4, 3), "f4"),
            np.array([[0, 1, 2], [0, 2, 3]], "u2"), tex, 3)


def load_meshes(key, data, tables, paint_bank, np):
    model, custom, aero, mirror, wing, bonnet, wheel, neon, vinyl = key
    if not (0 <= aero <= 3 and 0 <= mirror <= 1 and 0 <= wing <= 4 and 0 <= bonnet <= 3
            and (0 <= wheel <= 112 or wheel == 143) and 0 <= custom <= 10
            and 0 <= neon <= 12 and 0 <= vinyl <= 255):
        raise ValueError("unsupported dress selector")
    pack, folder, paint = model_paints()[model]
    if custom and paint_bank is None:
        raise ValueError("custom paint requires --paint-bank")
    pages = custom_pages(paint_bank, pack, custom, aero, np) if custom else {}
    decal = vinyl_page(data / "vinyl" / f"{folder}.vpk", aero, vinyl, paint, bonnet, np) if vinyl else None
    materials, applied = compose_materials(pages, decal, np)
    base = Pack(data / "cars" / f"{folder}.wpk")
    suffix = "_aero" + "ABC"[aero - 1] if aero else ""
    dressed = Pack(data / "cars" / f"{folder}{suffix}.wpk") if aero else base
    tire = CUSTOM_TIRE if wheel != 143 else WHEEL
    groups = {0, LAMP_OFF, MIRROR + mirror, BONNET + bonnet, *range(tire, tire + 4)}
    if wing < 4:
        groups.add(WING + wing)
    meshes = list(dressed.meshes(groups, np, paint, base, materials=materials))
    if pages and not (pages.keys() & applied):
        raise ValueError("selected paint does not match the body's materials")
    if decal and decal[0] not in applied:
        raise ValueError("selected vinyl does not match the body's materials")
    if wheel != 143:
        path, hubs = wheel_info(wheel, folder, aero, tables)
        rims = Pack(data / "wheels" / path)
        for k in range(4):
            x, z, width, radius = hubs[(k // 2) * 4:(k // 2 + 1) * 4]
            scale = np.array([width, radius, radius], dtype="f4")
            shift = np.array([(-1 if k % 2 else 1) * x, 0, z], dtype="f4")
            meshes.extend(rims.meshes({WHEEL + k % 2}, np, transform=(scale, shift)))
    if neon:
        meshes.append(neon_mesh(data / "neon.wpk", tables / "neondb.h", folder, aero, neon, np))
    return meshes


def rasterize(p, uv, color, light, tris, tex, blend, image, depth):
    height, width = depth.shape
    th, tw = tex.shape[:2]
    for tri in tris:
        a, b, c = tri
        x0, y0, z0 = p[a]
        x1, y1, z1 = p[b]
        x2, y2, z2 = p[c]
        denom = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(denom) < 0.000001:
            continue
        for y in range(max(0, int(min(y0, y1, y2))), min(height, math.ceil(max(y0, y1, y2)))):
            for x in range(max(0, int(min(x0, x1, x2))), min(width, math.ceil(max(x0, x1, x2)))):
                dx, dy = x + 0.5 - x0, y + 0.5 - y0
                wb = (dx * (y2 - y0) - dy * (x2 - x0)) / denom
                wc = ((x1 - x0) * dy - (y1 - y0) * dx) / denom
                wa = 1 - wb - wc
                if min(wa, wb, wc) < 0:
                    continue
                z = wa * z0 + wb * z1 + wc * z2
                if z < depth[y, x]:
                    continue
                u = math.floor((wa * uv[a, 0] + wb * uv[b, 0] + wc * uv[c, 0]) * tw) % tw
                v = math.floor((wa * uv[a, 1] + wb * uv[b, 1] + wc * uv[c, 1]) * th) % th
                rgba = tex[v, u]
                alpha = rgba[3] * (wa * color[a, 3] + wb * color[b, 3] + wc * color[c, 3]) / 65025
                if alpha <= 0.03:
                    continue
                shade = wa * light[a] + wb * light[b] + wc * light[c]
                if not blend or (blend < 3 and alpha > 0.96):
                    depth[y, x] = z
                    alpha = 1
                previous = image[y, x, 3] / 255
                opacity = alpha + previous * (1 - alpha)
                for ch in range(3):
                    rgb = rgba[ch] * (wa * color[a, ch] + wb * color[b, ch] + wc * color[c, ch]) / 255
                    if blend != 3:
                        rgb = min(255, rgb * shade + 4)
                    image[y, x, ch] = (rgb * alpha + image[y, x, ch] * previous * (1 - alpha)) / opacity
                image[y, x, 3] = opacity * 255


def turntable(meshes, np, raster, steps):
    width, height = 500, 266
    vertices = np.concatenate([mesh[0] for mesh in meshes if mesh[-1] != 3])
    center = (vertices.max(axis=0) + vertices.min(axis=0)) / 2
    span = np.linalg.norm(np.ptp(vertices[:, (0, 2)], axis=0))
    scale = 0.90 * width / span
    pitch = math.radians(14)
    for frame in range(steps):
        angle = math.radians(45) + frame * (2 * math.pi / steps)
        forward = np.array([math.sin(angle), 0, math.cos(angle)])
        eye = forward * math.cos(pitch) + [0, math.sin(pitch), 0]
        right = np.array([math.cos(angle), 0, -math.sin(angle)])
        up = np.cross(eye, right)
        key = eye * 0.28 + right * 0.12 + [0, 0.85, 0]
        depth = np.full((height, width), -np.inf, "f4")
        image = np.zeros((height, width, 4), "u1")
        batches = []
        for points, uv, rgba, normal, tris, tex, blend in meshes:
            p = points - center
            projected = np.column_stack(((p * right).sum(axis=1) * scale + width / 2,
                                         height / 2 - (p * up).sum(axis=1) * scale,
                                         (p * eye).sum(axis=1)))
            diffuse = np.maximum(0, (normal * key).sum(axis=1))
            sheen = np.maximum(0, (normal * eye).sum(axis=1)) ** 9
            light = 0.64 + 0.44 * diffuse + 0.13 * sheen
            batches.append((blend, float(projected[:, 2].mean()), projected, uv, rgba, light, tris, tex))
        for blend, _, projected, uv, rgba, light, tris, tex in sorted(batches, key=lambda b: b[:2]):
            raster(projected, uv, rgba, light, tris, tex, blend, image, depth)
        yield Image.fromarray(image).resize((400, 212), Image.Resampling.LANCZOS)


def export_car(key, data, tables, paint_bank, out, np, raster):
    meshes = load_meshes(key, data, tables, paint_bank, np)
    frames = list(turntable(meshes, np, raster, 48))
    if any(frame.getbbox() is None for frame in frames):
        raise ValueError("empty turntable frame")
    stem = "car-" + "-".join(str(i) for i in key)
    with TemporaryDirectory(dir=out) as scratch:
        still = Path(scratch) / f"{stem}-still.webp"
        animation = Path(scratch) / f"{stem}.webp"
        frames[0].save(still, quality=92)
        frames[0].save(animation, save_all=True, append_images=frames[1:], duration=100,
                       loop=0, quality=70, method=6)
        still.replace(out / still.name)
        animation.replace(out / animation.name)


def export_stock_cars(data, out, np, raster):
    for model in sorted(model_paints()):
        stock = (model, 0, 0, 0, 0, 0, 143, 0, 0)
        meshes = load_meshes(stock, data, None, None, np)
        frame = next(turntable(meshes, np, raster, 1))
        if frame.getbbox() is None:
            raise ValueError(f"empty stock preview for model {model}")
        with TemporaryDirectory(dir=out) as scratch:
            poster = Path(scratch) / f"stock-{model}.webp"
            frame.save(poster, quality=88)
            poster.replace(out / poster.name)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--arcade", type=Path, help="original arcade root containing main and data")
    p.add_argument("--data", type=Path, help="private converted data root containing cars and wheels")
    p.add_argument("--generated-src", type=Path, help="generated dressdb.h, carwheel.h and neondb.h directory")
    p.add_argument("--paint-bank", type=Path, help="private original-converter WPPAINT1 custom paint bank")
    p.add_argument("--stock", action="store_true", help="export a stock poster for every arcade model ID")
    p.add_argument("--car", type=int, nargs=9, metavar="ID", action="append",
                   help="raw_model custom_color aero mirror wing bonnet wheel neon vinyl")
    args = p.parse_args()
    if not (args.arcade or args.car or args.stock):
        p.error("provide --arcade, --car or --stock")
    if (args.car or args.stock) and not args.data:
        p.error("--car and --stock require --data")
    if args.car and not args.generated_src:
        p.error("--car requires --generated-src")
    args.out.mkdir(parents=True, exist_ok=True)
    if args.arcade:
        export_plates(args.arcade, args.out)
    if args.car or args.stock:
        import numba
        import numpy as np
        raster = numba.njit(rasterize)
        for key in args.car or []:
            export_car(key, args.data, args.generated_src, args.paint_bank, args.out, np, raster)
        if args.stock:
            export_stock_cars(args.data, args.out, np, raster)


if __name__ == "__main__":
    main()
