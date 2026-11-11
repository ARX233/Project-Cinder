"""Convert the reviewed 3DX+ car aura IGBs to an optional WPK2 sidecar."""
import argparse
import hashlib
import re
from pathlib import Path

import numpy as np

import pack as wpk
from scene import meshes, obj_list
from tex import to_pil_original_order

COLORS = ("green", "purple", "red", "blue")
NAME = "mileage-aura.wpk"


def aura_motion(igb, node, tracks, translation=0.0, rise=0.0):
    if node is None:
        return
    if node.type == "igTransform":
        sequence = igb.ref(node[10])
        if sequence is not None and sequence.type == "igTransformSequence1_5":
            values = igb.ref(sequence[2])
            key = np.frombuffer(igb.ref(values[4]).mem, "<f4").reshape(-1, 3)
            matrix = np.frombuffer(node[8].raw, "<f4").reshape(4, 4)
            if key.shape != (2, 3) or key[0, 1] not in (2, 4):
                raise ValueError("Unexpected original aura translation")
            translation, rise = float(matrix[3, 1]), float(key[0, 1])
    if node.type == "igGeometry":
        tracks.append((igb.string(node[2]), translation, rise))
    for child in obj_list(igb, igb.ref(node[7])):
        aura_motion(igb, child, tracks, translation, rise)


def pack(original_root, output):
    textures, batches = {}, []
    directory = Path(original_root) / "data" / "effect"
    for color, name in enumerate(COLORS):
        for glow in (False, True):
            path = directory / f"car_aura_{'glow_' if glow else ''}{name}.igb"
            model, geometry = meshes(path)
            tracks = []
            aura_motion(model, model.ref(model.of_type("igSceneInfo")[0][5]), tracks)
            if len(geometry) != len(tracks) or len(tracks) != (1 if glow else 17):
                raise ValueError("Unexpected original aura geometry")
            for mesh, (node, translation, rise) in zip(geometry, tracks):
                if mesh["name"] != node or mesh["state"]["blend_func"] != (4, 1):
                    raise ValueError("Unexpected original aura blend or node order")
                group = color * 16 + 11 if glow else color * 16 + 1 + 2 * (int(mesh["path"][-1][-2:]) - 1) + int(rise == 4)
                image = mesh["image"]
                texture = model.string(image[22])
                if texture not in textures:
                    pixels = to_pil_original_order(image, model.ref(image[13]).mem)
                    textures[texture] = wpk.encode16(pixels, 256)
                v = mesh["verts"]
                verts = np.zeros(len(v["pos"]), wpk.VERTEX)
                verts["pos"] = (np.c_[v["pos"], np.ones(len(verts))] @ mesh["matrix"])[:, :3]
                verts["pos"][:, 1] -= translation
                verts["uv"] = v["uv"]
                verts["rgba"] = v["color"][:, [2, 1, 0, 3]] if "color" in v else 255
                batches.append((group, texture, 2, verts, mesh["tris"], None))
    wpk.write(output, textures, list(textures), wpk.split_by_chunk(batches, 0), 0)



def pose_header(original_root, card_db, output):
    """Extract the arcade's per-body AuraScale/AuraOffset (car_common.lua getters)."""
    import lualite

    db = Path(card_db).read_text().split("CARDB_PACKS[", 1)[1].split("};", 1)[0]
    names = sorted(re.findall(r'"([A-Za-z0-9_]+)"', db))
    lines = ["/* Extracted by pack_mileage_aura.py from the original car.lua tables. */",
             "static const struct { const char *pack; float body[4][6]; } MILEAGE_AURA_POSE[] = {"]
    for name in names:
        lua = lualite.load(Path(original_root) / "data" / "car" / name / "car.lua")
        rows = []
        for index, body in enumerate(("normal", "aero_a", "aero_b", "aero_c")):
            row = []
            for key, default in (("AuraScale", 1), ("AuraOffset", 0)):
                table = lua.get(key)
                vec = table.get(body) if isinstance(table, dict) else table[index] if table and len(table) > index else None
                row.extend(float(vec[i]) if vec is not None and len(vec) > i else default for i in range(3))
            rows.append("{" + ", ".join(f"{float(v):.7f}".rstrip("0").rstrip(".") for v in row) + "}")
        lines.append(f'  {{ "{name}", {{' + ", ".join(rows) + "} },")
    lines.append("};")
    Path(output).write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pose-header", type=Path, metavar="CARDB_H", help="emit the C pose table instead of a WPK")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists")
    if args.pose_header:
        pose_header(args.original_root, args.pose_header, args.output)
        return
    pack(args.original_root, args.output)
    print(f"{args.output} {args.output.stat().st_size} bytes")
    with args.output.open("rb") as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    print(digest.hexdigest())


if __name__ == "__main__":
    main()
