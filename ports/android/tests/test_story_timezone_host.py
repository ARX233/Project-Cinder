"""Run production menu.c on macOS with host stubs; no assets or device.

Run: python3 ports/android/tests/test_story_timezone_host.py
WMMT_GENERATED_ROOT optionally names control-layout-v12, which must contain
android/project/src and ipad/project/src; generated files are read-only.
This menu-state test does not exercise app.c persistence or asset loading.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
GENERATED = Path(os.environ.get("WMMT_GENERATED_ROOT", ROOT.parent / "control-layout-v12"))
FIXTURE = Path(__file__).with_name("story_timezone_host.c")

class StoryTimezoneHost(unittest.TestCase):
    def test_production_menus(self):
        if sys.platform != "darwin" or not shutil.which("clang"):
            self.skipTest("requires macOS clang and Darwin dead-strip linker")
        with tempfile.TemporaryDirectory(prefix="wmmt-story-host-") as tmp:
            for port in ("android", "ipad"):
                with self.subTest(port=port):
                    generated = GENERATED / port / "project" / "src"
                    if not (generated / "cardb.h").is_file():
                        self.skipTest(f"generated headers unavailable: {generated}")
                    menu = ROOT / "ports" / port / "src" / "menu.c"
                    binary = Path(tmp) / port
                    cmd = ["clang", "-std=gnu99", "-U__APPLE__",
                           "-I", str(ROOT / "ports" / port / "test"),
                           "-I", str(generated), f'-DPORT_MENU="{menu}"',
                           "-ffunction-sections", "-fdata-sections", str(FIXTURE),
                           "-Wl,-dead_strip", "-Wl,-undefined,dynamic_lookup",
                           "-o", str(binary)]
                    subprocess.run(cmd, check=True)
                    subprocess.run([str(binary)], check=True)

if __name__ == "__main__":
    unittest.main()
