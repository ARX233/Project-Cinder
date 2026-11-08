static int fresh[4], deliveries[4], fresh_count[4];
void car_link_fresh(int pcb,int active) { if(pcb>=0 && pcb<4) { fresh[pcb]=active; if(active) fresh_count[pcb]++; } }
int test_fresh_count(int pcb) { return fresh_count[pcb]; }
void car_link_deliver(int pcb,const unsigned char *packet,int len) { (void)packet;(void)len;if(pcb>=0 && pcb<4) deliveries[pcb]++; }
int test_fresh(int pcb) { return fresh[pcb]; }
int test_deliveries(int pcb) { return deliveries[pcb]; }
void gk_send(int peer,const void *data,int len) {(void)peer;(void)data;(void)len;}
int gk_recv(void *data,int max,int *peer) {(void)data;(void)max;(void)peer;return 0;}
