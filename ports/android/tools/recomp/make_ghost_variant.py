#!/usr/bin/env python3
"""Create a PRIVATE Ghost physics variant, never rewrite the reviewed baseline.

Only the three original CSampler no-record functions and their missing native
callees are translated from the caller-selected original ELF. Existing native
physics bodies are retained; PLT file calls route through bounded opaque Ghost
streams (ordinary handles retain the baseline behavior). Recording entry guards
exactly reproduce the old no-op when no explicit Ghost recording session is on.
No original generated source or frame data belongs in the public repository.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile

BASELINE_SHA256 = 'a4d98adbe6b3bc8a86b09adc9f7af5c97a78a3298126bc0c1b0d18fb8f1ee26b'
MAIN_SHA256 = '2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'
RECORD = {0x89e03e0, 0x89e0428, 0x89e1130}
EXTRA_ROOTS = {0x89924c8, 0x8982d44}  # original Target race field and 2D getter
BODY = re.compile(r'^void (f_[0-9a-f]+)\(void\) \{\n.*?^\}\n', re.M | re.S)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--elf', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline, elf, output = (p.resolve() for p in (args.baseline, args.elf, args.output))
    if output == baseline or output == elf or output.exists():
        parser.error('output must be an absent PRIVATE path, distinct from every input')
    if digest(baseline) != BASELINE_SHA256 or digest(elf) != MAIN_SHA256:
        parser.error('input identity mismatch; a new baseline requires explicit review')
    os.environ['WMMT_MAIN'] = str(elf)
    spec = importlib.util.spec_from_file_location('ghost_original_recompiler', Path(__file__).with_name('recomp.py'))
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    rc.NO_RECORD = set()
    translation = rc.Translator()
    for address in sorted(RECORD | EXTRA_ROOTS):
        translation.add(address)
    translation.run()
    if translation.problems:
        raise SystemExit('native recording translation incomplete: ' + repr(translation.problems))
    # Keep this intermediate output beside the private output, not system /tmp.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='ghost-record-', suffix='.c', dir=output.parent, delete=False) as temp:
        extra_path = Path(temp.name)
    translation.emit(str(extra_path))
    extra = extra_path.read_text()
    old = baseline.read_text()
    old_bodies = {m.group(1): m.group(0) for m in BODY.finditer(old)}
    native_bodies = {m.group(1): m.group(0) for m in BODY.finditer(extra)}
    required = {'f_%x' % address for address in RECORD}
    if not required <= native_bodies.keys():
        raise SystemExit('missing original native recording body')
    additions = {}
    for name, body in native_bodies.items():
        if name in required:
            address = int(name[2:], 16)
            guard = ('  if (!rc_ghost_recording_enabled()) { rc_cpu.eax = 0; rc_cpu.esp += 4; return; }\n')
            body = body.replace('  RC_ENTRY(0x%xu);\n' % address, guard + '  RC_ENTRY(0x%xu);\n' % address, 1)
            # Assert the exact reviewed old no-record stub, before replacing it.
            expected = ('void %s(void) {\n  uint32_t esp = rc_cpu.esp, eax = rc_cpu.eax;\n'
                        '  eax = 0; esp += 4;\n  rc_cpu.esp = esp; rc_cpu.eax = eax;\n}\n') % name
            if old_bodies.get(name) != expected:
                raise SystemExit('baseline recording stub mismatch: ' + name)
            old = old.replace(expected, body, 1)
        elif name not in old_bodies:
            additions[name] = body
    # Original direct callees absent from the old closure need declarations and
    # dispatch entries; existing same-address bodies are NEVER replaced.
    declaration = ''.join('void %s(void);\n' % n for n in sorted(additions))
    cohort_base = {
        'baseline_source_sha256': BASELINE_SHA256, 'original_elf_sha256': MAIN_SHA256,
        'original_image_sha256': '5790b205045807181ab3931c9583b5652f7be9b8e7af8b9c1680c00325db0bd4',
        'recompiler_sha256': digest(Path(__file__).with_name('recomp.py')),
        'ghost_patcher_sha256': digest(Path(__file__)),
        'native_abi': 'ctarget-ghost-memory-v1-route0',
        'frontend_route_support': 'original ERamp 1..22; route0/fraction0 only; other routes fail closed',
        'floating_contract': 'IEEE-float32; no-fast-math; FP_CONTRACT-OFF',
    }
    cohorts = {}
    for model in ('binary64-p53', 'extended-p64', 'binary128-p113'):
        preimage = dict(cohort_base, floating_accumulator=model)
        cohorts[model] = hashlib.sha256(json.dumps(preimage, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    identity = ('\n#include <float.h>\n#pragma STDC FP_CONTRACT OFF\n'
                'const volatile uint32_t rc_ghost_native_bridge = 0x47485331u;\n'
                'const char *rc_ghost_physics_id(void) {\n'
                '#if defined(__FAST_MATH__) || (__BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__)\n'
                '  return 0;\n#else\n'
                '  if (FLT_RADIX != 2 || FLT_MANT_DIG != 24) return 0;\n'
                '  if (sizeof(fpt) == 8 && DBL_MANT_DIG == 53 && DBL_MAX_EXP == 1024) return "' + cohorts['binary64-p53'] + '";\n'
                '  if (sizeof(fpt) == sizeof(long double) && LDBL_MANT_DIG == 64 && LDBL_MAX_EXP == 16384) return "' + cohorts['extended-p64'] + '";\n'
                '  if (sizeof(fpt) == sizeof(long double) && LDBL_MANT_DIG == 113 && LDBL_MAX_EXP == 16384) return "' + cohorts['binary128-p113'] + '";\n'
                '  return 0;\n#endif\n}\n')
    old = old.replace('#include "rc_runtime.h"\n', '#include "rc_runtime.h"\n' + declaration + identity, 1)
    dispatch = old.index('void rc_dispatch(uint32_t t) {')
    old = old[:dispatch] + '\n'.join(additions.values()) + '\n' + old[dispatch:]
    for name in sorted(additions):
        address = int(name[2:], 16)
        old = old.replace('  switch (t) {\n', '  switch (t) {\n  case 0x%xu: %s(); return;\n' % (address, name), 1)
    replacements = {
        'eax = rc_fopen(A32(0));': 'eax = rc_ghost_fopen(A32(0), A32(1));',
        'eax = rc_fread(A32(0), A32(1), A32(2), A32(3));': 'eax = rc_ghost_fread(A32(0), A32(1), A32(2), A32(3));',
        'rc_fclose(A32(0));': 'rc_ghost_fclose(A32(0));',
        'eax = rc_feof(A32(0));': 'eax = rc_ghost_feof(A32(0));',
    }
    for before, after in replacements.items():
        old = old.replace(before, after)
    write_targets = {a for a, name in rc.PLT.items() if name == 'fwrite'}
    patched_writes = 0
    lines = []
    for line in old.splitlines(keepends=True):
        match = re.search(r'/\* [0-9a-f]+: (?:call|jmp) 0x([0-9a-f]+) \*/', line)
        if match and int(match.group(1), 16) in write_targets:
            if line.count('eax = 0;') != 1:
                raise SystemExit('unreviewed fwrite bridge shape')
            line = line.replace('eax = 0;', 'eax = rc_ghost_fwrite(A32(0), A32(1), A32(2), A32(3));')
            patched_writes += 1
        if '/* 898cf14: jne 0x898d440 */' in line:
            if 'if (!ZF) goto L_898d440;' not in line:
                raise SystemExit('unreviewed original recording mode branch')
            line = line.replace('if (!ZF) goto L_898d440;',
                                'if (!ZF || (rc_ghost_recording_enabled() && ecx == 6u)) goto L_898d440;')
        if '/* 898807e: call 0x89c3a64 */' in line:
            lines.append('  rc_cpu.ebp = ebp; rc_cpu.esp = esp; rc_hook(0x898807eu);\n')
        if '/* 898484c: call 0x89ae9a0 */' in line:
            lines.append('  rc_cpu.ebp = ebp; rc_cpu.esp = esp; rc_hook(0x898484cu);\n')
        lines.append(line)
    old = ''.join(lines)
    # Fail closed if ANY existing native body changed outside the explicitly
    # audited recording entries, opaque imports, observer hooks and gate branch.
    normalized = old
    for before, after in replacements.items():
        normalized = normalized.replace(after, before)
    normalized = normalized.replace('eax = rc_ghost_fwrite(A32(0), A32(1), A32(2), A32(3));', 'eax = 0;')
    normalized = normalized.replace('  rc_cpu.ebp = ebp; rc_cpu.esp = esp; rc_hook(0x898807eu);\n', '')
    normalized = normalized.replace('  rc_cpu.ebp = ebp; rc_cpu.esp = esp; rc_hook(0x898484cu);\n', '')
    normalized = normalized.replace('if (!ZF || (rc_ghost_recording_enabled() && ecx == 6u)) goto L_898d440;',
                                    'if (!ZF) goto L_898d440;')
    checked = {m.group(1): m.group(0) for m in BODY.finditer(normalized)}
    for name, body in old_bodies.items():
        if name not in required and checked.get(name) != body:
            raise SystemExit('unexpected native body change: ' + name)
    if not patched_writes:
        raise SystemExit('no original fwrite callsites patched')
    with output.open('x') as stream:
        stream.write(old)
    manifest = {
        'baseline_sha256': digest(baseline), 'original_elf_sha256': digest(elf),
        'variant_sha256': digest(output), 'restored_native_functions': sorted(hex(x) for x in RECORD),
        'baseline_native_body_count': len(old_bodies),
        'unchanged_existing_bodies_after_audited_bridge_normalization': len(old_bodies) - len(RECORD),
        'cseq_init_before_sha256': hashlib.sha256(old_bodies['f_89878c4'].encode()).hexdigest(),
        'cseq_init_variant_sha256': hashlib.sha256(next(m.group(0) for m in BODY.finditer(old) if m.group(1) == 'f_89878c4').encode()).hexdigest(),
        'new_native_callees': sorted(additions), 'opaque_fwrite_sites': patched_writes,
        'qualification_constructor_branch': {
            'original_address': '0x898cf14',
            'original_bytes': rc.data[rc.file_off(0x898cf14):rc.file_off(0x898cf14) + 6].hex(),
            'original_label': 'L_898d440',
            'before': 'if (!ZF) goto L_898d440;',
            'after': 'if (!ZF || (rc_ghost_recording_enabled() && ecx == 6u)) goto L_898d440;',
            'gate_off': 'identical original control flow',
        },
        'physics_cohort_preimage_without_accumulator': cohort_base,
        'physics_cohorts': cohorts,
        'recording_default': 'original no-op; enabled only by explicit Ghost session',
        'limitations': ['No runtime or device equivalence is implied by successful translation.'],
    }
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
