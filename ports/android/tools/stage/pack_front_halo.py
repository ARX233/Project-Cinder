"""Convert original DX+ front lamp artwork and locator positions for local use.

Run with a trusted, extracted arcade root and a writable converted data directory:
    python3 tools/stage/pack_front_halo.py ARCADE_ROOT CONVERTED_DATA_DIR
Or add both sidecars to a fresh copy of an approved resource ZIP for Android:
    python3 tools/stage/pack_front_halo.py ARCADE_ROOT NEW_ZIP --resource-zip ORIGINAL_ZIP

The optional front_halo.wpk has one WPK2 texture, car_headlight.dds. The optional
front_halo.bin is HL01, a little-endian u32 record count, and records of a 48-byte
NUL-padded pack name, u8 kind (cars/characar), u8 body (stock/aero A/B/C), u16
locator count, and that many triples of little-endian f32 body-local positions.
The order is R1..R4, L1..L4, omitting absent locators, as in the arcade lamp
constructor at 0x08601002. Signed legacy conversion outputs are separate.
"""
import argparse
import math
from pathlib import Path
import re
import shutil
import struct
import zipfile

from igb import IGB
import lualite
from pack import encode16
from scene import obj_list
from tex import to_pil_original_order


ANCHOR_NAMES = tuple(f"HL_NULL_{side}{number}" for side in "RL" for number in range(1, 5))
BODIES = ("normal", "aero_a", "aero_b", "aero_c")
TEXTURE = "car_headlight.dds"


def lamp_anchors(path):
    model = IGB(path)
    scenes = model.of_type("igSceneInfo")
    if len(scenes) != 1:
        raise ValueError(f"expected one scene in {path}")
    anchors = {}
    pending = [model.ref(scenes[0][5])]
    visited = set()
    while pending:
        node = pending.pop()
        if node is None or node.mem is not None or node.index in visited:
            continue
        visited.add(node.index)
        pending.extend(reversed(obj_list(model, model.ref(node[7]))))
        name = model.string(node[2])
        # The arcade's findNamedNodeOfType returns the first hit in scene order.
        if node.type != "igTransform" or name not in ANCHOR_NAMES or name in anchors:
            continue
        if node[8] is None or len(node[8].raw) != 64:
            raise ValueError(f"invalid lamp locator matrix {name} in {path}")
        position = struct.unpack_from("<3f", node[8].raw, 48)
        if not all(math.isfinite(value) and abs(value) <= 100 for value in position):
            raise ValueError(f"invalid lamp locator position {name} in {path}")
        anchors[name] = position
    return tuple(anchors[name] for name in ANCHOR_NAMES if name in anchors)


def anchor_pack(root):
    records = []
    cache = {}
    for kind, directory in enumerate(("car", "characar")):
        for lua in sorted((root / "data" / directory).glob("*/car.lua")):
            name = lua.parent.name
            if not re.fullmatch(r"[A-Za-z0-9_]{1,47}", name):
                raise ValueError(f"unsupported car pack name {name}")
            body_paths = lualite.load(lua)["BodyIGB"]
            for body, body_name in enumerate(BODIES):
                relative = body_paths.get(body_name)
                if not relative:
                    continue
                path = root / relative
                if path not in cache:
                    cache[path] = lamp_anchors(path)
                positions = cache[path]
                if positions:
                    header = struct.pack("<48sBBH", name.encode("ascii"), kind, body, len(positions))
                    records.append(header + b"".join(struct.pack("<3f", *xyz) for xyz in positions))
    if not records:
        raise ValueError("no arcade front lamp locators found")
    return struct.pack("<4sI", b"HL01", len(records)) + b"".join(records)


def texture_pack(root):
    model = IGB(root / "data" / "effect" / "car_frontlight.igb")
    images = [image for image in model.of_type("igImage") if model.string(image[22]) == TEXTURE]
    if len(images) != 1:
        raise ValueError("expected one arcade front lamp atlas")
    image = images[0]
    if (image[2].i32, image[3].i32, image[11].i32) != (512, 512, 15):
        raise ValueError("unexpected arcade front lamp atlas format")
    width, height, fmt, pixels = encode16(to_pil_original_order(image, model.ref(image[13]).mem), 512)
    tex_off = 32
    data_off = tex_off + 64
    header = struct.pack("<4sIIIfIII", b"WPK2", 1, 0, 0, 4000.0, tex_off, data_off, data_off)
    entry = struct.pack("<48sHHIII", TEXTURE.encode("ascii"), width, height, fmt, data_off, len(pixels))
    return header + entry + pixels


def augment_zip(source, target, sidecars):
    with zipfile.ZipFile(source) as archive:
        if set(archive.namelist()) & {name for name, _ in sidecars}:
            raise ValueError("the resource ZIP already contains front lamp sidecars")
    with target.open("x+b") as output:
        try:
            with source.open("rb") as original:
                shutil.copyfileobj(original, output, 1024 * 1024)
            output.flush()
            with zipfile.ZipFile(output, "a", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as archive:
                for name, data in sidecars:
                    archive.writestr(name, data)
        except BaseException:
            output.close()
            target.unlink()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arcade_root", type=Path)
    parser.add_argument("output", type=Path, help="data directory, or a new ZIP with --resource-zip")
    parser.add_argument("--resource-zip", type=Path, help="approved converted resource ZIP to copy")
    args = parser.parse_args()
    sidecars = (("front_halo.wpk", texture_pack(args.arcade_root)), ("front_halo.bin", anchor_pack(args.arcade_root)))
    if args.resource_zip:
        augment_zip(args.resource_zip, args.output, sidecars)
        return
    args.output.mkdir(parents=True, exist_ok=True)
    if any((args.output / name).exists() for name, _ in sidecars):
        raise ValueError("the output directory already contains front lamp sidecars")
    for name, data in sidecars:
        with (args.output / name).open("xb") as out:
            out.write(data)


if __name__ == "__main__":
    main()
