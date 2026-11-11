#!/usr/bin/env python3
"""Verify the production mileage stage and its return to existing result routes."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MENU = (ROOT / "src/menu.c").read_text()
start = MENU.index("enum { MILEAGE_COUNT_TICKS")
end = MENU.index("int menu_finish_update(", start)

PREAMBLE = r'''
#include <assert.h>
#include <math.h>
#include <string.h>
#include "menu.h"
static int nexts, sounds, award_sounds;
enum { SND_FINISH, SND_RESULT_PASS };
static void snd_menu(int which) {
  assert(which == SND_FINISH || which == SND_RESULT_PASS);
  ++award_sounds;
}
static void snd_effect(const char *name, float volume) {
  assert(!strcmp(name, "odo_count") && volume == 1);
  sounds++;
}
static void go(menu_state *m, int screen) {
  m->screen = screen;
  m->t = 0;
}
static void back_from_race(menu_state *m, int white) {
  assert(!white);
  nexts++;
  go(m, MENU_GAME);
}
'''
CHECKS = r'''
static menu_state menu;
static void frame(int tap) {
  menu.t++;
  mileage_step(&menu, tap);
}
int main(void) {
  for (int mode = MENU_GAME_STORY; mode <= MENU_GAME_GHOST; ++mode) {
    memset(&menu, 0, sizeof menu);
    nexts = sounds = 0;
    menu.game = mode;
    menu.finish = 1;
    menu_finish_set_mileage(&menu, 4999700, 5005000);
    assert(menu.mileage.total_km == 4999 && menu.mileage.remaining_km == 6);
    assert(finish_leave(&menu) == MENU_LEAVE);
    assert(menu.screen == MENU_MILEAGE && !menu.finish && !nexts);

    for (int i = 0; i < MILEAGE_FADE_TICKS; i++) frame(0);
    assert(!sounds && menu.mileage.remaining_km == 6);
    frame(0);
    assert(sounds == 1 && menu.mileage.total_km == 5000);
    for (int i = 0; i < MILEAGE_COUNT_TICKS - 1; i++) frame(0);
    assert(sounds == 1 && menu.mileage.remaining_km == 5);
    frame(1);
    assert(sounds == 1 && !menu.mileage.remaining_km && menu.mileage.total_km == 5005 && !nexts);
    frame(1);
    for (int i = 0; i < MILEAGE_FADE_TICKS; i++) frame(0);
    assert(!menu.mileage.active && menu.screen == MENU_GAME && nexts == 1);
  }
  memset(&menu, 0, sizeof menu);
  nexts = 0;
  menu.finish = 1;
  menu.finish_story = 3;
  menu_finish_set_mileage(&menu, 0, 3100);
  assert(finish_leave(&menu) == MENU_LEAVE && menu.screen == MENU_GAME && nexts == 1);
  assert(mileage_km(NAN) == 0 && mileage_km(-1) == 0 && mileage_km(1e20) == 16777215);
  menu.finish = 1;
  menu.finish_story = 0;
  menu_finish_set_mileage(&menu, 2000, 2300);
  assert(!menu.mileage.remaining_km && menu.mileage.total_km == 2);
  finish_leave(&menu);
  for (int i = 0; i < MILEAGE_FADE_TICKS + MILEAGE_HOLD_TICKS - 1; i++) frame(0);
  assert(!menu.mileage.fade_out && nexts == 1);
  frame(0);
  assert(menu.mileage.fade_out == 1 && nexts == 1);
  for (int i = 0; i < MILEAGE_FADE_TICKS; i++) frame(0);
  assert(menu.screen == MENU_GAME && nexts == 2);
  memset(&menu, 0, sizeof menu);
  menu.finish = menu.finish_goal = 1;
  menu.finish_ghost = MENU_GHOST_RESULT_LOSE;
  menu_finish_set_crown_award(&menu, 2, 0, 0);
  assert(!menu.crown_award.active);
  menu.finish_ghost = MENU_GHOST_RESULT_WIN;
  menu_finish_set_mileage(&menu, 1000, 3000);
  menu_finish_set_crown_award(&menu, 2, 0, 1);
  assert(menu.crown_award.active && menu.crown_award.pending);
  assert(finish_leave(&menu) == MENU_LEAVE && menu.screen == MENU_MILEAGE);
  assert(!menu.crown_award.active && !award_sounds);
  menu.finish = 1;
  menu_finish_set_crown_award(&menu, 2, 0, 0);
  assert(finish_leave(&menu) == MENU_LEAVE && menu.screen == MENU_CROWN_AWARD);
  for (int i = 0; i < CROWN_AWARD_NORMAL + 2 * CROWN_AWARD_FADE - 1; ++i) {
    ++menu.t;
    crown_award_step(&menu);
    assert(menu.screen == MENU_CROWN_AWARD);
  }
  ++menu.t;
  crown_award_step(&menu);
  assert(menu.screen == MENU_MILEAGE && menu.mileage.active && award_sounds == 2);
  return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="cinder-mileage-") as directory:
    source = Path(directory) / "mileage.c"
    executable = source.with_suffix("")
    source.write_text(PREAMBLE + MENU[start:end] + CHECKS)
    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=undefined", "-fno-sanitize-recover=all",
                    "-I", str(ROOT / "src"), str(source), "-lm", "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
print("PASS five mileage routes, carry exclusion, count timing, tap, and automatic dismissal")
