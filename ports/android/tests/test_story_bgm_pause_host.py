from pathlib import Path
root = Path(__file__).resolve().parents[1]
app = (root / "src/app.c").read_text()
native = (root / "src/main_android.c").read_text()
getter = app[app.index("int app_bgm_gameplay_paused(void)"):app.index("/* clRaceThread::race", app.index("int app_bgm_gameplay_paused(void)"))]
for token in ("!G.in_menu", "!G.menu.finish", "!G.vs_race", "!G.n_ten", "MENU_GAME_STORY", "G.story_end_freeze > 0"):
    assert token in getter
assert "if (G.ten_freeze > 0 || G.story_end_freeze > 0) hud_negate" in app
import re
assignments = list(re.finditer(r'G\.story_end_freeze = hud_story_cutin_goal_hold\(&G\.car\.race\);', app))
assert len(assignments) == 3
for m in assignments:
    after = app[m.end():m.end() + 180]
    assert re.search(r'#ifdef __ANDROID__\s+if \(G\.story_end_freeze > 0\) android_story_bgm_pause\(\);\s+#endif', after)
assert 'void android_story_bgm_pause(void) { sync_bgm_gameplay_pause(1); }' in native
frame = native[native.index("    app_present(dt);"):native.index("    app_frame_done(present_ms);")]
assert frame.index("app_present(dt)") < frame.index("sync_movie()") < frame.index("eglSwapBuffers(")
sync = native[native.index("static void sync_movie(void)"):native.index("/* ---- GL ---- */")]
assert sync.index("if (paused &&") < sync.index("call_str(A.play_bgm, track)") < sync.index("if (!paused &&")
assert "A.bgm_gameplay_paused = -1" in sync
base = (root / "test/extra_bgm_state_test.py").read_text()
base = base.replace("a=p.index('  void setBgmVolume(')", "a=p.index('  void setBgmGameplayPaused(')")
base = base.replace("boolean resumed=true,bgmPreparing,bgmGameplayPaused;", "boolean resumed=true,bgmPreparing; volatile boolean bgmGameplayPaused; long bgmPauseRevision;")
base = base.replace("void pause(){if(preparing)", "boolean isPlaying(){return playing;} void pause(){if(preparing)")
insert = """
   // An already queued legacy start must see the pause before the UI queue drains.
   a.playBgm("legacy");a.setBgmGameplayPaused(true);a.drain();MediaPlayer early=a.bgm;check(legacy.released&&!early.playing);legacy=early;
   a.setBgmGameplayPaused(false);a.setBgmGameplayPaused(true);a.drain();check(!legacy.playing);
   a.setBgmGameplayPaused(true);a.drain();check(!legacy.playing&&!legacy.released);
   a.onPause();a.onResume();check(!legacy.playing);
   a.setBgmGameplayPaused(false);a.drain();check(legacy.playing&&!legacy.released);
   a.setBgmGameplayPaused(true);a.playBgm("wm2_01");a.drain();check(legacy.released);a.worker();a.drain();MediaPlayer frozen=a.bgm;frozen.firePrepared();check(!frozen.playing);
   a.onPause();a.setBgmGameplayPaused(false);a.drain();check(!frozen.playing);a.onResume();check(frozen.playing&&!frozen.released);
   a.setBgmGameplayPaused(true);a.playBgm("legacy");a.drain();check(frozen.released&&!a.bgm.playing);a.setBgmGameplayPaused(false);a.drain();check(a.bgm.playing);
"""
needle = '  a.playBgm("wm2_01");a.drain();a.worker();a.drain();MediaPlayer dead='
assert needle in base
base = base.replace(needle, insert + needle)
base = base.replace('&&previous.logHandler.removed==previous.logHealthCheck&&previous.consentDialog.dismissed', '')
assert '   previous.onDestroy();' in base
base = base.replace('   previous.onDestroy();', '   previous.setBgmGameplayPaused(true);previous.drain();check(!replacement.bgmGameplayPaused);previous.onDestroy();')
exec(compile(base, str(root / "test/extra_bgm_state_test.py"), "exec"), {"__file__": str(root / "test/extra_bgm_state_test.py"), "__name__": "__main__"})
print("story BGM pause source and player contracts passed")
