"""Exercise production story selection with synthetic data, never original assets."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
ANDROID = ROOT / "ports/android"
GENERATED = Path(os.environ.get("WMMT_GENERATED_ROOT", ROOT.parent / "control-layout-v12")) / "android/project/src"
WORK = Path("/Volumes/CodexWork")


class StoryDefaultsMenuHost(unittest.TestCase):
    def test_story_defaults(self):
        if sys.platform != "darwin" or not shutil.which("clang"):
            self.skipTest("requires macOS clang and Darwin dead-strip linker")
        if not (GENERATED / "cardb.h").is_file():
            self.skipTest("generated support headers unavailable")
        if not WORK.is_dir():
            self.skipTest("/Volumes/CodexWork unavailable for temporary output")
        with tempfile.TemporaryDirectory(prefix="wmmt-story-defaults-", dir=WORK) as tmp:
            tmp = Path(tmp)
            # Entirely invented values, different by row and music group.
            rows = [f"  {{{1 - i % 2}, {{{1 + i % 10}, {2 + i % 10}, {3 + i % 10}}}}}," for i in range(111)]
            (tmp / "story_defaults_private.h").write_text(
                "typedef struct { unsigned char day; unsigned char bgm[3]; } story_default_row;\n"
                "static const story_default_row story_defaults_private[111] = {\n"
                + "\n".join(rows) + "\n};\n", encoding="ascii")
            binary = tmp / "test"
            cmd = ["clang", "-std=gnu99", "-U__APPLE__", "-DWMMT_STORY_DEFAULTS_TEST", "-DWMMT_BGM_TEST",
                   "-fsanitize=undefined", "-fno-sanitize-recover=all",
                   "-I", str(tmp), "-I", str(ANDROID / "test"), "-I", str(GENERATED),
                   f'-DPORT_MENU="{ANDROID / "src/menu.c"}"', "-ffunction-sections", "-fdata-sections",
                   str(ANDROID / "tests/story_defaults_menu_host.c"), "-Wl,-dead_strip",
                   "-Wl,-undefined,dynamic_lookup", "-o", str(binary)]
            subprocess.run(cmd, check=True, cwd=tmp, env={**os.environ, "TMPDIR": str(tmp)})
            subprocess.run([str(binary)], check=True, cwd=tmp, timeout=30, env={**os.environ, "TMPDIR": str(tmp)})


if __name__ == "__main__":
    unittest.main()
