"""Synthetic local sidecar/format/I/O tests, not native readiness or cloud authority.

Only ghost_store.c/.h + the existing execution-free ghost_format parser are built.
No game input/assets/engine, save migration, device, network or REA are used.
"""
import ctypes
import hashlib
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

SOURCE = Path(__file__).resolve().parents[1]
HEADER = 184
MAX_TRAIL = 28 + 4 * 512 + 48 * 8192
BASENAME = "ghost_local_v1"
PHYSICS = hashlib.sha256(b"synthetic current physics only").hexdigest().encode("ascii")
OTHER_PHYSICS = hashlib.sha256(b"synthetic incompatible physics").hexdigest().encode("ascii")
OK, NOT_FOUND, ARGUMENT, IO, MEMORY, VERSION, LENGTH, CHECKSUM, PHYSICS_ERROR, METADATA, TRAIL, UNSAFE, UNSYNCED = range(13)
STALE = 13


class CarSpec(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint), ("gears", ctypes.c_int),
                ("tyres", ctypes.c_float * 6), ("spokes", ctypes.c_int),
                ("power", ctypes.c_int), ("handling", ctypes.c_int)]


class Record(ctypes.Structure):
    _fields_ = [("ramp", ctypes.c_uint32), ("route", ctypes.c_uint32),
                ("race_field", ctypes.c_uint32 * 6), ("owner", CarSpec),
                ("physics_sha256", ctypes.c_char * 65), ("recorded_at", ctypes.c_uint64),
                ("trail", ctypes.POINTER(ctypes.c_ubyte)), ("trail_bytes", ctypes.c_size_t)]


class Crown(ctypes.Structure):
    _fields_ = [("race", Record)] + [
        (field, ctypes.c_uint32)
        for field in ("raw_model", "raw_ramp", "custom_color", "aero", "mirror", "wing",
                      "bonnet", "wheel", "neon", "vinyl", "title", "class_id")
    ] + [("name", ctypes.c_uint16 * 5), ("revision", ctypes.c_uint64)]


AreaAllowed = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_uint32, ctypes.c_void_p)


class Policy(ctypes.Structure):
    _fields_ = [("stage", ctypes.c_uint32), ("area_allowed", AreaAllowed),
                ("context", ctypes.c_void_p), ("max_samples", ctypes.c_uint32),
                 ("area_sequence_allowed", ctypes.c_void_p), ("max_ticks", ctypes.c_uint32)]


def bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def native_trail(*, nan_sample=False, sample_area=10, areas=(10, 11), stage=363, count=3):
    samples = []
    for index in range(count):
        sample = bytearray(48)
        for offset, value in ((0, float(index * 100)), (4, 1.0), (8, 2.0), (12, 3.0),
                              (32, 0.25), (36, 0.5), (40, 0.75)):
            struct.pack_into("<f", sample, offset, value)
        if nan_sample and index == 1:
            struct.pack_into("<I", sample, 4, 0x7FC00000)
        struct.pack_into("<II", sample, 24, 4, sample_area)
        samples.append(sample)
    transposed = bytes(samples[index][column] for column in range(48) for index in range(count))
    delta = bytes((value - (transposed[i - 1] if i else 0)) & 255 for i, value in enumerate(transposed))
    prefix = struct.pack("<II", 0x070426A, len(areas)) + struct.pack("<" + "I" * len(areas), *areas)
    data = prefix + struct.pack("<IIII", stage, 12345, 1, count) + delta
    return data + struct.pack("<I", sum(data) & 0xFFFFFFFF)


def make_record(data=None, *, stamp=1700000000):
    data = native_trail() if data is None else data
    array = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    record = Record()
    record.ramp, record.route = 1, 0
    record.race_field[:] = (363, 0, 10, bits(0.0), bits(100000.0), 1)
    record.owner.type, record.owner.gears = 0x12345678, 6
    record.owner.tyres[:] = (-800.0, 300.0, 1200.0, -800.0, 300.0, -1200.0)
    record.owner.spokes, record.owner.power, record.owner.handling = 5, 17, 17
    record.physics_sha256 = PHYSICS
    record.recorded_at = stamp
    record.trail, record.trail_bytes = array, len(data)
    return record, array


def fix_crc(data):
    result = bytearray(data)
    struct.pack_into("<I", result, 24, 0)
    struct.pack_into("<I", result, 24, zlib.crc32(result) & 0xFFFFFFFF)
    return bytes(result)


HELPER = r'''
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
#include "ghost_store.h"
static int fail_mode, write_count, sync_count;
void ghost_test_failure(int mode) { fail_mode = mode; write_count = sync_count = 0; }
size_t ghost_test_record_size(void) { return sizeof(ghost_store_record); }
size_t ghost_test_crown_size(void) { return sizeof(ghost_crown_record); }
size_t ghost_test_car_size(void) { return sizeof(car_spec); }
size_t ghost_test_policy_size(void) { return sizeof(ghost_format_policy); }
void *ghost_test_malloc(size_t bytes) {
  if (fail_mode == 5) return NULL;
  return malloc(bytes);
}
ssize_t ghost_test_write(int fd, const void *data, size_t bytes) {
  if (fail_mode == 1) {
    if (!write_count++) return write(fd, data, bytes / 2);
    errno = ENOSPC; return -1;
  }
  if (fail_mode == 6 && !write_count++) { errno = EINTR; return -1; }
  return write(fd, data, bytes);
}
int ghost_test_fsync(int fd) {
  struct stat st;
  if (fstat(fd, &st)) return -1;
  if ((fail_mode == 3 && !S_ISDIR(st.st_mode)) ||
      (fail_mode == 4 && S_ISDIR(st.st_mode))) { errno = EIO; return -1; }
  if (fail_mode == 7 && !sync_count++) { errno = EINTR; return -1; }
  return fsync(fd);
}
int ghost_test_renameat(int oldfd, const char *oldname, int newfd, const char *newname) {
  if (fail_mode == 2) { errno = EACCES; return -1; }
  return renameat(oldfd, oldname, newfd, newname);
}
'''


class GhostStoreHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix="ghost-store-build-", dir=os.environ.get("TMPDIR"))
        cls.addClassCleanup(cls.build.cleanup)
        build = Path(cls.build.name)
        helper = build / "synthetic_fault_adapter.c"
        helper.write_text(HELPER)
        compiler = shutil.which("cc") or shutil.which("clang")
        if compiler is None:
            raise RuntimeError("A host C compiler is required; no dependencies are installed")
        base = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O1", "-g", "-fPIC", "-I", str(SOURCE / "src")]
        obj = build / "ghost_store.o"
        subprocess.run(base + ["-Dwrite=ghost_test_write", "-Dfsync=ghost_test_fsync",
                               "-Drenameat=ghost_test_renameat", "-Dmalloc=ghost_test_malloc",
                               "-c", str(SOURCE / "src/ghost_store.c"), "-o", str(obj)], check=True,
                       capture_output=True, text=True)
        library = build / ("ghost_store_test.dylib" if sys.platform == "darwin" else "ghost_store_test.so")
        subprocess.run(base + (["-dynamiclib"] if sys.platform == "darwin" else ["-shared"]) +
                       [str(obj), str(SOURCE / "src/ghost_format.c"), str(helper), "-lz", "-lm", "-o", str(library)],
                       check=True, capture_output=True, text=True)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.ghost_store_save.argtypes = [ctypes.c_char_p, ctypes.POINTER(Record)]
        cls.lib.ghost_store_save.restype = ctypes.c_int
        cls.lib.ghost_store_load.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(Record)]
        cls.lib.ghost_store_load.restype = ctypes.c_int
        cls.lib.ghost_store_free.argtypes = [ctypes.POINTER(Record)]
        cls.lib.ghost_store_contains_map.argtypes = [ctypes.POINTER(Record), ctypes.c_uint32, ctypes.c_uint32]
        cls.lib.ghost_store_contains_map.restype = ctypes.c_int
        cls.lib.ghost_store_validate_native.argtypes = [ctypes.POINTER(Record), ctypes.POINTER(Policy)]
        cls.lib.ghost_store_validate_native.restype = ctypes.c_int
        cls.lib.ghost_crown_save.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.POINTER(Crown), ctypes.c_uint64]
        cls.lib.ghost_crown_save.restype = ctypes.c_int
        cls.lib.ghost_crown_load.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_char_p, ctypes.POINTER(Crown)]
        cls.lib.ghost_crown_load.restype = ctypes.c_int
        cls.lib.ghost_replay_save.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint,
                                                ctypes.POINTER(Crown), ctypes.c_uint64]
        cls.lib.ghost_replay_save.restype = ctypes.c_int
        cls.lib.ghost_replay_load.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint,
                                                ctypes.c_char_p, ctypes.POINTER(Crown)]
        cls.lib.ghost_replay_load.restype = ctypes.c_int
        cls.lib.ghost_crown_free.argtypes = [ctypes.POINTER(Crown)]
        cls.lib.ghost_profile_pack.argtypes = [ctypes.POINTER(Crown),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)), ctypes.POINTER(ctypes.c_size_t)]
        cls.lib.ghost_profile_pack.restype = ctypes.c_int
        cls.lib.ghost_profile_unpack.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_size_t,
            ctypes.c_char_p, ctypes.POINTER(Crown)]
        cls.lib.ghost_profile_unpack.restype = ctypes.c_int
        cls.lib.ghost_test_crown_size.restype = ctypes.c_size_t
        if cls.lib.ghost_test_crown_size() != ctypes.sizeof(Crown):
            raise AssertionError("Host ctypes/C crown ABI layout mismatch")
        cls.lib.ghost_store_error.argtypes = [ctypes.c_int]
        cls.lib.ghost_store_error.restype = ctypes.c_char_p
        cls.lib.ghost_test_failure.argtypes = [ctypes.c_int]
        cls.lib.ghost_test_record_size.restype = ctypes.c_size_t
        cls.lib.ghost_test_car_size.restype = ctypes.c_size_t
        cls.lib.ghost_test_policy_size.restype = ctypes.c_size_t
        if cls.lib.ghost_test_record_size() != ctypes.sizeof(Record) or cls.lib.ghost_test_car_size() != ctypes.sizeof(CarSpec) or cls.lib.ghost_test_policy_size() != ctypes.sizeof(Policy):
            raise AssertionError("Host ctypes/C ABI layout mismatch")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ghost-store-case-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.path = self.directory / BASENAME
        self.sentinels = {name: ("synthetic untouched legacy " + name).encode()
                          for name in ("garage", "records", "option", "key")}
        for name, data in self.sentinels.items():
            (self.directory / name).write_bytes(data)
        self.lib.ghost_test_failure(0)
        self.record, self.buffer = make_record()

    def tearDown(self):
        self.lib.ghost_test_failure(0)
        for name, data in self.sentinels.items():
            self.assertEqual((self.directory / name).read_bytes(), data, name)

    def save(self, record=None, directory=None):
        return self.lib.ghost_store_save(os.fsencode(directory or self.directory), ctypes.byref(record or self.record))

    def load(self, physics=PHYSICS, directory=None):
        record = Record()
        result = self.lib.ghost_store_load(os.fsencode(directory or self.directory), physics, ctypes.byref(record))
        self.addCleanup(self.lib.ghost_store_free, ctypes.byref(record))
        return result, record

    def saved_bytes(self):
        self.assertEqual(self.save(), OK)
        return self.path.read_bytes()

    def assert_no_temps(self):
        self.assertEqual(list(self.directory.glob(BASENAME + ".tmp.*")), [])

    @unittest.skipUnless(sys.platform == "darwin" or sys.platform.startswith("linux"),
                         "requires search-only directory descriptors")
    def test_crown_saves_and_replaces_under_search_only_parent(self):
        parent = self.directory / "app-data-parent"
        store = parent / "app-records"
        store.mkdir(parents=True, mode=0o700)
        self.addCleanup(parent.chmod, 0o700)
        parent.chmod(0o111)
        if os.access(parent, os.R_OK):
            self.skipTest("requires a user subject to directory read permissions")
        root = os.fsencode(store) + b"/"
        winner = Crown(race=self.record, raw_model=92, raw_ramp=15, wheel=143,
                       name=(0xff21, 0, 0, 0, 0))
        loaded = Crown()
        self.addCleanup(self.lib.ghost_crown_free, ctypes.byref(loaded))
        self.assertEqual(self.lib.ghost_crown_save(root, 6, ctypes.byref(winner), 0), OK)
        self.assertEqual(self.lib.ghost_crown_load(root, 6, PHYSICS, ctypes.byref(loaded)), OK)
        revision = loaded.revision
        self.lib.ghost_crown_free(ctypes.byref(loaded))
        winner.name[0] = 0xff22
        self.assertEqual(self.lib.ghost_crown_save(root, 6, ctypes.byref(winner), revision), OK)
        self.assertEqual(self.lib.ghost_crown_load(root, 6, PHYSICS, ctypes.byref(loaded)), OK)
        self.assertEqual(list(loaded.name), list(winner.name))

    def test_crown_round_trip_and_revision_only_replace_the_selected_area(self):
        practice = self.saved_bytes()
        root = os.fsencode(self.directory)
        winner = Crown(race=self.record, raw_model=92, raw_ramp=15, custom_color=9, aero=3,
                       wheel=143, name=(0xff21, 0xff32, 0xff38, 0, 0))
        self.assertEqual(self.lib.ghost_crown_save(root, 6, ctypes.byref(winner), 0), OK)
        self.assertEqual(self.lib.ghost_crown_save(root, 5, ctypes.byref(winner), 0), OK)
        other = (self.directory / "ghost_crown_5").read_bytes()
        selected = self.directory / "ghost_crown_6"
        first = selected.read_bytes()
        loaded = Crown()
        self.addCleanup(self.lib.ghost_crown_free, ctypes.byref(loaded))
        self.assertEqual(self.lib.ghost_crown_load(root, 6, PHYSICS, ctypes.byref(loaded)), OK)
        revision = loaded.revision
        self.assertGreater(revision, 0)
        self.assertEqual(list(loaded.name), list(winner.name))
        self.assertEqual(loaded.raw_model, winner.raw_model)
        self.assertEqual(loaded.custom_color, winner.custom_color)
        self.assertEqual(ctypes.string_at(loaded.race.trail, loaded.race.trail_bytes), bytes(self.buffer))
        self.lib.ghost_crown_free(ctypes.byref(loaded))
        self.assertEqual(self.lib.ghost_crown_load(root, 7, PHYSICS, ctypes.byref(loaded)), NOT_FOUND)
        winner.name[0] = 0xff22
        self.assertEqual(self.lib.ghost_crown_save(root, 6, ctypes.byref(winner), 0), STALE)
        self.lib.ghost_test_failure(2)
        self.assertEqual(self.lib.ghost_crown_save(root, 6, ctypes.byref(winner), revision), IO)
        self.assertEqual(selected.read_bytes(), first)
        self.assertFalse(list(self.directory.glob("ghost_crown_*.tmp.*")))
        self.lib.ghost_test_failure(0)
        self.assertEqual(self.lib.ghost_crown_save(root, 6, ctypes.byref(winner), revision), OK)
        self.assertEqual(self.lib.ghost_crown_load(root, 6, PHYSICS, ctypes.byref(loaded)), OK)
        self.assertNotEqual(loaded.revision, revision)
        self.assertEqual(list(loaded.name), list(winner.name))
        self.assertEqual(self.lib.ghost_crown_save(root, 6, ctypes.byref(winner), revision), STALE)
        self.assertEqual(self.path.read_bytes(), practice)
        self.assertEqual((self.directory / "ghost_crown_5").read_bytes(), other)

    def test_cloud_profile_roundtrip_uses_exact_store_bytes_and_checks_physics(self):
        profile = Crown(race=self.record, raw_model=92, raw_ramp=15, wheel=143,
                        name=(0xff21, 0xff32, 0xff38, 0, 0))
        body = ctypes.POINTER(ctypes.c_ubyte)()
        length = ctypes.c_size_t()
        self.assertEqual(self.lib.ghost_profile_pack(ctypes.byref(profile), ctypes.byref(body), ctypes.byref(length)), OK)
        libc = ctypes.CDLL(None)
        libc.free.argtypes = [ctypes.c_void_p]
        self.addCleanup(libc.free, body)
        root = os.fsencode(self.directory)
        self.assertEqual(self.lib.ghost_crown_save(root, 6, ctypes.byref(profile), 0), OK)
        self.assertEqual(ctypes.string_at(body, length.value), (self.directory / "ghost_crown_6").read_bytes())
        replay = Crown()
        self.addCleanup(self.lib.ghost_crown_free, ctypes.byref(replay))
        self.assertEqual(self.lib.ghost_profile_unpack(body, length.value, OTHER_PHYSICS, ctypes.byref(replay)), PHYSICS_ERROR)
        self.assertEqual(self.lib.ghost_profile_unpack(body, length.value, PHYSICS, ctypes.byref(replay)), OK)
        self.assertEqual(list(replay.name), list(profile.name))
        self.assertEqual(ctypes.string_at(replay.race.trail, replay.race.trail_bytes), bytes(self.buffer))
        self.lib.ghost_crown_free(ctypes.byref(replay))
        body[length.value - 1] ^= 1
        self.assertEqual(self.lib.ghost_profile_unpack(body, length.value, PHYSICS, ctypes.byref(replay)), CHECKSUM)

    def test_missing_is_not_found_and_never_creates_or_migrates_legacy_saves(self):
        result, loaded = self.load()
        self.assertEqual(result, NOT_FOUND)
        self.assertFalse(loaded.trail)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.lib.ghost_store_contains_map(ctypes.byref(loaded), 1, 0), 0)
        self.assert_no_temps()

    def test_roundtrip_explicit_little_endian_wire_and_narrow_permissions(self):
        data = self.saved_bytes()
        self.assertEqual(data[:8], b"W3GLOCAL")
        self.assertEqual(struct.unpack_from("<IIII", data, 8), (1, HEADER, len(self.buffer), len(data)))
        self.assertEqual(struct.unpack_from("<II", data, 32), (1, 0))
        self.assertEqual(struct.unpack_from("<IIIIII", data, 40), tuple(self.record.race_field))
        self.assertEqual(struct.unpack_from("<II", data, 64), (0x12345678, 6))
        self.assertEqual(struct.unpack_from("<ffffff", data, 72), tuple(self.record.owner.tyres))
        self.assertEqual(data[108:172], PHYSICS)
        self.assertEqual(struct.unpack_from("<Q", data, 172)[0], self.record.recorded_at)
        self.assertEqual(data[HEADER:], bytes(self.buffer))
        self.assertEqual(data, fix_crc(data))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        result, loaded = self.load()
        self.assertEqual(result, OK)
        self.assertEqual((loaded.ramp, loaded.route, loaded.recorded_at), (1, 0, self.record.recorded_at))
        self.assertEqual(bytes(loaded.physics_sha256), PHYSICS)
        self.assertEqual(ctypes.string_at(loaded.trail, loaded.trail_bytes), bytes(self.buffer))
        self.assertEqual(self.lib.ghost_store_contains_map(ctypes.byref(loaded), 1, 0), 1)
        self.assertEqual(self.lib.ghost_store_contains_map(ctypes.byref(loaded), 2, 0), 0)
        self.assertEqual(self.lib.ghost_store_contains_map(ctypes.byref(loaded), 1, 1), 0)
        self.assert_no_temps()

    def test_loaded_trail_is_independently_owned_and_free_is_idempotent(self):
        original = self.saved_bytes()
        result, loaded = self.load()
        result2, another = self.load()
        self.assertEqual((result, result2), (OK, OK))
        self.assertNotEqual(ctypes.addressof(loaded.trail.contents), ctypes.addressof(another.trail.contents))
        loaded.trail[0] ^= 0xFF
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(ctypes.string_at(another.trail, another.trail_bytes), bytes(self.buffer))
        self.buffer[0] ^= 0xFF
        self.assertEqual(ctypes.string_at(another.trail, another.trail_bytes), native_trail())
        self.lib.ghost_store_free(ctypes.byref(loaded))
        self.assertFalse(loaded.trail)
        self.assertEqual((loaded.ramp, loaded.route, loaded.trail_bytes, loaded.recorded_at), (0, 0, 0, 0))
        self.lib.ghost_store_free(ctypes.byref(loaded))

    def test_replacement_changes_only_independent_sidecar(self):
        first = self.saved_bytes()
        other, backing = make_record(stamp=1700000123)
        other.owner.type = 0xFFFFFFFF  # No guessed private ECarType maximum in storage.
        self.assertEqual(self.save(other), OK)
        self.assertNotEqual(self.path.read_bytes(), first)
        result, loaded = self.load()
        self.assertEqual(result, OK)
        self.assertEqual((loaded.owner.type, loaded.recorded_at), (0xFFFFFFFF, other.recorded_at))
        self.assertEqual(ctypes.string_at(loaded.trail, loaded.trail_bytes), bytes(backing))

    def test_ordinary_time_attack_replay_has_separate_bounded_slots_and_no_crown(self):
        original = Crown(race=self.record, raw_model=92, raw_ramp=15, wheel=143,
                         name=(0xff21, 0, 0, 0, 0))
        record, replay_bytes = make_record(stamp=1700000123)
        record.ramp = 23
        replay = Crown(race=record, raw_model=92, raw_ramp=22, wheel=143,
                       name=(0xff22, 0, 0, 0, 0))
        path = os.fsencode(self.directory)
        self.assertEqual(self.lib.ghost_crown_save(path, 0, ctypes.byref(original), 0), OK)
        self.assertEqual(self.lib.ghost_crown_save(path, 0, ctypes.byref(replay), 0), METADATA)
        self.assertEqual(self.lib.ghost_replay_save(path, 0, 4, ctypes.byref(replay), 0), ARGUMENT)
        self.assertEqual(self.lib.ghost_replay_save(path, 0, 1, ctypes.byref(replay), 0), OK)
        loaded = Crown()
        self.addCleanup(self.lib.ghost_crown_free, ctypes.byref(loaded))
        self.assertEqual(self.lib.ghost_replay_load(path, 0, 0, PHYSICS, ctypes.byref(loaded)), NOT_FOUND)
        self.assertEqual(self.lib.ghost_replay_load(path, 0, 1, PHYSICS, ctypes.byref(loaded)), OK)
        self.assertEqual((loaded.raw_ramp, loaded.race.ramp, loaded.race.route), (22, 23, 0))
        self.assertEqual(ctypes.string_at(loaded.race.trail, loaded.race.trail_bytes), bytes(replay_bytes))
        self.assertEqual(self.lib.ghost_replay_save(path, 0, 1, ctypes.byref(replay), 0), STALE)
        replay.race.route = 1
        self.assertEqual(self.lib.ghost_replay_save(path, 0, 1, ctypes.byref(replay), loaded.revision), METADATA)
        self.assertTrue((self.directory / "ghost_crown_0").is_file())

    def test_mid_write_rename_file_fsync_and_allocation_failure_preserve_old(self):
        old = self.saved_bytes()
        other, backing = make_record(stamp=1700000123)
        for mode, expected in ((1, IO), (2, IO), (3, IO), (5, MEMORY)):
            with self.subTest(mode=mode):
                self.lib.ghost_test_failure(mode)
                self.assertEqual(self.save(other), expected)
                self.lib.ghost_test_failure(0)
                self.assertEqual(self.path.read_bytes(), old)
                self.assert_no_temps()
        self.assertEqual(bytes(backing), native_trail())

    def test_failed_first_save_does_not_create_sidecar_or_leave_owned_temps(self):
        self.lib.ghost_test_failure(1)
        self.assertEqual(self.save(), IO)
        self.lib.ghost_test_failure(0)
        self.assertFalse(self.path.exists())
        self.assert_no_temps()

    def test_post_rename_directory_sync_warning_does_not_lie_about_commit(self):
        old = self.saved_bytes()
        other, backing = make_record(stamp=1700000123)
        self.lib.ghost_test_failure(4)
        self.assertEqual(self.save(other), UNSYNCED)
        self.lib.ghost_test_failure(0)
        self.assertNotEqual(self.path.read_bytes(), old)
        result, loaded = self.load()
        self.assertEqual((result, loaded.recorded_at), (OK, other.recorded_at))
        self.assertIn(b"committed", self.lib.ghost_store_error(UNSYNCED))
        self.assert_no_temps()

    def test_interrupted_syscalls_retry_without_changing_result(self):
        for mode in (6, 7):
            with self.subTest(mode=mode):
                self.lib.ghost_test_failure(mode)
                self.assertEqual(self.save(), OK)
                self.lib.ghost_test_failure(0)
                self.assertEqual(self.load()[0], OK)
                self.assert_no_temps()

    def test_truncation_extension_oversize_and_header_overflow_fail_without_mutation(self):
        good = self.saved_bytes()
        malformed = [good[:n] for n in (0, 1, 8, 12, HEADER - 1, HEADER, len(good) - 1)]
        malformed += [good + b"extra", b"x" * (HEADER + MAX_TRAIL + 1)]
        for offset, value in ((12, 0xFFFFFFFF), (16, 0xFFFFFFFF), (20, 0xFFFFFFFF), (16, 0), (12, HEADER + 4)):
            data = bytearray(good)
            struct.pack_into("<I", data, offset, value)
            malformed.append(fix_crc(data))
        for data in malformed:
            with self.subTest(length=len(data)):
                self.path.write_bytes(data)
                result, loaded = self.load()
                self.assertEqual(result, LENGTH)
                self.assertFalse(loaded.trail)
                self.assertEqual(self.path.read_bytes(), data)
                self.assert_no_temps()

    def test_crc_covers_metadata_and_original_payload(self):
        good = self.saved_bytes()
        for offset in (32, 36, 64, 72, 100, 108, 172, HEADER + 20, len(good) - 1):
            with self.subTest(offset=offset):
                bad = bytearray(good)
                bad[offset] ^= 1
                self.path.write_bytes(bad)
                result, loaded = self.load()
                self.assertEqual(result, CHECKSUM)
                self.assertFalse(loaded.trail)
                self.assertEqual(self.path.read_bytes(), bytes(bad))

    def test_unsupported_version_and_reserved_fields_are_preserved(self):
        good = self.saved_bytes()
        for offset, value in ((8, 2), (28, 1), (180, 1)):
            data = bytearray(good)
            struct.pack_into("<I", data, offset, value)
            data = fix_crc(data)
            self.path.write_bytes(data)
            self.assertEqual(self.load()[0], VERSION)
            self.assertEqual(self.path.read_bytes(), data)
            self.assertEqual(self.save(), VERSION)
            self.assertEqual(self.path.read_bytes(), data)
        self.assert_no_temps()

    def test_physics_id_exact_matching_rejects_current_incompatibility(self):
        good = self.saved_bytes()
        result, loaded = self.load(OTHER_PHYSICS)
        self.assertEqual(result, PHYSICS_ERROR)
        self.assertFalse(loaded.trail)
        for invalid in (b"short", b"A" * 64, b"z" * 64, b"a" * 65, None):
            self.assertEqual(self.load(invalid)[0], ARGUMENT)
        bad = bytearray(good)
        bad[108] = ord("Z")
        self.path.write_bytes(fix_crc(bad))
        self.assertEqual(self.load()[0], PHYSICS_ERROR)

    def test_invalid_metadata_save_cannot_replace_old(self):
        old = self.saved_bytes()
        mutations = [lambda r: setattr(r, "ramp", 0), lambda r: setattr(r, "ramp", 23),
                     lambda r: setattr(r, "route", 0xFFFFFFFF),
                     lambda r: setattr(r, "recorded_at", 0xFFFFFFFFFFFFFFFF),
                     lambda r: setattr(r.owner, "gears", -1), lambda r: setattr(r.owner, "gears", 17),
                     lambda r: setattr(r.owner, "spokes", -1), lambda r: setattr(r.owner, "power", -1),
                     lambda r: setattr(r.owner, "handling", 25), lambda r: setattr(r.owner, "power", 24),
                     lambda r: r.owner.tyres.__setitem__(0, float("nan")),
                     lambda r: r.owner.tyres.__setitem__(2, float("inf")),
                     lambda r: r.owner.tyres.__setitem__(1, 0), lambda r: r.owner.tyres.__setitem__(4, 1e-30),
                     lambda r: r.owner.tyres.__setitem__(5, 1e8),
                     lambda r: r.race_field.__setitem__(0, 0), lambda r: r.race_field.__setitem__(1, 0xFFFFFFFF),
                     lambda r: r.race_field.__setitem__(2, 0xFFFFFFFF),
                     lambda r: r.race_field.__setitem__(3, bits(-1.0)),
                     lambda r: r.race_field.__setitem__(4, bits(0.0)),
                     lambda r: r.race_field.__setitem__(3, 0x7F800000),
                     lambda r: r.race_field.__setitem__(4, 0x7FC00000)]
        for mutation in mutations:
            record, backing = make_record()
            mutation(record)
            self.assertEqual(self.save(record), METADATA)
            self.assertEqual(self.path.read_bytes(), old)
        record, backing = make_record()
        record.physics_sha256 = b"short"
        self.assertEqual(self.save(record), PHYSICS_ERROR)
        self.assertEqual(self.path.read_bytes(), old)
        self.assert_no_temps()

    def test_negative_index_bad_float_and_tune_on_wire_rejected_even_with_new_crc(self):
        good = self.saved_bytes()
        for offset, value in ((32, 0xFFFFFFFF), (36, 0xFFFFFFFF), (40, 0), (48, 0xFFFFFFFF),
                              (52, 0x7FC00000), (56, 0x7F800000), (68, 0xFFFFFFFF),
                              (72, 0x7FC00000), (76, 0), (96, 0xFFFFFFFF), (100, 25), (104, 0xFFFFFFFF)):
            with self.subTest(offset=offset, value=value):
                data = bytearray(good)
                struct.pack_into("<I", data, offset, value)
                data = fix_crc(data)
                self.path.write_bytes(data)
                self.assertEqual(self.load()[0], METADATA)
                self.assertEqual(self.path.read_bytes(), data)

    def test_native_version_limits_checksum_and_sample_syntax_reject(self):
        old = self.saved_bytes()
        malformed = [(b"short", LENGTH), (native_trail() + b"extra", LENGTH),
                     (native_trail(nan_sample=True), TRAIL),
                     (native_trail(sample_area=99), TRAIL),
                     (native_trail(areas=(10, 10)), TRAIL), (native_trail(stage=364), TRAIL)]
        for offset, value, expected in ((0, 0x070426B, VERSION), (4, 0xFFFFFFFF, TRAIL),
                                        (4, 0, TRAIL), (28, 0xFFFFFFFF, TRAIL)):
            blob = bytearray(native_trail())
            struct.pack_into("<I", blob, offset, value)
            malformed.append((bytes(blob), expected))
        bad = bytearray(native_trail())
        bad[-1] ^= 1
        malformed.append((bytes(bad), CHECKSUM))
        for blob, expected in malformed:
            with self.subTest(expected=expected, size=len(blob)):
                record, backing = make_record(blob)
                self.assertEqual(self.save(record), expected)
                self.assertEqual(self.path.read_bytes(), old)
        record, backing = make_record()
        record.trail_bytes = MAX_TRAIL + 1
        self.assertEqual(self.save(record), LENGTH)  # Reject before dereferencing short backing.
        record.trail = None
        record.trail_bytes = 32
        self.assertEqual(self.save(record), LENGTH)
        self.assert_no_temps()

    def test_native_payload_corruption_with_recomputed_envelope_still_fails(self):
        good = self.saved_bytes()
        bad = bytearray(good)
        bad[-1] ^= 1
        bad = fix_crc(bad)
        self.path.write_bytes(bad)
        self.assertEqual(self.load()[0], CHECKSUM)
        self.assertEqual(self.path.read_bytes(), bad)

    def test_sample_nan_with_both_checksums_recomputed_still_rejected_on_load(self):
        good = self.saved_bytes()
        bad = fix_crc(good[:HEADER] + native_trail(nan_sample=True))
        self.path.write_bytes(bad)
        self.assertEqual(self.load()[0], TRAIL)
        self.assertEqual(self.path.read_bytes(), bad)

    def test_syntactic_local_load_is_not_a_native_area_approval(self):
        record, backing = make_record(native_trail(areas=(99,), sample_area=99))
        self.assertEqual(self.save(record), OK)
        result, loaded = self.load()
        self.assertEqual(result, OK)
        allowed = AreaAllowed(lambda area, _: int(area in (10, 11)))
        policy = Policy(363, allowed, None, 0)
        self.assertEqual(self.lib.ghost_store_validate_native(ctypes.byref(loaded), ctypes.byref(policy)), TRAIL)
        self.assertEqual(ctypes.string_at(loaded.trail, loaded.trail_bytes), bytes(backing))

    def test_real_explicit_area_policy_required_for_strict_validation(self):
        record, backing = make_record()
        allowed = AreaAllowed(lambda area, _: int(area in (10, 11)))
        denied = AreaAllowed(lambda area, _: 0)
        good = Policy(363, allowed, None, 0)
        wrong_stage = Policy(364, allowed, None, 0)
        bad = Policy(363, denied, None, 0)
        self.assertEqual(self.lib.ghost_store_validate_native(ctypes.byref(record), None), ARGUMENT)
        self.assertEqual(self.lib.ghost_store_validate_native(ctypes.byref(record), ctypes.byref(wrong_stage)), ARGUMENT)
        self.assertEqual(self.lib.ghost_store_validate_native(ctypes.byref(record), ctypes.byref(good)), OK)
        self.assertEqual(self.lib.ghost_store_validate_native(ctypes.byref(record), ctypes.byref(bad)), TRAIL)
        self.assertEqual(bytes(backing), native_trail())

    def test_path_traversal_relative_and_missing_directory_fail_without_any_save_touch(self):
        old = self.saved_bytes()
        for directory in ("relative", self.directory / "..", str(self.directory) + "/./",
                          str(self.directory) + "//bad", "/" + "x" * 4097):
            self.assertEqual(self.save(directory=directory), UNSAFE)
            self.assertEqual(self.load(directory=directory)[0], UNSAFE)
            self.assertEqual(self.path.read_bytes(), old)
        self.assertEqual(self.save(directory=self.directory / "nonexistent"), IO)
        self.assertFalse((self.directory / "nonexistent").exists())
        self.assertEqual(self.save(directory=str(self.directory) + "/"), OK)

    def test_symlink_directory_or_ancestor_never_followed(self):
        real = self.directory / "real"
        real.mkdir()
        alias = self.directory / "alias"
        alias.symlink_to(real, target_is_directory=True)
        nested = real / "nested"
        nested.mkdir()
        for directory in (alias, alias / "nested"):
            self.assertEqual(self.save(directory=directory), UNSAFE)
            self.assertEqual(self.load(directory=directory)[0], UNSAFE)
        self.assertFalse((real / BASENAME).exists())
        self.assertFalse((nested / BASENAME).exists())

    def test_symlink_hardlink_and_special_sidecars_are_rejected_not_replaced(self):
        sentinel = self.directory / "garage"
        self.path.symlink_to(sentinel)
        self.assertEqual(self.save(), UNSAFE)
        self.assertEqual(self.load()[0], UNSAFE)
        self.assertTrue(self.path.is_symlink())
        self.path.unlink()  # Exact test-owned symlink, not its sentinel target.
        os.link(sentinel, self.path)
        self.assertEqual(self.save(), UNSAFE)
        self.assertEqual(self.load()[0], UNSAFE)
        self.path.unlink()  # Exact test-created hardlink only.
        os.mkfifo(self.path)
        self.assertEqual(self.save(), UNSAFE)
        self.assertEqual(self.load()[0], UNSAFE)  # O_NONBLOCK means no FIFO wait.
        self.path.unlink()
        self.path.mkdir()
        self.assertEqual(self.save(), UNSAFE)
        self.assertEqual(self.load()[0], UNSAFE)

    def test_preexisting_temp_files_are_never_cleaned_or_overwritten(self):
        foreign = self.directory / (BASENAME + ".tmp.foreign")
        foreign.write_bytes(b"synthetic pre-existing file not owned by store")
        self.assertEqual(self.save(), OK)
        self.assertEqual(foreign.read_bytes(), b"synthetic pre-existing file not owned by store")
        self.lib.ghost_test_failure(2)
        self.assertEqual(self.save(), IO)
        self.lib.ghost_test_failure(0)
        self.assertEqual(foreign.read_bytes(), b"synthetic pre-existing file not owned by store")
        self.assertEqual(list(self.directory.glob(BASENAME + ".tmp.*")), [foreign])

    def test_bad_arguments_failure_out_unchanged_and_allocation_failure(self):
        self.saved_bytes()
        out = Record()
        out.ramp, out.route, out.recorded_at = 22, 123, 42
        before = bytes(out)
        self.assertEqual(self.lib.ghost_store_load(os.fsencode(self.directory), OTHER_PHYSICS, ctypes.byref(out)), PHYSICS_ERROR)
        self.assertEqual(bytes(out), before)
        self.lib.ghost_test_failure(5)
        self.assertEqual(self.lib.ghost_store_load(os.fsencode(self.directory), PHYSICS, ctypes.byref(out)), MEMORY)
        self.assertEqual(bytes(out), before)
        self.lib.ghost_test_failure(0)
        self.assertEqual(self.lib.ghost_store_save(os.fsencode(self.directory), None), ARGUMENT)
        self.assertEqual(self.lib.ghost_store_load(os.fsencode(self.directory), PHYSICS, None), ARGUMENT)
        self.assertEqual(self.lib.ghost_store_load(os.fsencode(self.directory), PHYSICS, ctypes.byref(self.record)), ARGUMENT)
        self.assertEqual(self.lib.ghost_store_contains_map(None, 1, 0), 0)
        self.lib.ghost_store_free(None)

    def test_checksum_error_text_never_claims_authentication_or_cloud_verification(self):
        self.assertIn(b"not authentication", self.lib.ghost_store_error(CHECKSUM))
        self.assertIn(b"unknown", self.lib.ghost_store_error(999))


if __name__ == "__main__":
    unittest.main(verbosity=2)
