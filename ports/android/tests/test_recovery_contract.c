/* Standalone helper tests only; not app integration. */
#include "../src/vs_recovery.h"
#include "../src/vs_recovery_wire.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void) {
  const uint64_t roster[] = {11,22,33}, absent[] = {11,33}, dup[] = {11,22,22};
  vs_recovery s;
  unsigned char base[VS_RECOVERY_WIRE_BASE_SIZE], packet[VS_RECOVERY_WIRE_SIZE];
  vs_recovery_wire_extension e = {VS_RECOVERY_WIRE_ABORT,77,1234,42}, d;
  assert(!vs_recovery_init(&s,dup,3,11,77,0,21000));
  assert(vs_recovery_init(&s,roster,3,11,77,0,21000));
  assert(vs_recovery_observe(&s,77,1,1,roster,3)==VS_RECOVERY_ACCEPTED);
  assert(vs_recovery_observe(&s,77,2,1000,absent,2)==VS_RECOVERY_ACCEPTED);
  assert(vs_recovery_observe(&s,77,2,22000,absent,2)==VS_RECOVERY_IGNORED);
  assert(vs_recovery_observe(&s,78,3,22000,absent,2)==VS_RECOVERY_IGNORED);
  assert(vs_recovery_observe(&s,77,3,21999,absent,2)==VS_RECOVERY_ACCEPTED);
  assert(vs_recovery_observe(&s,77,4,22000,absent,2)==VS_RECOVERY_EMIT_ABORT);
  assert(s.reason==VS_RECOVERY_ABORT_MISSING && s.missing_id==22);
  assert(vs_recovery_observe(&s,77,5,23000,roster,3)==VS_RECOVERY_IGNORED);
  vs_recovery_acknowledge(&s);
  assert(s.acknowledged && s.reason==VS_RECOVERY_ABORT_MISSING);
  assert(vs_recovery_init(&s,roster,3,11,78,23000,21000));
  assert(s.reason==VS_RECOVERY_NO_ABORT && !s.acknowledged);
  memset(base,0x5a,sizeof base);
  assert(vs_recovery_wire_encode(packet,sizeof packet,base,sizeof base,&e));
  assert(!memcmp(packet,base,sizeof base));
  assert(!vs_recovery_wire_decode(&d,base,sizeof base));
  assert(vs_recovery_wire_decode(&d,packet,sizeof packet));
  assert(vs_recovery_wire_accept_peer(&d,1234,77,41));
  assert(!vs_recovery_wire_accept_peer(&d,1234,77,42));
  assert(!vs_recovery_wire_accept_peer(&d,1234,78,41));
  assert(!vs_recovery_wire_accept_peer(&d,1235,77,41));
  assert(!vs_recovery_wire_accept_peer(&d,1234,77,43));
  assert(vs_recovery_wire_seq_newer(0,UINT32_MAX));
  assert(!vs_recovery_wire_seq_newer(UINT32_C(0x80000000),0));
  assert(!vs_recovery_wire_encode(packet,sizeof packet,packet,sizeof packet,&e));
  unsigned char ready[VS_RECOVERY_READY_SIZE], prefix[VS_RECOVERY_WIRE_SIZE]; int loaded = -1;
  assert(vs_recovery_wire_encode(ready,sizeof ready,base,sizeof base,&e));
  memcpy(prefix,ready,sizeof prefix);
  assert(vs_recovery_wire_put_ready(ready,sizeof ready,0));
  assert(!memcmp(prefix,ready,sizeof prefix));
  assert(vs_recovery_wire_read_ready(ready,sizeof ready,&loaded) && loaded==0);
  assert(vs_recovery_wire_decode(&d,ready,sizeof ready));
  assert(vs_recovery_wire_put_ready(ready,sizeof ready,1));
  assert(vs_recovery_wire_read_ready(ready,sizeof ready,&loaded) && loaded==1);
  loaded=-1; assert(!vs_recovery_wire_read_ready(ready,42,&loaded) && loaded==-1);
  ready[46]=2; assert(!vs_recovery_wire_read_ready(ready,sizeof ready,&loaded) && loaded==-1);
  assert(!vs_recovery_wire_put_ready(ready,sizeof ready,2));
  puts("recovery primitive contracts OK");
  return 0;
}
