"""Reconstruct the pinned 3DX+ physics bootstrap image without running game code.

Only the user's ELF is input.  No APK, saved image, emulator, disassembler, or
third-party package is needed at conversion time.  This is deliberately NOT an
ELF loader or a general x86 interpreter: fixed, reviewed initializer instruction
shapes are decoded into data copies, scalar formulas, and affine field stores.
Unknown revisions/semantics fail closed.  The final whole-image digest is an
independent acceptance condition, not a source for output bytes.

Data provenance:
* PT_LOAD bytes plus zero-filled memory -> [IMAGE_BASE, IMAGE_END).
* .rel.plt order -> synthetic host-import slots (STUB_BASE + ordinal * 16).
* A1/A3 copies at 0x89c3ea4..0x89c3ec7, 0x897e4de, 0x897ee05.
* 66 C7 /0 word immediates at 0x897e1a0..0x897e1bb.
* atan2f/sqrtf arguments, MULSS scale and destinations at 0x89ad5f8..632;
  each float store/arithmetic rounds to IEEE binary32, CVTT truncates to zero.
* CLinx::LxPcb initializer 0x89ebee6..0x89ec185: static affine store records,
  repeated over the array bounds and stride encoded in its ADD/CMP operands.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import stat
import struct
from typing import Callable

SOURCE_SHA256 = '2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'
IMAGE_SHA256 = '5790b205045807181ab3931c9583b5652f7be9b8e7af8b9c1680c00325db0bd4'
IMAGE_BASE = 0x092F1B20
IMAGE_END = 0x0993A468
IMAGE_SIZE = IMAGE_END - IMAGE_BASE
STUB_BASE = 0x20000000
ALGORITHM = '3dxplus-static-physics-v1'
MAX_SOURCE_SIZE = 32 * 1024 * 1024
Cancel = Callable[[], bool]
Progress = Callable[[str, int, int], None]


class PhysicsImageError(ValueError):
    """Controlled conversion rejection, with a stable machine-readable code."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ConversionCancelled(PhysicsImageError):
    def __init__(self):
        super().__init__('cancelled', 'Physics image conversion cancelled')


def _check(cancel: Cancel | None) -> None:
    if cancel is not None and cancel():
        raise ConversionCancelled()


def _require(ok: bool, message: str, code: str = 'invalid_elf') -> None:
    if not ok:
        raise PhysicsImageError(code, message)


def _bounds(offset: int, size: int, total: int) -> None:
    _require(0 <= offset <= total and 0 <= size <= total - offset,
             'ELF range is outside its backing bytes')


def _power2(n: int) -> bool:
    return n > 0 and n & (n - 1) == 0


@dataclass(frozen=True)
class Segment:
    offset: int
    address: int
    file_size: int
    memory_size: int
    flags: int


@dataclass(frozen=True)
class Section:
    name: str
    kind: int
    flags: int
    address: int
    offset: int
    size: int
    link: int
    info: int
    alignment: int
    entry_size: int


class Elf32:
    """Bounded ELF32 little-endian i386 reader, also usable with synthetic ELF."""
    def __init__(self, data: bytes, cancel: Cancel | None = None):
        _check(cancel)
        _require(isinstance(data, bytes), 'ELF input must be immutable bytes')
        _require(52 <= len(data) <= MAX_SOURCE_SIZE, 'Invalid ELF input length')
        h = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
        ident, typ, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shstr = h
        _require(ident[:7] == b'\x7fELF\x01\x01\x01' and ident[7:] == bytes(9),
                 'Only System V little-endian ELF32 is supported')
        _require((typ, machine, version, flags, ehsize, phsize, shsize) == (2, 3, 1, 0, 52, 32, 40),
                 'Unsupported ELF header or architecture')
        _require(0 < phnum <= 128 and 0 < shnum <= 512 and 0 < shstr < shnum,
                 'Missing, extended, or excessive ELF header tables')
        _require(phoff >= ehsize and shoff >= ehsize, 'Invalid ELF table offsets')
        _bounds(phoff, phnum * phsize, len(data))
        _bounds(shoff, shnum * shsize, len(data))
        _require(phoff + phnum * phsize <= shoff or shoff + shnum * shsize <= phoff,
                 'Overlapping ELF header tables')
        self.data = data
        segments = []
        for i in range(phnum):
            _check(cancel)
            kind, offset, va, _pa, fs, ms, permissions, alignment = struct.unpack_from('<8I', data, phoff + i * phsize)
            _require(fs <= ms and va + ms <= 2**32, 'Invalid ELF program range')
            _bounds(offset, fs, len(data))
            _require(alignment in (0, 1) or (_power2(alignment) and va % alignment == offset % alignment),
                     'Invalid ELF program alignment')
            if kind == 1:
                _require(ms > 0 and ms <= MAX_SOURCE_SIZE and permissions & ~7 == 0,
                         'Invalid PT_LOAD size or permissions')
                segments.append(Segment(offset, va, fs, ms, permissions))
        _require(bool(segments), 'ELF has no PT_LOAD segments')
        segments.sort(key=lambda seg: seg.address)
        for a, b in zip(segments, segments[1:]):
            _require(a.address + a.memory_size <= b.address, 'Overlapping PT_LOAD virtual ranges')
        ranges = sorted((s.offset, s.offset + s.file_size) for s in segments if s.file_size)
        for a, b in zip(ranges, ranges[1:]):
            _require(a[1] <= b[0], 'Overlapping PT_LOAD file ranges')
        self.segments = tuple(segments)
        _require(any(s.flags & 1 and s.address <= entry < s.address + s.file_size for s in segments),
                 'ELF entry is not in executable file bytes')
        raw_sections = [struct.unpack_from('<10I', data, shoff + i * shsize) for i in range(shnum)]
        _require(raw_sections[0] == (0,) * 10, 'Invalid null section')
        string_header = raw_sections[shstr]
        _require(string_header[1] == 3, 'Section name table is not STRTAB')
        _bounds(string_header[4], string_header[5], len(data))
        strings = data[string_header[4]:string_header[4] + string_header[5]]
        _require(strings[:1] == b'\0', 'Invalid section name string table')
        sections = []
        by_name = {}
        for i, row in enumerate(raw_sections):
            _check(cancel)
            name_offset, kind, secflags, va, offset, size, link, info, alignment, entsize = row
            _require(name_offset < len(strings), 'Section name offset out of bounds')
            terminator = strings.find(b'\0', name_offset)
            _require(terminator >= name_offset, 'Unterminated section name')
            try:
                name = strings[name_offset:terminator].decode('ascii')
            except UnicodeDecodeError as exc:
                raise PhysicsImageError('invalid_elf', 'Non-ASCII section name') from exc
            _require(link < shnum and (alignment in (0, 1) or _power2(alignment)),
                     'Invalid section link or alignment')
            _require(va + size <= 2**32 and size <= MAX_SOURCE_SIZE,
                     'Invalid ELF section range')
            if kind != 8:
                _bounds(offset, size, len(data))
            if secflags & 2 and size:
                seg = self._segment(va, size, file_backed=kind != 8)
                if kind != 8:
                    _require(offset == seg.offset + va - seg.address, 'Section/PT_LOAD mapping mismatch')
            _require(not name or name not in by_name, 'Duplicate ELF section name')
            sec = Section(name, kind, secflags, va, offset, size, link, info, alignment, entsize)
            sections.append(sec)
            if name:
                by_name[name] = sec
        self.sections = tuple(sections)
        self.by_name = by_name

    def _segment(self, address: int, size: int, *, file_backed: bool = True) -> Segment:
        _require(0 <= address <= 2**32 and size >= 0 and address + size <= 2**32,
                 'Invalid virtual byte range')
        matches = [s for s in self.segments if s.address <= address and
                   address + size <= s.address + (s.file_size if file_backed else s.memory_size)]
        _require(len(matches) == 1, 'Virtual range is unmapped, ambiguous, or not file-backed')
        return matches[0]

    def read(self, address: int, size: int) -> bytes:
        seg = self._segment(address, size)
        offset = seg.offset + address - seg.address
        return self.data[offset:offset + size]

    def code(self, address: int, size: int) -> bytes:
        _require(self._segment(address, size).flags & 1 != 0, 'Initializer is not executable data')
        return self.read(address, size)

    def section(self, name: str, kind: int) -> Section:
        sec = self.by_name.get(name)
        _require(sec is not None and sec.kind == kind, 'Missing or invalid required section: ' + name)
        return sec

    def image(self, base: int, end: int, cancel: Cancel | None = None) -> bytearray:
        _require(0 <= base < end <= 2**32 and end - base <= 16 * 1024 * 1024,
                 'Invalid image projection range')
        image = bytearray(end - base)
        for seg in self.segments:
            _check(cancel)
            lo, hi = max(base, seg.address), min(end, seg.address + seg.file_size)
            if lo < hi:
                image[lo - base:hi - base] = self.read(lo, hi - lo)
        return image


def _shape(elf: Elf32, address: int, prefix: bytes) -> None:
    _require(elf.code(address, len(prefix)) == prefix,
             'Unsupported initializer instruction shape at ' + hex(address), 'unsupported_initialization')


def _u32(data: bytes) -> int:
    return struct.unpack('<I', data)[0]


def _operand32(elf: Elf32, address: int, prefix: bytes) -> int:
    _shape(elf, address, prefix)
    return _u32(elf.code(address + len(prefix), 4))


def _relative(elf: Elf32, address: int, opcode: int) -> int:
    _shape(elf, address, bytes([opcode]))
    width = 1 if opcode == 0xEB else 4
    offset = int.from_bytes(elf.code(address + 1, width), 'little', signed=True)
    return address + 1 + width + offset


def _constructors(elf: Elf32, cancel: Cancel | None) -> set[int]:
    sec = elf.section('.ctors', 1)
    _require(sec.size >= 8 and sec.size % 4 == 0, 'Invalid constructor table')
    values = struct.unpack('<' + 'I' * (sec.size // 4), elf.read(sec.address, sec.size))
    _require(values[0] == 0xFFFFFFFF and values[-1] == 0, 'Invalid constructor sentinels')
    for va in values[1:-1]:
        _check(cancel)
        elf.code(va, 1)
    return set(values[1:-1])


def _ctor(elf: Elf32, ctors: set[int], wrapper: int, body: int) -> None:
    _require(wrapper in ctors, 'Required initializer is absent from .ctors', 'unsupported_initialization')
    _shape(elf, wrapper, b'\x55\xba')  # push ebp; mov edx, priority
    _require(_u32(elf.code(wrapper + 2, 4)) == 0xFFFF, 'Unexpected initialization priority', 'unsupported_initialization')
    _require(_operand32(elf, wrapper + 6, b'\xb8') == 1, 'Unexpected initialization mode', 'unsupported_initialization')
    _shape(elf, wrapper + 11, b'\x89\xe5\xc9')
    opcode = elf.code(wrapper + 14, 1)[0]
    _require(opcode in (0xEB, 0xE9), 'Unexpected initializer wrapper jump', 'unsupported_initialization')
    _require(_relative(elf, wrapper + 14, opcode) == body, 'Initializer wrapper target mismatch', 'unsupported_initialization')


def _store(image: bytearray, address: int, data: bytes) -> None:
    _require(IMAGE_BASE <= address and address + len(data) <= IMAGE_END,
             'Initializer store is outside physics image', 'unsupported_initialization')
    image[address - IMAGE_BASE:address - IMAGE_BASE + len(data)] = data


def _imports(elf: Elf32, image: bytearray, cancel: Cancel | None) -> int:
    rel = elf.section('.rel.plt', 9)
    dyn = elf.section('.dynsym', 11)
    got = elf.section('.got', 1)
    _require(elf.sections[rel.link] == dyn and rel.info < len(elf.sections) and
             elf.sections[rel.info].name == '.plt' and elf.sections[dyn.link].kind == 3 and
             got.flags & 3 == 3 and rel.entry_size == 8 and rel.size % 8 == 0 and
             dyn.entry_size == 16 and dyn.size % 16 == 0 and rel.size // 8 == 484,
             'Unsupported PLT relocation metadata', 'unsupported_initialization')
    targets = set()
    for index in range(rel.size // 8):
        _check(cancel)
        target, info = struct.unpack('<II', elf.read(rel.address + index * 8, 8))
        _require(info & 255 == 7 and 0 < info >> 8 < dyn.size // 16,
                 'Unsupported PLT relocation kind or symbol', 'unsupported_initialization')
        _require(got.address <= target <= got.address + got.size - 4 and target % 4 == 0 and target not in targets,
                 'Invalid or duplicate import slot', 'unsupported_initialization')
        targets.add(target)
        _store(image, target, struct.pack('<I', STUB_BASE + index * 16))
    return len(targets)


def _copy(elf: Elf32, image: bytearray, load: int, store: int, source: int, destination: int) -> None:
    src = _operand32(elf, load, b'\xa1')
    dst = _operand32(elf, store, b'\xa3')
    _require(src == source and dst == destination and store == load + 5,
             'Unsupported data-copy operands', 'unsupported_initialization')
    _store(image, dst, elf.read(src, 4))


def _f32(value: float) -> float:
    return struct.unpack('<f', struct.pack('<f', value))[0]


def _float_initializers(elf: Elf32, image: bytearray) -> None:
    xbits = _operand32(elf, 0x89AD5F8, b'\xc7\x44\x24\x04')
    ybits = _operand32(elf, 0x89AD600, b'\xc7\x04\x24')
    radicand_bits = _operand32(elf, 0x89AD61C, b'\xc7\x04\x24')
    _require(_relative(elf, 0x89AD607, 0xE8) == 0x84223D8 and
             _relative(elf, 0x89AD62D, 0xE8) == 0x8422168,
             'Unsupported scalar initialization function', 'unsupported_initialization')
    _shape(elf, 0x89AD60C, b'\xd9\x5d\xfc\xf3\x0f\x10\x45\xfc')
    scale_address = _operand32(elf, 0x89AD614, b'\xf3\x0f\x59\x05')
    _require(scale_address == 0x9433E04, 'Unsupported angle scaling operand', 'unsupported_initialization')
    _shape(elf, 0x89AD623, b'\xf3\x0f\x2c\xc0')
    angle_dst = _operand32(elf, 0x89AD627, b'\x66\xa3')
    root_dst = _operand32(elf, 0x89AD632, b'\xd9\x1d')
    _require((angle_dst, root_dst) == (0x9803094, 0x9803090),
             'Unsupported scalar initialization destinations', 'unsupported_initialization')
    x, y, radicand = [struct.unpack('<f', struct.pack('<I', bits))[0] for bits in (xbits, ybits, radicand_bits)]
    scale = struct.unpack('<f', elf.read(scale_address, 4))[0]
    _require(all(math.isfinite(v) for v in (x, y, radicand, scale)) and radicand >= 0,
             'Invalid scalar initializer data', 'unsupported_initialization')
    angle = _f32(_f32(math.atan2(y, x)) * scale)
    _require(math.isfinite(angle) and -2**31 <= angle < 2**31,
             'Angle conversion is out of range', 'unsupported_initialization')
    _store(image, angle_dst, struct.pack('<H', math.trunc(angle) & 0xFFFF))
    _store(image, root_dst, struct.pack('<f', math.sqrt(radicand)))


def _linx_stores(elf: Elf32, cancel: Cancel | None) -> tuple[int, int, int, list[tuple[int, bytes]]]:
    """Decode one straight-line affine block, NOT a CPU execution loop.

    Register values are object-relative integer offsets, never game data or CPU
    state.  EBP accesses name compiler scratch slots.  Branches/calls/loads from
    game memory and every unlisted opcode are forbidden.  The only loop is
    reconstructed algebraically from the reviewed terminal ADD/CMP/JNE shape.
    """
    base = _operand32(elf, 0x89EBEE6, b'\xbe')
    _require(base == 0x98033E0, 'Unexpected Linx array base', 'unsupported_initialization')
    regs = {6: 0}  # ESI is the symbolic first-object base.
    locals_: dict[int, int] = {}
    stores = []
    pc, stop = 0x89EBEF0, 0x89EC17F
    stride = end = None
    instruction_count = 0
    while pc < stop:
        _check(cancel)
        instruction_count += 1
        _require(instruction_count <= 160, 'Excessive initializer block', 'unsupported_initialization')
        raw = elf.code(pc, min(12, stop - pc))
        prefix = 1 if raw[0] == 0x66 else 0
        _require(len(raw) >= prefix + 2, 'Truncated affine instruction', 'unsupported_initialization')
        opcode, modrm = raw[prefix], raw[prefix + 1]
        if prefix == 0 and opcode == 0x81 and modrm in (0xC6, 0xFE):
            _require(len(raw) >= 6, 'Truncated Linx array bounds', 'unsupported_initialization')
            immediate = _u32(raw[2:6])
            if modrm == 0xC6:
                _require(pc == 0x89EC157 and stride is None and regs[6] == 0,
                         'Unexpected array stride location', 'unsupported_initialization')
                stride = immediate
                regs[6] += stride
            else:
                _require(pc == 0x89EC15D and end is None, 'Unexpected array bound location', 'unsupported_initialization')
                end = immediate
            pc += 6
            continue
        mod, reg, rm = modrm >> 6, (modrm >> 3) & 7, modrm & 7
        _require(mod in (1, 2) and rm != 4, 'Unsupported affine addressing', 'unsupported_initialization')
        disp_size = 1 if mod == 1 else 4
        n = prefix + 2 + disp_size
        _require(len(raw) >= n, 'Truncated affine displacement', 'unsupported_initialization')
        displacement = int.from_bytes(raw[prefix + 2:n], 'little', signed=True)
        if opcode == 0x8D and not prefix:
            _require(rm in regs and rm != 5, 'Unknown LEA basis', 'unsupported_initialization')
            regs[reg] = regs[rm] + displacement
        elif opcode == 0x89 and not prefix:
            _require(rm == 5 and reg in regs and displacement in (-20, -16),
                     'Unsupported affine scratch assignment', 'unsupported_initialization')
            locals_[displacement] = regs[reg]
        elif opcode == 0x8B and not prefix:
            _require(rm == 5 and displacement in locals_, 'Unknown affine scratch load', 'unsupported_initialization')
            regs[reg] = locals_[displacement]
        elif opcode == 0xC7:
            width = 2 if prefix else 4
            _require(reg == 0 and rm in regs and rm != 5 and len(raw) >= n + width,
                     'Unsupported affine initializer store', 'unsupported_initialization')
            stores.append((regs[rm] + displacement, raw[n:n + width]))
            n += width
        else:
            raise PhysicsImageError('unsupported_initialization', 'Unknown affine initializer opcode at ' + hex(pc))
        pc += n
    _require(pc == stop and stride is not None and end is not None and stride > 0 and
             end > base and (end - base) % stride == 0 and (end - base) // stride == 3,
             'Invalid Linx array extent', 'unsupported_initialization')
    _shape(elf, stop, b'\x0f\x85')
    branch = stop + 6 + int.from_bytes(elf.code(stop + 2, 4), 'little', signed=True)
    _require(branch == 0x89EBEF0, 'Invalid Linx loop backedge', 'unsupported_initialization')
    _require(_relative(elf, stop + 6, 0xE9) == 0x89EBECC, 'Invalid Linx initializer exit', 'unsupported_initialization')
    _require(len(stores) == 82 and sum(int.from_bytes(v, 'little') != 0 for _, v in stores) == 7,
             'Unexpected affine field coverage', 'unsupported_initialization')
    for offset, value in stores:
        _require(0 <= offset and offset + len(value) <= stride, 'Affine store escapes object', 'unsupported_initialization')
    return base, end, stride, stores


def _build_image(elf: Elf32, cancel: Cancel | None = None,
                 progress: Progress | None = None) -> tuple[bytearray, dict[str, int]]:
    def step(name: str, index: int) -> None:
        _check(cancel)
        if progress:
            progress(name, index, 6)
    step('project_load_segments', 0)
    image = elf.image(IMAGE_BASE, IMAGE_END, cancel)
    ctors = _constructors(elf, cancel)
    step('import_slots', 1)
    slots = _imports(elf, image, cancel)
    step('static_data_copies', 2)
    _ctor(elf, ctors, 0x89C3EE0, 0x89C3E70)
    for i, dst in enumerate((0x977907C, 0x977906C, 0x977905C, 0x977904C)):
        _check(cancel)
        _copy(elf, image, 0x89C3EA4 + i * 10, 0x89C3EA9 + i * 10, 0x9778EE8 + i * 4, dst)
    for wrapper, body, load, dst in ((0x897E500, 0x897E4AC, 0x897E4DE, 0x98027E8),
                                      (0x897EE20, 0x897EDD4, 0x897EE05, 0x98027F8)):
        _ctor(elf, ctors, wrapper, body)
        _copy(elf, image, load, load + 5, 0x943DA44, dst)
    step('angle_constants', 3)
    _ctor(elf, ctors, 0x897E1C8, 0x897E190)
    for index in range(4):
        pc = 0x897E1A0 + index * 9
        dest = _operand32(elf, pc, b'\x66\xc7\x05')
        _require(dest == 0x98027E6 - index * 2, 'Unexpected word initialization destination', 'unsupported_initialization')
        _store(image, dest, elf.code(pc + 7, 2))
    step('scalar_initializers', 4)
    _ctor(elf, ctors, 0x89AD63C, 0x89AD5E0)
    _float_initializers(elf, image)
    step('linx_field_initializers', 5)
    _ctor(elf, ctors, 0x89EC1B4, 0x89EBEA8)
    base, end, stride, stores = _linx_stores(elf, cancel)
    for object_base in range(base, end, stride):
        for offset, value in stores:
            _check(cancel)
            _store(image, object_base + offset, value)
    step('verify_image', 6)
    return image, {'import_slots': slots, 'data_copies': 6, 'word_constants': 4,
                   'scalar_initializers': 2, 'linx_objects': (end - base) // stride,
                   'linx_field_stores_per_object': len(stores)}


@contextmanager
def _parent_fd(path: os.PathLike[str] | str):
    """Open each existing directory without following symlinks, retaining its fd."""
    raw = os.fspath(path)
    _require(isinstance(raw, str) and '\x00' not in raw and '..' not in Path(raw).parts,
             'Invalid file path or parent traversal', 'invalid_path')
    p = Path(os.path.abspath(raw))
    _require(p.name not in ('', '.', '..'), 'Invalid file path', 'invalid_path')
    _require(hasattr(os, 'O_NOFOLLOW') and hasattr(os, 'O_DIRECTORY'),
             'Platform cannot enforce no-symlink paths', 'unsupported_platform')
    read_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    walk_flags = read_flags | getattr(os, 'O_PATH', 0)
    fd = os.open(p.anchor, walk_flags)
    try:
        for component in p.parent.parts[1:]:
            next_fd = os.open(component, walk_flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        # Android allows path traversal through system directories without read
        # access. Only the final parent needs a readable descriptor for scans.
        if walk_flags != read_flags:
            next_fd = os.open('.', read_flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd, p.name
    finally:
        os.close(fd)


def _read_source(fd: int, cancel: Cancel | None, progress: Progress | None,
                 *, retain: bool) -> tuple[bytes, str]:
    before = os.fstat(fd)
    _require(stat.S_ISREG(before.st_mode) and 52 <= before.st_size <= MAX_SOURCE_SIZE,
             'Source must be a bounded regular file', 'invalid_source')
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    chunks = []
    total = 0
    while total < before.st_size:
        _check(cancel)
        chunk = os.read(fd, min(1024 * 1024, before.st_size - total))
        _require(bool(chunk), 'Source changed or became unreadable', 'source_changed')
        digest.update(chunk)
        if retain:
            chunks.append(chunk)
        total += len(chunk)
        if progress:
            progress('read_source' if retain else 'recheck_source', total, before.st_size)
    _require(not os.read(fd, 1), 'Source grew while being read', 'source_changed')
    after = os.fstat(fd)
    _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
             (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
             'Source metadata changed while being read', 'source_changed')
    return b''.join(chunks), digest.hexdigest()


def convert_physics_image(main_path: os.PathLike[str] | str,
                          output_path: os.PathLike[str] | str, *,
                          cancel: Cancel | None = None,
                          progress: Progress | None = None) -> dict:
    """Validate, derive, hash-check, then exclusively create a new phys.img.

    The destination parent must already exist.  Every directory component and
    both file endpoints are opened without following symlinks.  Existing output
    files are never overwritten.  On an I/O/cancellation failure after exclusive
    creation the caller-owned job directory retains the new partial artifact;
    this function never unlinks a path (avoids replacement races).  Callbacks
    contain phase/counts only, never game bytes.  There is no golden-input or
    source-pin override in this public API.
    """
    _check(cancel)
    try:
        with _parent_fd(output_path) as (out_dir, out_name):
            try:
                os.stat(out_name, dir_fd=out_dir, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise PhysicsImageError('output_exists', 'Output path already exists')
            with _parent_fd(main_path) as (source_dir, source_name):
                fd = os.open(source_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_dir)
                try:
                    data, source_hash = _read_source(fd, cancel, progress, retain=True)
                    elf = Elf32(data, cancel)
                    _require(source_hash == SOURCE_SHA256, 'Unsupported main SHA-256', 'unsupported_source')
                    image, steps = _build_image(elf, cancel, progress)
                    image_hash = hashlib.sha256(image).hexdigest()
                    _require(len(image) == IMAGE_SIZE and image_hash == IMAGE_SHA256,
                             'Static reconstruction did not match the reviewed image digest', 'image_mismatch')
                    _, after_hash = _read_source(fd, cancel, progress, retain=False)
                    _require(after_hash == source_hash, 'Source changed during conversion', 'source_changed')
                    held = os.fstat(fd)
                    named = os.stat(source_name, dir_fd=source_dir, follow_symlinks=False)
                    _require(stat.S_ISREG(named.st_mode) and (held.st_dev, held.st_ino) ==
                             (named.st_dev, named.st_ino), 'Source path was replaced during conversion', 'source_changed')
                finally:
                    os.close(fd)
            _check(cancel)
            output_fd = os.open(out_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=out_dir)
            try:
                view = memoryview(image)
                offset = 0
                while offset < len(view):
                    _check(cancel)
                    n = os.write(output_fd, view[offset:offset + 1024 * 1024])
                    _require(n > 0, 'Output write made no progress', 'io_error')
                    offset += n
                    if progress:
                        progress('write_image', offset, IMAGE_SIZE)
                os.fsync(output_fd)
            finally:
                os.close(output_fd)
        return {'source_sha256': source_hash, 'source_sha256_after': after_hash,
                'image_sha256': image_hash, 'bytes': IMAGE_SIZE,
                'algorithm': ALGORITHM, 'steps': steps}
    except FileExistsError as exc:
        raise PhysicsImageError('output_exists', 'Output path was created concurrently') from exc
    except OSError as exc:
        raise PhysicsImageError('io_error', 'Physics image file operation failed: ' + str(exc)) from exc
