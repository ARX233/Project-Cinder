/* Native host test. Link car.c, ghost_runtime.c, ghost_format.c, tire_smoke.c,
 * phys/rc_runtime.c and the host arcade physics object, with -DWMMT_EGL
 * -DRC_FPT=double -Isrc -lm -lz. Argument: converted physics data directory. */
#include "car.h"
#include "cardb.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>

static unsigned char outgoing[CAR_LINK_PACKET], incoming[CAR_LINK_PACKET];
static int slot, sent, received;

static void on_send(const unsigned char *packet, int n, void *ctx) {
  (void)ctx;
  assert(n == sizeof outgoing);
  memcpy(outgoing, packet, n);
  sent = 1;
}

static void on_receive(void *ctx) {
  (void)ctx;
  if (received) car_link_deliver(slot ^ 1, incoming, sizeof incoming);
}

static int lamp_on(int offset) {
  return !(offset >= 161 && offset < 209 && (offset - 161) % 20 < 8);
}

static void run_peer(int fd, const char *data) {
  char error[256];
  if (car_init(data, error, sizeof error)) {
    fprintf(stderr, "%s\n", error);
    exit(1);
  }
  car_spec me = CAR_SPEC_FD3S;
  me.power = me.handling = 10;
  car_link_car rival = {.pcb = slot ^ 1, .type = me.type, .power = me.power,
                       .handling = me.handling, .spokes = me.spokes};
  memcpy(rival.tyres, me.tyres, sizeof rival.tyres);
  car_link_io io = {on_send, on_receive, NULL};
  car_set_versus(slot, &rival, 1, 0, 12, 1, &io);
  car_state car;
  assert(car_start(&car, 0, 0, &me) == 0);
  int active = -1;
  for (int tick = 0; tick < 490; ++tick) {
    if (car.race.play_state == 2 && active < 0) active = tick;
    int offset = active >= 0 ? tick - active : -1;
    /* A second press during the first pulse leaves the native sequence intact. */
    car_input in = {.throttle = 1, .passing = slot == 0 && (offset == 160 || offset == 165)};
    sent = 0;
    car_update(&car, &in);
    if (offset >= 145 && offset <= 220) {
      assert(sent && car.rival_shown[0]);
      assert(car.spot == (slot == 0 ? lamp_on(offset) : 1));
      assert((outgoing[0x251] & 1) == car.spot);
      assert(car.rival_spot[0] == (slot == 1 ? lamp_on(offset - 1) : 1));
    }
    assert(send(fd, outgoing, sizeof outgoing, 0) == sizeof outgoing);
    assert(recv(fd, incoming, sizeof incoming, 0) == sizeof incoming);
    received = 1;
  }
  assert(active >= 0 && active + 220 < 490);
}

int main(int argc, char **argv) {
  assert(argc == 2);
  alarm(20);
  int fd[2];
  assert(socketpair(AF_UNIX, SOCK_DGRAM, 0, fd) == 0);
  pid_t peer = fork();
  assert(peer >= 0);
  if (!peer) {
    alarm(20);
    slot = 1;
    close(fd[0]);
    run_peer(fd[1], argv[1]);
    _exit(0);
  }
  close(fd[1]);
  run_peer(fd[0], argv[1]);
  int status;
  assert(waitpid(peer, &status, 0) == peer && WIFEXITED(status) && WEXITSTATUS(status) == 0);
  puts("Arcade VS passing input, pulse timing and peer packet passed");
  return 0;
}
