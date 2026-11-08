"""Original native body-switch groups; integrate into tools/stage/pack_cars.py.
No mesh generation: retain exact original per-car/per-body subtrees/materials.
Groups match story_part_visibility.h; native visibility helper0x8944dd0.
"""
GROUPS = {
    'MUFFLER1': 0x180, 'MUFFLER2': 0x181, 'ROLLBAR': 0x182,
    'WINKER1': 0x183, 'WINKER2': 0x184,
    'EMBLEM1': 0x185, 'EMBLEM2': 0x186,
    'GLASS1': 0x187, 'GLASS2': 0x188, 'GLASS3': 0x189,
}

def story_part_group(mesh):
    groups = [GROUPS[n] for n in mesh['path'] if n in GROUPS]
    if len(groups) > 1:
        # All214 audited bodies have independent siblings. Do not flatten an
        # unseen nested conjunction to an OR/first-match visibility guess.
        raise ValueError('nested story assembly conditions require explicit support')
    return groups[0] if groups else None

def story_part_keep(mesh, previous_keep):
    group=story_part_group(mesh)
    return True if group is not None else previous_keep(mesh)

def story_part_or_group(mesh, previous_group):
    group=story_part_group(mesh)
    return group if group is not None else previous_group(mesh)

def visible(group, flags):
    """CPU mirror of exact C contract, for static inventory/selection tests."""
    if group < 0x180 or group >= 0x18a: return None
    if group <= 0x181: return group == 0x180 + bool(flags & 1)
    if group == 0x182: return bool(flags & 2)
    if group <= 0x184: return group == 0x183 + bool(flags & 8)
    if group <= 0x186: return group == 0x185 + bool(flags & 16)
    glass=0 if not flags & 32 else 2 if flags & 64 else 1
    return group == 0x187 + glass
