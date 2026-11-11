"""The versus' pre-race scene (clRaceThread::JoMatchingInformationMove): the cars flying in by
data/menu3d/demo/Battle_anm.igb, for src/battle.h.

The arcade plays the IGB's animation (clModelObject::setAnimFrame(min(frame, 200) * 1e7 ns):
10 ms a game frame) and reads its transforms' own (local) matrices each frame:
  body  = BODY_ROOT * ROOT (row vectors: BODY_ROOT first), each car's body;
  tyres = TIRE_ROOT * ROOT, each car's tyre set;
  wheel k = rotation(TIRE_ROT_k) * rotation(TIRE_k) (the spin, then the steer), at the car's
  own wheel spots;
  the camera at CAM_BODY's translation looking at CAM_AIM's.
Matrices here are row-major with row vectors, the same floats as a column-major GL matrix.

usage: pack_battle.py <arcade root (has data/menu3d/demo)> out.h      (writes the header)
       pack_battle.py <arcade root> --probe                           (prints what the IGB holds)
       pack_battle.py <arcade root> --target out.inc                   (Ghost matchup poses)
"""
import os
import struct
import sys
from collections import Counter

import numpy as np

import scene
from igb import IGB

FILE = "data/menu3d/demo/Battle_anm.igb"
FRAMES = 201  # 0..200 (the arcade clamps the frame at 200)
WHEELS = ("FL", "FR", "RL", "RR")


def quat_matrix(q):
    """igQuaternionf (x, y, z, w) -> the 3x3 rotation of a row-vector matrix (as igTransform's)"""
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def lst(f, o, fmt, k):
    if o is None:
        return None
    n = o[2].i32
    m = f.ref(o[4]).mem
    return np.array([struct.unpack_from("<" + fmt, m, i * k) for i in range(n)], np.float64)


class Node:
    def __init__(self, f, o):
        self.name = f.string(o[2]) if o[2] is not None else ""
        self.static = np.frombuffer(o[8].raw, "<f4").reshape(4, 4).astype(np.float64)
        self.seq = None
        sq = f.ref(o[11]) if o[11] is not None else None
        if sq is not None and sq.type.startswith("igTransformSequence"):
            t = lst(f, f.ref(sq[11]), "q", 8)
            self.seq = (t[:, 0] / 1e9 if t is not None else None, lst(f, f.ref(sq[2]), "3f", 12),
                        lst(f, f.ref(sq[3]), "4f", 16), lst(f, f.ref(sq[4]), "3f", 12))
        self.seq_type = sq.type if sq is not None else None

    def local(self, t):
        """the node's own matrix at t seconds (the keys held past the ends)"""
        if self.seq is None or self.seq[0] is None:
            return self.static
        times, T, R, S = self.seq
        m = self.static.copy()
        k = int(np.searchsorted(times, t, side="right")) - 1
        k0, k1 = max(0, min(k, len(times) - 1)), max(0, min(k + 1, len(times) - 1))
        a = 0.0 if k1 == k0 else min(1.0, max(0.0, (t - times[k0]) / (times[k1] - times[k0])))
        if R is not None and len(R):
            q0, q1 = R[min(k0, len(R) - 1)], R[min(k1, len(R) - 1)]
            if np.dot(q0, q1) < 0:
                q1 = -q1
            q = q0 * (1 - a) + q1 * a  # nlerp: the keys are a frame apart
            q /= np.linalg.norm(q)
            m[:3, :3] = quat_matrix(q)
        if S is not None and len(S) == len(times):
            s = S[k0] * (1 - a) + S[k1] * a
            m[:3, :3] = np.diag(s) @ m[:3, :3]
        if T is not None and len(T):
            m[3, :3] = T[min(k0, len(T) - 1)] * (1 - a) + T[min(k1, len(T) - 1)] * a
        return m


def load(root, filename=FILE):
    path = os.path.join(root, filename)
    f = IGB(path)
    nodes = {}
    for o in f.of_type("igTransform"):
        n = Node(f, o)
        nodes[n.name] = n
    return path, f, nodes


def probe(root):
    path, f, nodes = load(root)
    print(FILE, os.path.getsize(path), "bytes")
    print("types:", dict(Counter(o.type for o in f.objects if o is not None and o.mem is None)))
    for name, n in nodes.items():
        if n.seq is None:
            print("  %-14s static, translation %s" % (name, n.static[3, :3].round(3)))
            continue
        t, T, R, S = n.seq
        print("  %-14s %s keys %d t %.3f..%.3f  T0 %s T1 %s  R0 %s  S %s" % (
            name, n.seq_type, len(t) if t is not None else -1, t[0] if t is not None else 0, t[-1] if t is not None else 0,
            T[0].round(2) if T is not None else None, T[-1].round(2) if T is not None else None,
            R[0].round(3) if R is not None else None, None if S is None else S[0].round(3)))
    try:
        _, ms = scene.meshes(path)
        print("meshes:", len(ms), [(m["name"], len(m["verts"]["pos"])) for m in ms[:12]])
    except Exception as e:  # noqa: BLE001 (a probe: say it and go on)
        print("meshes: failed", e)
    for fr in (0, 40, 70, 100, 135, 200):
        b = nodes["BODY_ROOT"].local(fr * 0.01) @ nodes["ROOT"].local(fr * 0.01)
        print("f%3d body pos %s  eye %s  at %s" % (fr, b[3, :3].round(2), nodes["CAM_BODY"].local(fr * 0.01)[3, :3].round(2),
                                                  nodes["CAM_AIM"].local(fr * 0.01)[3, :3].round(2)))


def floats(v, fmt="%.4f"):
    """C float literals, the trailing zeros off (1.0000 -> 1.0f)"""
    out = []
    for x in v:
        t = (fmt % x).rstrip("0")
        out.append((t + "0" if t.endswith(".") else t) + "f")
    return ", ".join(out)


def pack_target(root, out):
    """TgMatchingInformationYield samples at 10 ms, clamped at frame 200."""
    _, _, nodes = load(root, "data/menu3d/demo/Target_anm.igb")
    rows = []
    for frame in range(FRAMES):
        t = frame * 0.01
        body = nodes["BODY_ROOT"].local(t) @ nodes["ROOT"].local(t)
        wheels = []
        for w in WHEELS:
            wheel = nodes["TIRE_ROT_" + w].local(t) @ nodes["TIRE_" + w].local(t)
            wheels.append(floats(wheel[:3, :3].reshape(-1)))
        eye = nodes["CAM_BODY"].local(t)[3, :3]
        aim = nodes["CAM_AIM"].local(t)[3, :3]
        rows.append((floats(body[:, :3].reshape(-1)), wheels, floats(eye), floats(aim)))
    while len(rows) > 1 and rows[-1] == rows[-2]:
        rows.pop()

    with open(out, "w") as h:
        h.write("/* Generated by tools/stage/pack_battle.py --target from Target_anm.igb.\n"
                " * BODY_ROOT * ROOT (four rows of XYZ), local wheel rotations (FL FR RL RR),\n"
                " * CAM_BODY and CAM_AIM translations at 10 ms intervals. Hold the last pose. */\n"
                "static const struct { float body[12], wheel[4][9], eye[3], aim[3]; } GHOST_INTRO_POSE[] = {\n")
        for body, wheels, eye, aim in rows:
            wheel_rows = ", ".join("{ " + w + " }" for w in wheels)
            h.write(f"  {{ {{ {body} }},\n    {{ {wheel_rows} }},\n    {{ {eye} }}, {{ {aim} }} }},\n")
        h.write("};\n")


def main():
    root = sys.argv[1]
    if sys.argv[2] == "--target":
        pack_target(root, sys.argv[3])
        return
    if sys.argv[2] == "--probe":
        probe(root)
        return
    _, _, nodes = load(root)
    out = sys.argv[2]
    rows = []
    for fr in range(FRAMES):
        t = fr * 0.01
        root_m = nodes["ROOT"].local(t)
        body = nodes["BODY_ROOT"].local(t) @ root_m
        tyre = nodes["TIRE_ROOT"].local(t) @ root_m
        wheels = []
        for w in WHEELS:
            r = nodes["TIRE_ROT_" + w].local(t)[:3, :3] @ nodes["TIRE_" + w].local(t)[:3, :3]
            wheels.append(r)
        eye, at = nodes["CAM_BODY"].local(t)[3, :3], nodes["CAM_AIM"].local(t)[3, :3]
        rows.append((body, tyre, wheels, eye, at))
    with open(out, "w") as h:
        h.write("/* Generated by tools/stage/pack_battle.py from the arcade's %s: do not edit. */\n" % FILE)
        h.write("#ifndef BATTLE_H\n#define BATTLE_H\n\n")
        h.write("/* clRaceThread::JoMatchingInformationMove's animation, a game frame each (10 ms of it):\n"
                " * body BODY_ROOT * ROOT, tyre TIRE_ROOT * ROOT (column-major GL matrices), wheel the\n"
                " * rotations TIRE_ROT_k * TIRE_k (FL FR RL RR, column-major 3x3), the camera CAM_BODY\n"
                " * looking at CAM_AIM */\n")
        h.write("#define BATTLE_FRAMES %d\n" % FRAMES)
        h.write("typedef struct {\n  float body[16], tyre[16];\n  float wheel[4][9];\n  float eye[3], at[3];\n} battle_frame;\n\n")
        h.write("static const battle_frame BATTLE[BATTLE_FRAMES] = {\n")
        for body, tyre, wheels, eye, at in rows:
            h.write("  { { %s },\n    { %s },\n    { %s },\n    { %s }, { %s } },\n" % (
                floats(body.reshape(-1)), floats(tyre.reshape(-1)),
                " }, { ".join(floats(w.reshape(-1)) for w in wheels).join(("{ ", " }")),
                floats(eye, "%.3f"), floats(at, "%.3f")))
        h.write("};\n\n#endif\n")


if __name__ == "__main__":
    main()
