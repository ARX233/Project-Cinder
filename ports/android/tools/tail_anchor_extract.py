#!/usr/bin/env python3
"""Extract verified static-subset anchors from caller-supplied trusted IGB v8.

Mapping JSON: {"entries":[{"car_id":0,"body_id":0,"igb":"/absolute/input.igb"}]}.
Caller verifies mappings. No asset discovery. Reject unknown nodes, animation,
non-identity ancestor transforms, duplicates and missing anchors. Field types
are restricted to a schema observed in one source file, not all IGBs. This legacy
parser is not a security sandbox for hostile IGB files. Never overwrite output.
Output is a static candidate, not a render-ready runtime asset.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "stage"))
from igb import IGB

IDENTITY = (1.,0.,0.,0., 0.,1.,0.,0., 0.,0.,1.,0., 0.,0.,0.,1.)
TYPES = {"igAttrSet", "igGroup", "igTransform", "igGeometry"}
NAMES = {"TAIL_L1", "TAIL_R1"}
LIMIT = 65535

def integer(field, label, expected_type):
    if field is None or field.type != expected_type or field.size != 4 or len(field.raw) != 4:
        raise ValueError("invalid " + label)
    return struct.unpack("<i", field.raw)[0]

def ref(f, field, label, expected_type="ObjectRef"): 
    if field is None:
        return None
    n = integer(field, label, expected_type)
    if n < 0:
        return None
    if n >= len(f.objects) or f.objects[n] is None or n in f.externals:
        raise ValueError("invalid or external " + label)
    return f.objects[n]

def children(f, node):
    if node[7] is None:
        raise ValueError("missing child list field")
    lst = ref(f, node[7], "child list")
    if lst is None:
        return []
    if lst.type != "igNodeList":
        raise ValueError("unsupported child list type")
    n = integer(lst[2], "child count", "Int")
    if n < 0 or n > LIMIT:
        raise ValueError("invalid child count")
    mem = ref(f, lst[4], "child storage", "MemoryRef")
    if n == 0:
        return []
    if mem is None or mem.mem is None or len(mem.mem) < 4*n:
        raise ValueError("truncated child storage")
    out = []
    for i in struct.unpack_from("<%di" % n, mem.mem):
        if i < 0 or i >= len(f.objects) or f.objects[i] is None or i in f.externals:
            raise ValueError("invalid child reference")
        out.append(f.objects[i])
    return out

def extract_scene(f):
    if f.version != 8 or f.slot_offset != 0:
        raise ValueError("only IGB v8 supported")
    infos = f.of_type("igSceneInfo")
    if len(infos) != 1:
        raise ValueError("expected exactly one scene")
    root = ref(f, infos[0][5], "scene root")
    if root is None:
        raise ValueError("missing scene root")
    found, active, visits = {}, set(), [0]
    def walk(node, path, parents_identity):
        visits[0] += 1
        if len(path) > 256 or visits[0] > LIMIT or node.index in active:
            raise ValueError("cyclic or excessive scene graph")
        if node.mem is not None or node.type not in TYPES:
            raise ValueError("unsupported scene node: " + node.type)
        active.add(node.index)
        name = None
        n = integer(node[2], "name", "String")
        if n >= 0:
            if n >= len(f.names):
                raise ValueError("invalid node name")
            name = f.names[n]
        matrix = IDENTITY
        if node.type == "igTransform":
            if node[10] is not None:
                raise ValueError("animated or unsupported transform slot 10")
            if integer(node[11], "animation reference", "ObjectRef") >= 0:
                raise ValueError("animated or unsupported transform")
            field = node[8]
            if field is None or field.type != "Matrix44f" or field.size != 64 or len(field.raw) != 64:
                raise ValueError("missing or invalid matrix")
            matrix = struct.unpack("<16f", field.raw)
            if not all(math.isfinite(x) for x in matrix):
                raise ValueError("non-finite matrix")
        if name in NAMES:
            if node.type != "igTransform":
                raise ValueError("anchor is not a transform")
            if not parents_identity:
                raise ValueError("non-identity ancestor transform")
            if name in found:
                raise ValueError("ambiguous or multiply instanced anchor: " + name)
            found[name] = {"matrix": list(matrix), "instance_path": list(path)}
        for i, child in enumerate(children(f, node)):
            walk(child, path + (i,), parents_identity and matrix == IDENTITY)
        active.remove(node.index)
    walk(root, (), True)
    if set(found) != NAMES:
        raise ValueError("missing tail anchor(s)")
    return found

def checked_path(text, existing):
    if not isinstance(text, str) or "\0" in text or not os.path.isabs(text):
        raise ValueError("path must be absolute")
    p = Path(text)
    if ".." in p.parts:
        raise ValueError("parent traversal forbidden")
    q = p if existing else p.parent
    for component in (q, *q.parents):
        if component.is_symlink():
            raise ValueError("symlink path forbidden")
    if existing and not stat.S_ISREG(p.stat().st_mode):
        raise ValueError("input must be regular")
    if not existing and not p.parent.is_dir():
        raise ValueError("output parent missing")
    return p

def convert(manifest, loader=IGB):
    if not isinstance(manifest, dict) or set(manifest) != {"entries"} or not isinstance(manifest["entries"], list) or not manifest["entries"]:
        raise ValueError("expected nonempty entries")
    records, keys = [], set()
    for item in manifest["entries"]:
        if not isinstance(item, dict) or set(item) != {"car_id", "body_id", "igb"}:
            raise ValueError("invalid mapping entry")
        car, body = item["car_id"], item["body_id"]
        if type(car) is not int or not 0 <= car <= 119 or type(body) is not int or not 0 <= body <= 3 or (car, body) in keys:
            raise ValueError("invalid or duplicate mapping key")
        keys.add((car, body))
        p = checked_path(item["igb"], True)
        if p.suffix.lower() != ".igb" or not 48 <= p.stat().st_size <= 32*1024*1024:
            raise ValueError("invalid IGB input")
        f = loader(str(p))
        records.append({"car_id": car, "body_id": body, "source_sha256": hashlib.sha256(f.buf).hexdigest(), "anchors": extract_scene(f)})
    return {"schema": "wmmt-tail-anchors", "version": 1, "matrix_layout": "row-major-row-vector", "space": "scene-root-parent; ancestors identity", "records": records}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifest"); ap.add_argument("output")
    a = ap.parse_args()
    manifest = checked_path(a.manifest, True)
    output = checked_path(a.output, False)
    if output.suffix.lower() != ".json":
        raise ValueError("output must be JSON")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    payload = (json.dumps(convert(data), ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)

if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, struct.error, IndexError, KeyError, TypeError) as exc:
        print("tail-anchor extraction failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
