#include "vs_recovery_wire.h"
#include <stdint.h>
#include <string.h>

/* Difference comparisons avoid address+length wrap. No pointers are read. */
static int overlaps(const void *a, size_t an, const void *b, size_t bn)
{
    uintptr_t x = (uintptr_t)a, y = (uintptr_t)b;
    return x <= y ? y - x < an : x - y < bn;
}
static int valid(const vs_recovery_wire_extension *e)
{
    return e->flags <= VS_RECOVERY_WIRE_FINISHED && e->nonce != 0 &&
           (e->flags == VS_RECOVERY_WIRE_NORMAL || e->race_id != 0);
}
static void put_le(uint8_t *p, uint64_t value, unsigned n)
{
    unsigned i;
    for (i = 0; i < n; ++i) p[i] = (uint8_t)(value >> (8u * i));
}
static uint64_t get_le(const uint8_t *p, unsigned n)
{
    uint64_t value = 0;
    unsigned i;
    for (i = 0; i < n; ++i) value |= (uint64_t)p[i] << (8u * i);
    return value;
}
int vs_recovery_wire_encode(uint8_t *out, size_t cap, const uint8_t *base,
                            size_t len, const vs_recovery_wire_extension *e)
{
    uint8_t result[VS_RECOVERY_WIRE_SIZE];
    if (!out || !base || !e || cap < VS_RECOVERY_WIRE_SIZE ||
        len < VS_RECOVERY_WIRE_BASE_SIZE ||
        overlaps(out, VS_RECOVERY_WIRE_SIZE, base, VS_RECOVERY_WIRE_BASE_SIZE) ||
        overlaps(out, VS_RECOVERY_WIRE_SIZE, e, sizeof(*e)) || !valid(e)) return 0;
    memcpy(result, base, VS_RECOVERY_WIRE_BASE_SIZE);
    memcpy(result + 21, "RFR1", 4);
    result[25] = e->flags;
    put_le(result + 26, e->race_id, 4);
    put_le(result + 30, e->nonce, 8);
    put_le(result + 38, e->seq, 4);
    memcpy(out, result, sizeof(result));
    return 1;
}
int vs_recovery_wire_decode(vs_recovery_wire_extension *out,
                            const uint8_t *profile, size_t len)
{
    vs_recovery_wire_extension e;
    if (!out || !profile || len < VS_RECOVERY_WIRE_SIZE ||
        overlaps(out, sizeof(*out), profile, len) ||
        memcmp(profile + 21, "RFR1", 4) != 0) return 0;
    e.flags = profile[25];
    e.race_id = (uint32_t)get_le(profile + 26, 4);
    e.nonce = get_le(profile + 30, 8);
    e.seq = (uint32_t)get_le(profile + 38, 4);
    if (!valid(&e)) return 0;
    *out = e;
    return 1;
}
int vs_recovery_wire_put_ready(uint8_t *profile, size_t capacity, int loaded)
{
    vs_recovery_wire_extension e;
    if (!profile || capacity < VS_RECOVERY_READY_SIZE || (loaded != 0 && loaded != 1) ||
        !vs_recovery_wire_decode(&e, profile, VS_RECOVERY_WIRE_SIZE)) return 0;
    memcpy(profile + VS_RECOVERY_WIRE_SIZE, "RDY1", 4);
    profile[VS_RECOVERY_WIRE_SIZE + 4] = (uint8_t)loaded;
    return 1;
}
int vs_recovery_wire_read_ready(const uint8_t *profile, size_t length, int *loaded)
{
    vs_recovery_wire_extension e;
    if (!profile || !loaded || length < VS_RECOVERY_READY_SIZE ||
        overlaps(loaded, sizeof(*loaded), profile, length) ||
        !vs_recovery_wire_decode(&e, profile, length) ||
        memcmp(profile + VS_RECOVERY_WIRE_SIZE, "RDY1", 4) ||
        profile[VS_RECOVERY_WIRE_SIZE + 4] > 1) return 0;
    *loaded = profile[VS_RECOVERY_WIRE_SIZE + 4];
    return 1;
}
int vs_recovery_wire_seq_newer(uint32_t candidate, uint32_t last)
{
    uint32_t delta = candidate - last;
    return delta != 0 && delta < UINT32_C(0x80000000);
}
int vs_recovery_wire_accept_peer(const vs_recovery_wire_extension *peer,
                                 uint64_t nonce, uint32_t race, uint32_t last)
{
    return peer && valid(peer) && nonce != 0 && race != 0 &&
           peer->nonce == nonce && peer->race_id == race &&
           vs_recovery_wire_seq_newer(peer->seq, last);
}
