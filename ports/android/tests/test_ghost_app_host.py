#!/usr/bin/env python3
"""CPU tests of production app Ghost functions and actual app.c wiring.

The included app_ghost.inc is unmodified production code. Menu, native engine,
resource catalog and local IO are strict public-interface doubles, not a fake
implementation of the app. No private native frames/paths enter this fixture.
Optional full-app syntax checks use existing reviewed generated headers read-only.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TMP = Path(os.environ.get("TMPDIR", str(ROOT.parent / "tmp"))).resolve()
TMP.mkdir(parents=True, exist_ok=True)
if TMP == ROOT or ROOT in TMP.parents:
    raise SystemExit("TMPDIR must be outside source")
app = (SRC / "app.c").read_text()
glue = (SRC / "app_ghost.inc").read_text()
# Wiring checks accompany executable function tests: no unattached API-only mode.
assert '#include "app_ghost.inc"' in app
assert "app_ghost_menu();\n  if (!app_ghost_mode()) vs_menu();" in app
assert "go && app_ghost_mode() && !app_ghost_go_valid()" in app
assert "if (!ghost) car_set_rivals(rv," in app
assert "if (ghost && !app_ghost_started(&spec))" in app
assert app.index("if (app_ghost_finish())") < app.index("if (!app_ghost_mode() && race->over && !G.menu.finish && !G.vs_closed")
assert "!app_ghost_mode() && !(G.menu.game == MENU_GAME_STORY" in app
assert "app_ghost_fail(\"RUN CANCELLED - PREVIOUS RECORD KEPT\")" in app
assert "G.menu.ready = app_ghost_mode() ? all_in && AG.prepared" in app
assert "if (ghost_pack >= 0) all_in" in app
assert "WANT(ghost_pack);" in app
assert "GHOST LOADING TIMED OUT - NOT STARTED" in app
assert "route == 0" in glue and "CLOUD NOT CONFIGURED" in glue
for forbidden in ("net_open(", "net_poll(", "net_send(", "net_scan(", "vs_host_open(", "menu_vs_", "car_set_rivals(",
                  "title_race_over(", "garage_save(", "records_finish(", "car_best", "best_ms", "vs_stars_car"):
    assert forbidden not in glue, forbidden
cc = os.environ.get("CC", "clang")
with tempfile.TemporaryDirectory(prefix="ghost-app-host-", dir=TMP) as tmp:
    tmp = Path(tmp)
    exe = tmp / "ghost-app"
    cmd = [cc, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
           "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(SRC),
           str(ROOT / "tests/test_ghost_app_host.c"), "-lm", "-o", str(exe)]
    subprocess.run(cmd, check=True, cwd=tmp, timeout=120)
    subprocess.run([str(exe)], check=True, cwd=tmp, timeout=30,
                   env=dict(os.environ, UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"))
    private_arg = os.environ.get("CINDER_PRIVATE_SRC")
    if private_arg and sys.platform == "darwin":
        # Host declarations only: no GL/EGL runtime is linked or executed.
        (tmp / "EGL").mkdir()
        (tmp / "EGL/egl.h").write_text("void (*eglGetProcAddress(const char *name))(void);\n")
        (tmp / "gl-declarations.h").write_text(
            '#include <OpenGL/gl3.h>\n'
            'GLuint gl_compile_program(const char *vs, const char *fs, const char **attribs, int n_attribs);\n')
        private = Path(private_arg).resolve()
        if not (private / "cardb.h").is_file():
            raise SystemExit("CINDER_PRIVATE_SRC must contain reviewed generated headers")
        for label, flags in (("GLES", []), ("VKcompat", ["-DWMMT_VK=1"]),
                             ("NativeVulkan", ["-DWMMT_VK=1", "-DWMMT_NATIVE_VK=1"])):
            if label == "NativeVulkan":
                vk_include = os.environ.get("CINDER_VULKAN_INCLUDE")
                if not vk_include:
                    print("NativeVulkan syntax SKIP: set CINDER_VULKAN_INCLUDE to existing SDK headers")
                    continue
                flags = [*flags, "-idirafter", str(Path(vk_include).resolve())]
            cmd = [cc, "-std=gnu11", "-fsyntax-only", "-D__ANDROID__=1",
                   "-DWMMT_GL_H=1", "-Wno-deprecated-declarations", "-include", str(tmp / "gl-declarations.h"),
                   "-I", str(tmp), "-I", str(SRC), "-I", str(ROOT / "test"), "-I", str(private),
                   *flags, str(SRC / "app.c")]
            subprocess.run(cmd, check=True, cwd=tmp, timeout=120)
            print(label, "complete production app.c syntax PASS")
print("PASS actual app wiring: PRE/GO fail-closed, resources, native start, separate results, legacy authority gates")
