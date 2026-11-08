"""Pack every car the car select offers (tools/cars.json, from cardb.py) into
data/cars/<folder>.wpk, dressed the way the arcade's car.lua describes it:

- BodyIGB.normal, the stock body: its switch nodes (the table at 0x97773c0 in main) set
  as clCarModelData::constructBody does for an untuned car: MUFFLER1, WINKER1, GLASS1,
  the driver, no roll bar, fog lights, winkers, reversing light or full tail lamps
  (LAMP_REAR_ON*). Its lamps by the car's mode: a race's cars
  (clCarConstructParam mode 0, the official machine's 3) show the switches of 0x9777460,
  the headlights on and the tail lamps half lit (LIGHT_ON, LAMP_REAR_HALF*); the menus'
  (mode 2) those of 0x9777450, all off (LIGHT_OFF, LAMP_REAR_OFF*). Each set is a chunk
  group of its own (pack.LAMP_ON, pack.LAMP_OFF) that the renderer picks. So are the
  dress-up parts' children MIRROR1..2, WING1..4 and BONNET1..4 (pack.MIRROR, WING, BONNET).
- the brake lamp model clCarLampSource loads beside the body (nsBrakeParts::
  BrakeLampFileNameGetFromCarId by the car and body, tools/brakelamps.json from
  tools/brakelampdb.py: the Evos' GSR and RS share brakelamp_mit_CE9A.igb), all of it glowing
  (additive): its switches as the constructor and clCarLampManager::update leave them, RUN
  off the brake and STOP on it (chunk groups pack.BRAKE_RUN, pack.BRAKE_STOP, picked by the
  renderer), STOP_HIGH and STOP_WING2 on it too for the wings BrakelampHasHighMount and
  BrakelampHasWingBrake name (pack.BRAKE_HIGH, pack.BRAKE_WING2 + those wings' bits), LIGHT
  and the rest always (pack.BRAKE_LIGHT), the winkers (WINKER_L/R, MW_L/R: the hazard, which
  no car turns on) never. All of it in a race only: clCarEffectManager makes the lamp source
  for the race's cars, and clMenuCar::init loads just the body and the tyres.
- TireStatus.file[1]: the stock tyre model (the second is the tuned car's; each holds all four
  tyres at the FD3S's places, TIRE_W1_FL..RR), moved to TireLocation.normal and scaled by
  TireStatus.scale[1] (front, rear: scale_x across, scale_zy for the diameter).
- the wheel of TireStatus.wheel_name in wheel_list.lua (its def_mid model, WHEEL_L / WHEEL_R
  at the hub), scaled like the tyre times the wheel's own scale. Its IGB blends it, but it
  is drawn with the solid meshes: in the blend pass nothing writes depth, so the hub axle
  behind the wheel face (a black hexagonal post) showed through the centre cap.
- BodyColorTexture.normal: paint 0 replaces the BaseTexture pages in place; paint k >= 1
  is stored as extra textures named "p<k>:<page texture>" that the game swaps in.
- ShadowIGB.normal: the shadow volume, as the pack's shadow group (render.c render_shadows).
- the tyres and wheels in chunk groups of their own per corner (pack.WHEEL + FL, FR, RL, RR),
  so the game can turn them as the arcade does.
- the tyres again as clCarModelData::constructTire sets them for a dress-up wheel (the
  construct param's wheel not 0x8f): TireStatus.scale[2] (TireScaleGet's first argument 1)
  at CustomTireLocation (TireLocationGet's second), in pack.CTIRE + corner. The wheel itself
  is drawn from its own pack (--wheels).
- lit (WPK3): normals, and per mesh the arcade's car program (car.cg, car_blend.cg) with its
  EnvMapTexture, SpecularMapTexture and uniformEnvMapPower, for the renderer's car lighting.

usage: pack_cars.py <arcade root> <out dir> [folder...]
       pack_cars.py <arcade root> <out dir> --wheels  (data/wheels/<name>_<set>.wpk, <menu3d>.wpk)
       pack_cars.py <arcade root> --wheel-table      (src/carwheel.h)
       pack_cars.py <arcade root> <out dir> --aero a|b|c [folder...]  (data/cars/<folder>_aeroA.wpk ...)
       pack_cars.py <arcade root> <out dir> --chara [folder...]
--chara packs the story rivals' own cars (data/characar/<folder>, the list RIVALDB_CHARA in
src/rivaldb.h) the same way, each with its one paint.
--wheels packs the dress-up wheels (src/dressdb.h DRESS_WHEELS): wheel_list.lua's last model
(the one a car's own wheel is packed from) with the texture set's textures, scaled by the
wheel's own scale, WHEEL_L in chunk group pack.WHEEL, WHEEL_R in pack.WHEEL + 1, at the hub;
and each one's GET screen model (data/menu3d/wheel/<menu3d>.igb) as it is.
--wheel-table writes, by car (CARDB_PACKS) and body (normal, aero A..C), where a dress-up wheel
goes and how it is scaled: CustomTireLocation and TireStatus.scale[2], front and rear.
"""
import json
import os
import re
import struct
import sys

import numpy as np
from PIL import Image

import lualite
import pack

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_TEX = 512


# switch nodes left out (constructBody's 0x94208c0 and 0x9777480 lists, not shown again):
# fog lights, full tail lamps, winkers, the reversing light, the roll bar, vinyls
HIDDEN = re.compile(r"^(FOG_LIGHT_ON|LAMP_REAR_ON\d*|L_WINKER_ON|R_WINKER_ON|BACK_LIGHT_ON|ROLLBAR|VINYL\d*)$")
# the lamps by mode: lit in a race, unlit in the menus
LAMP_ON = re.compile(r"^(LIGHT_ON|LAMP_REAR_HALF\d*)$")
LAMP_OFF = re.compile(r"^(LIGHT_OFF|LAMP_REAR_OFF\d*)$")
# the brake lamp model's switches
BRAKE_HIDDEN = re.compile(r"^(WINKER_L|WINKER_R|MW_L|MW_R)$")
# the stop lamps on the brake for some wings (bits 0..4 of the car's mask): STOP_HIGH, STOP_WING2
BRAKE_WINGS = {"STOP_HIGH": pack.BRAKE_HIGH, "STOP_WING2": pack.BRAKE_WING2}
# dress-up parts: the first of each is the stock one
PART = re.compile(r"^(MIRROR|MUFFLER|WING|BONNET|WINKER|GLASS)(\d+)$")
# the ones the dress-up changes (clCarModelData::constructBody's 0x8944dd0 by the construct
# param's mirror, wing and bonnet): every child, each a chunk group of its own
WORN = {"MIRROR": (pack.MIRROR, 2), "WING": (pack.WING, 4), "BONNET": (pack.BONNET, 4)}


def stock(m, wings=(0, 0), story_assembly=False):
    """wings: brake-lamp wing masks; story_assembly retains original forced variants."""
    if story_assembly:
        from story_part_groups import story_part_group
        group = story_part_group(m)
        if group is not None:
            m["group"] = group
            return True
    for name in m["path"]:
        p = PART.match(name)
        if p and p.group(1) in WORN and 1 <= int(p.group(2)) <= WORN[p.group(1)][1]:
            m["group"] = WORN[p.group(1)][0] + int(p.group(2)) - 1
            continue
        if HIDDEN.match(name) or (p and p.group(2) != "1"):
            return False
        if BRAKE_HIDDEN.match(name):
            return False
        if LAMP_ON.match(name):
            m["group"] = pack.LAMP_ON
        elif LAMP_OFF.match(name):
            m["group"] = pack.LAMP_OFF
        elif name == "RUN":
            m["group"] = pack.BRAKE_RUN
        elif name == "STOP":
            m["group"] = pack.BRAKE_STOP
        elif name in BRAKE_WINGS:
            mask = wings[name == "STOP_WING2"]
            if not mask:
                return False
            m["group"] = BRAKE_WINGS[name] + mask
    if "group" not in m and m["path"] and m["path"][0].lower().startswith("brakelamp_"):
        m["group"] = pack.BRAKE_LIGHT
    return True


# Wheel-only conversion must not require unrelated generated car metadata at import.
# A signed-recipe executor may explicitly supply its verified, original-derived table.
# Historical command-line car packing retains its lazy local-file behavior.
BRAKE_LAMPS = None
CAR_IDS = None


def configure_brake_lamps(db):
    global BRAKE_LAMPS, CAR_IDS
    if not isinstance(db, dict) or set(db) != {"cars", "lamps"}:
        raise ValueError("invalid brake-lamp support table")
    if not isinstance(db["cars"], dict) or not isinstance(db["lamps"], dict):
        raise ValueError("invalid brake-lamp support maps")
    if any(not isinstance(k, str) or type(v) is not int or not 0 <= v < 120
           for k, v in db["cars"].items()):
        raise ValueError("invalid brake-lamp car identity")
    for key, row in db["lamps"].items():
        if (not isinstance(key, str) or not isinstance(row, list) or len(row) != 3 or
                not isinstance(row[0], str) or not re.fullmatch(r"[A-Za-z0-9_]+", row[0]) or
                any(type(v) is not int or not 0 <= v <= 31 for v in row[1:])):
            raise ValueError("invalid brake-lamp entry")
    BRAKE_LAMPS = db
    CAR_IDS = {k.lower(): v for k, v in db["cars"].items()}


def brake_lamp(folder, body):
    """the brake lamp model's path in the arcade's data and its STOP_HIGH and STOP_WING2
    masks for the car of pack `folder` with body normal or aero_a..aero_c"""
    if BRAKE_LAMPS is None:
        with open(os.path.join(HERE, "..", "brakelamps.json")) as source:
            configure_brake_lamps(json.load(source))
    car = CAR_IDS.get(folder.lower())
    row = BRAKE_LAMPS["lamps"].get("%s %d" % (car, 0 if body == "normal" else " abc".index(body[-1])))
    return ("data/car/brakelamp/brakelamp_%s.igb" % row[0], (row[1], row[2])) if row else (None, (0, 0))


def placement(scale, at):
    """row-vector matrix: scale (x, y, z), then translate to `at`"""
    m = np.diag([scale[0], scale[1], scale[2], 1.0]).astype(np.float32)
    m[3, :3] = at
    return m


def corner(k, side, base=pack.WHEEL):
    """chunk group of a tyre and wheel: front (k 0) or rear, left (+x) or right; each turns on
    its own (clCarDisp::update's tyre nodes, render.c)"""
    return base + 2 * k + (0 if side > 0 else 1)


def tyres(loc, scale, base=pack.WHEEL):
    """per mesh of a tyre model: its corner from where the model puts it"""
    def fn(m):
        t = m["matrix"][3]
        k = 0 if t[2] > 0 else 1
        side = 1.0 if t[0] > 0 else -1.0
        s = scale[k]
        local = m["matrix"].copy()
        local[3, :3] = 0
        return [(local @ placement((s["scale_x"], s["scale_zy"], s["scale_zy"]), (side * loc[k][0], 0, loc[k][1])),
                 corner(k, side, base))]
    return fn


def wheels(loc, scale, own):
    """WHEEL_L on the left (+x) hubs, WHEEL_R on the right"""
    def fn(m):
        side = 1.0 if any(n.endswith("_L") for n in m["path"]) else -1.0
        out = []
        for k in (0, 1):
            s = scale[k]
            sc = (s["scale_x"] * own[0], s["scale_zy"] * own[1], s["scale_zy"] * own[2])
            out.append((m["matrix"] @ placement(sc, (side * loc[k][0], 0, loc[k][1])), corner(k, side)))
        return out
    return fn


def custom_tyres(car, body):
    """a dress-up wheel's tyre places and scales (car_common.lua TireLocationGet with hwhel 1,
    TireScaleGet with hinc 1; each falls back to the stock one)"""
    ts = car["TireStatus"]
    loc = (car.get("CustomTireLocation") or {}).get(body) or car["TireLocation"][body]
    scale = ts["scale"][1] if len(ts["scale"]) > 1 else ts["scale"][0]
    return loc, scale


def pack_wheel(root, wheel, tex_set, out):
    """a dress-up wheel, at the hub with its own scale: WHEEL_L in pack.WHEEL, WHEEL_R in + 1"""
    own = np.diag([wheel.get("scale_x", 1.0), wheel.get("scale_y", 1.0), wheel.get("scale_z", 1.0), 1.0]).astype(np.float32)
    igb = f"{root}/{wheel['igb_files'][-1]}"
    swaps = {}
    sets = wheel.get("texture") or []
    if tex_set < len(sets):
        swaps[wheel["base_textures"][-1].rsplit(".", 1)[0]] = f"{root}/{sets[tex_set][-1]}"
    side = lambda m: 0 if any(n.endswith("_L") for n in m["path"]) else 1
    places = [(igb, lambda m: [(m["matrix"] @ own, pack.WHEEL + side(m))])]
    textures, order, meshes, _ = pack.collect([], None, (MAX_TEX,) * 3, places, swaps, lit=True,
                                              opaque=lambda m: True)
    short = {n: n.replace("\\", "/").rsplit("/", 1)[-1] for n in order}
    textures = {short.get(n, n): t for n, t in textures.items()}
    order = [short[n] for n in order]
    meshes = [(g, short.get(n, n), fl, v, t, mat and (mat[0], short.get(mat[1], mat[1]), short.get(mat[2], mat[2]), mat[3]))
              for g, n, fl, v, t, mat in meshes]
    pack.write(out, textures, order, pack.split_by_chunk(meshes, 0), 0, lit=True)
    print("  %s: %d meshes, %d textures" % (os.path.basename(out), len(meshes), len(order)))


def pack_menu_wheel(root, name, out):
    """the GET screen's wheel (data/menu3d/wheel/<name>.igb) as it is, in chunk 0"""
    places = [(f"{root}/data/menu3d/wheel/{name}.igb", lambda m: [(m["matrix"], 0)])]
    pack.scene.NORMALS_1_1 = True  # its normals are in the old vertex format's block 1
    try:
        textures, order, meshes, _ = pack.collect([], None, (MAX_TEX,) * 3, places, None, lit=True,
                                                  opaque=lambda m: True)
    finally:
        pack.scene.NORMALS_1_1 = False
    short = {n: n.replace("\\", "/").rsplit("/", 1)[-1] for n in order}
    textures = {short.get(n, n): t for n, t in textures.items()}
    order = [short[n] for n in order]
    meshes = [(g, short.get(n, n), fl, v, t, mat and (mat[0], short.get(mat[1], mat[1]), short.get(mat[2], mat[2]), mat[3]))
              for g, n, fl, v, t, mat in meshes]
    pack.write(out, textures, order, pack.split_by_chunk(meshes, 0), 0, lit=True)
    print("  %s: %d meshes, %d textures" % (os.path.basename(out), len(meshes), len(order)))


def wheel_table(root):
    """src/carwheel.h: by CARDB_PACKS and body, the dress-up wheel's places and scales"""
    src = open(f"{HERE}/../../src/cardb.h").read()
    body_src = src.split("CARDB_PACKS[", 1)[1].split("};", 1)[0]
    packs = re.findall(r'"([^"]+)"', body_src)
    out = ["/* Generated by tools/stage/pack_cars.py --wheel-table from the cars' car.lua: do not edit. */",
           "#ifndef CARWHEEL_H", "#define CARWHEEL_H", "",
           "/* by CARDB_PACKS and body (normal, aero A, B, C): a dress-up wheel's hub, front and rear",
           " * (the left one's x and z: CustomTireLocation), and its scale across and in diameter",
           " * (TireStatus.scale[2]'s scale_x, scale_zy) */",
           "static const float CARWHEEL[%d][4][2][4] = {" % len(packs)]
    for folder in packs:
        car = lualite.load(f"{root}/data/car/{folder}/car.lua")
        out.append("  { /* %s */" % folder)
        for body in ("normal", "aero_a", "aero_b", "aero_c"):
            b = body if body in car["TireLocation"] else "normal"
            loc, scale = custom_tyres(car, b)
            f = lambda v: repr(float(v)) + "f"  # 1.0f, not 1f
            out.append("    { " + ", ".join("{ %s, %s, %s, %s }" % tuple(map(f, (loc[k][0], loc[k][1], scale[k]["scale_x"], scale[k]["scale_zy"])))
                                         for k in (0, 1)) + " },")
        out.append("  },")
    out += ["};", "", "#endif", ""]
    open(f"{HERE}/../../src/carwheel.h", "w").write("\n".join(out))


def read_textures(path):
    """a pack's textures, name -> (w, h, fmt, bytes) as pack.write took them"""
    if not os.path.exists(path):
        return {}
    data = open(path, "rb").read()
    n_tex, tex_off = struct.unpack_from("<I", data, 4)[0], struct.unpack_from("<I", data, 20)[0]
    out = {}
    for i in range(n_tex):
        name, w, h, fmt, off, size = struct.unpack_from("<48sHHIII", data, tex_off + 64 * i)
        out[name.split(b"\0")[0].decode("latin1")] = (w, h, fmt, data[off:off + size])
    return out


# These stock wheel images are DXT1 component-order 100 in the arcade assets.  The
# original loader converts them to platform order 107 (swapping red and blue).
# Restrict the correction to the exact car, original wheel and diffuse image; do
# not apply it to other Subaru images or the independently packed dress-up wheels.
STOCK_WHEEL_BGR = {
    "sub_gc8": ("sub_gc8_wheel", "gc8_wheel01_mid.dds"),
    "sub_gc8_ra": ("sub_gc8_wheel", "gc8_wheel01_mid.dds"),
    "sub_gdb": ("sub_gdb_wheel", "gdb_wheel01_mid.dds"),
    "sub_gdb_specc": ("sub_gdb_wheel", "gdb_wheel01_mid.dds"),
    "sub_gdbf": ("sub_gdbf_wheel", "gdbf_wheel01_mid.dds"),
}


def fix_stock_wheel_bgr(folder, kind, wheel, textures, meshes):
    """Swap RGB565 channels only for the verified stock wheel diffuse texture.

    DXT1 endpoint swapping needs index remapping when endpoint order reverses;
    swapping decoded pixels instead preserves the decoded palette and alpha.
    Fail before writing if an alternative encoding or image source is in use.
    """
    target = STOCK_WHEEL_BGR.get(folder.lower()) if kind == "car" else None
    if not target:
        return
    if not wheel or wheel.get("name", "").lower() != target[0]:
        raise ValueError("unexpected stock wheel for " + folder)
    matches = [n for n in textures if n.replace("\\", "/").rsplit("/", 1)[-1].lower() == target[1]]
    if len(matches) != 1:
        raise ValueError("expected one stock wheel diffuse texture for " + folder)
    name = matches[0]
    if pack.TEX_UPSCALED:
        raise ValueError("stock wheel correction cannot verify upscaled image source")
    refs = [m for m in meshes if m[1] == name]
    if not refs or any(not (pack.WHEEL <= m[0] < pack.WHEEL + 4) for m in refs):
        raise ValueError("stock wheel image also used outside its wheel meshes")
    if any(m[5] is not None and name in (m[5][1], m[5][2]) for m in meshes):
        raise ValueError("stock wheel image also used as a material map")
    w, h, fmt, data = textures[name]
    if fmt != 0 or w <= 0 or h <= 0 or len(data) != w * h * 2:
        raise ValueError("stock wheel requires complete opaque RGB565 texture")
    px = np.frombuffer(data, dtype="<u2")
    swapped = ((px & 0x001f) << 11) | (px & 0x07e0) | ((px >> 11) & 0x001f)
    textures[name] = (w, h, fmt, swapped.astype("<u2").tobytes())


def pack_car(root, folder, npaint, wheel_list, out, kind="car", body="normal", story_assembly=False):
    """body: normal, or the dress-up aero set aero_a, aero_b, aero_c (car.lua's keys)"""
    if type(story_assembly) is not bool or (story_assembly and kind != "car"):
        raise ValueError("story_assembly is an opt-in player-car-only boolean")
    car = lualite.load(f"{root}/data/{kind}/{folder}/car.lua")
    if body not in car["BodyIGB"]:
        print(folder, "has no", body, "(the gem cars only have aero A)")
        return
    path = lambda p: f"{root}/{p}"
    ts = car["TireStatus"]
    loc = car["TireLocation"][body]
    scale = ts["scale"][0]
    places = [(path(ts["file"][0]), tyres(loc, scale))]
    wheel = next((w for w in wheel_list if w.get("name") == ts.get("wheel_name")), None)
    if wheel and wheel.get("igb_files"):
        own = (wheel.get("scale_x", 1.0), wheel.get("scale_y", 1.0), wheel.get("scale_z", 1.0))
        places.append((path(wheel["igb_files"][-1]), wheels(loc, scale, own)))
    else:
        print(folder, "no wheel", ts.get("wheel_name"))
    if kind == "car":
        cloc, cscale = custom_tyres(car, body)
        places.append((path(ts["file"][0]), tyres(cloc, cscale, pack.CTIRE)))
    # some car.lua end a table with an empty "-- ダミー" aero_c that overrides the real one:
    # the stock body's textures and paints then
    tex = lambda t: car[t][body] if car[t].get(body) else car[t]["normal"]
    base = {k: v.rsplit(".", 1)[0] for k, v in tex("BaseTexture").items() if v}
    paints = tex("BodyColorTexture")[:npaint]
    swaps = {base[k]: path(paints[0][k]) for k in base if paints[0].get(k)}
    models = [(0, path(car["BodyIGB"][body]))]
    lamp, wings = brake_lamp(folder, body)
    if lamp and os.path.exists(path(lamp)):
        models.append((0, path(lamp)))
    else:
        print(folder, "no brake lamp model", lamp)
    textures, order, meshes, _ = pack.collect(models, None, (MAX_TEX,) * 3,
                                              places, swaps, keep=lambda m: stock(m, wings, story_assembly), lit=True,
                                              opaque=lambda m: any(n.startswith("WHEEL_") for n in m["path"]))
    fix_stock_wheel_bgr(folder, kind, wheel, textures, meshes)
    # name the textures as car.lua does, so the paint names fit the 47 characters a pack keeps
    short = {n: n.replace("\\", "/").rsplit("/", 1)[-1] for n in order}
    textures = {short.get(n, n): t for n, t in textures.items()}
    order = [short[n] for n in order]
    meshes = [(g, short.get(n, n), fl, v, t, mat and (mat[0], short.get(mat[1], mat[1]), short.get(mat[2], mat[2]), mat[3]))
              for g, n, fl, v, t, mat in meshes]
    by_key = {pack.tex_key(n): n for n in order}
    extra = 0
    for i, p in enumerate(paints[1:], 1):
        for k, key in base.items():
            if not p.get(k) or p.get(k) == paints[0].get(k) or key not in by_key or not os.path.exists(path(p[k])):
                continue
            name = "p%d:%s" % (i, by_key[key])
            textures[name] = pack.encode16(pack.load_image_file(path(p[k])), MAX_TEX)
            order.append(name)
            extra += 1
    missing = [key for key in base.values() if key not in by_key]
    if missing:
        print(folder, "body has no texture", missing)
    if car.get("ShadowIGB", {}).get(body):
        meshes += pack.shadow_meshes(path(car["ShadowIGB"][body]), lit=True)
    else:
        print(folder, "no shadow")
    if body != "normal":
        # an aero set's pack keeps only the textures the stock pack does not have: the rest
        # it borrows from that pack in the game (size 0 here; render.c wpk_share)
        stock_tex = read_textures(os.path.join(os.path.dirname(out), f"{folder}.wpk"))
        shared = [n for n in order if stock_tex.get(n) == textures[n]]
        for n in shared:
            w, h, fmt, _ = textures[n]
            textures[n] = (w, h, fmt, b"")
        print("  %s: %d of %d textures from the stock pack" % (folder, len(shared), len(order)))
    # one chunk: in chunks of any size the car would be cut at x = 0 and z = 0, four times the draws
    pack.write(out, textures, order, pack.split_by_chunk(meshes, 0), 0, lit=True)
    print("  %s: %d paints, %d extra paint textures" % (folder, len(paints), extra))


def main():
    root = sys.argv[1]
    if sys.argv[2:3] == ["--wheel-table"]:
        wheel_table(root)
        return
    out_dir = sys.argv[2]
    want = sys.argv[3:]
    wheel_list = lualite.load(f"{root}/data/wheel_list.lua", {"AbsPath": "data/"})["WheelList"]
    os.makedirs(out_dir, exist_ok=True)
    if want[:1] == ["--wheels"]:
        src = open(f"{HERE}/../../src/dressdb.h").read()
        for _, tex_set, name, menu3d in re.findall(r'^  \{ (\d+), (\d+), "([^"]+)", "([^"]+)" \},$', src, re.M):
            wheel = next(w for w in wheel_list if w.get("name") == name)
            pack_wheel(root, wheel, int(tex_set), f"{out_dir}/{name}_{tex_set}.wpk")
            pack_menu_wheel(root, menu3d, f"{out_dir}/{menu3d}.wpk")
        return
    if want[:1] == ["--chara"]:
        src = open(f"{HERE}/../../src/rivaldb.h").read()
        folders = re.findall(r'^  "([^"]+)",$', src.split("RIVALDB_CHARA[", 1)[1], re.M)
        for folder in folders:
            if want[1:] and folder not in want[1:]:
                continue
            pack_car(root, folder, 1, wheel_list, f"{out_dir}/{folder}.wpk", "characar")
        return
    body = "normal"
    if want[:1] == ["--aero"]:
        body, want = "aero_" + want[1].lower(), want[2:]
    db = json.load(open(f"{HERE}/../cars.json"))
    for folder, npaint in db["packs"].items():
        if want and folder not in want:
            continue
        name = folder if body == "normal" else f"{folder}_aero{body[-1].upper()}"
        pack_car(root, folder, npaint, wheel_list, f"{out_dir}/{name}.wpk", body=body)


if __name__ == "__main__":
    main()
