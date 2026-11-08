"""Decode igImage pixel data to RGBA via Pillow's DDS reader.

Legacy to_pil output stays byte-for-byte stable. The new, explicitly selected
order-aware entry point is for a separately reviewed conversion recipe only;
existing ResourceStore/profile output must never be rewritten in place.
"""
import io
import struct

from PIL import Image

# igImage pixel formats seen so far -> DDS FourCC
FOURCC = {14: b"DXT1", 15: b"DXT3", 16: b"DXT5"}


def _original_dxt_to_ogl(data, fmt):
    """Static reconstruction of original DEFAULT->OGL compressed colour order.

    ELF 2e6591...: DXT1 0x08ba5230; DXT3 and DXT5 0x08ba53a0.
    OGL=107 registration: DXT5 0x08bb13ac; enum DEFAULT=100.
    This is not a pixel tint: swap each RGB565 endpoint's five-bit R/B fields,
    preserve G and all eight alpha bytes, and preserve endpoint ordering with
    the original selector remapping. It is an involution on valid blocks.
    No original machine code is executed by this reconstruction.
    """
    block, offset = (8, 0) if fmt == 14 else (16, 8)
    if len(data) % block:
        raise ValueError("incomplete original DXT block")
    out = bytearray(data)
    for base in range(0, len(out), block):
        p = base + offset
        a, b, selectors = struct.unpack_from("<HHI", out, p)
        old_le = b >= a
        x = ((a & 31) << 11) | (a & 0x07e0) | (a >> 11)
        y = ((b & 31) << 11) | (b & 0x07e0) | (b >> 11)
        if old_le != (y >= x):
            x, y = y, x
            mapped = 0
            for shift in range(0, 32, 2):
                index = (selectors >> shift) & 3
                # Original 0x08ba5450..5483: in three-colour order only
                # endpoints 0/1 swap; in four-colour order 2/3 swap too.
                index = (index & 2) | ((~index & 1) if not old_le else
                                         (~(index ^ (index >> 1)) & 1))
                mapped |= index << shift
            selectors = mapped
        struct.pack_into("<HHI", out, p, x, y, selectors)
    return bytes(out)


def to_pil_original_order(img_obj, data):
    """Decode one reviewed original image with explicit channel-order metadata.

    Supported authority is DEFAULT=100 or already-concrete OGL=107 only.
    Original RGBA8888/RGB888/luminance DEFAULT->OGL does not swap components;
    original DXT1/3/5 DEFAULT->OGL does. Other platforms/orders fail closed.
    A new recipe/profile must opt in; legacy to_pil and its callers do not.
    """
    order_field = img_obj[6]
    if order_field is None or order_field.i32 not in (100, 107):
        raise ValueError("unreviewed original igImage component order")
    fmt = img_obj[11].i32
    if fmt not in (0, 5, 7, 14, 15, 16):
        raise ValueError("unreviewed original igImage pixel format")
    w, h = img_obj[2].i32, img_obj[3].i32
    if w <= 0 or h <= 0:
        raise ValueError("invalid original igImage dimensions")
    if fmt in FOURCC:
        block = 8 if fmt == 14 else 16
        top = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block
        if len(data) < top:
            raise ValueError("truncated original igImage pixels")
        data = bytes(data[:top])
        if order_field.i32 == 100:
            data = _original_dxt_to_ogl(data, fmt)
    return to_pil(img_obj, data)


def to_pil(img_obj, data):
    w, h, fmt = img_obj[2].i32, img_obj[3].i32, img_obj[11].i32
    if fmt == 0:  # 8-bit luminance (the miniature course's roads, base_road_Fix)
        return Image.frombytes("L", (w, h), bytes(data[:w * h])).convert("RGBA")
    if fmt == 5:  # 24-bit RGB
        return Image.frombytes("RGB", (w, h), bytes(data[:w * h * 3])).convert("RGBA")
    if fmt == 7:  # 32-bit RGBA
        return Image.frombytes("RGBA", (w, h), bytes(data[:w * h * 4]))
    if fmt not in FOURCC:
        raise ValueError("unsupported igImage format %d" % fmt)
    block = 8 if fmt == 14 else 16
    top = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block
    hdr = struct.pack("<4s7I44x", b"DDS ", 124, 0x1007 | 0x80000, h, w, top, 0, 1)
    pf = struct.pack("<2I4s5I", 32, 0x4, FOURCC[fmt], 0, 0, 0, 0, 0)
    caps = struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    return Image.open(io.BytesIO(hdr + pf + caps + data[:top])).convert("RGBA")
