"""Production Android menu state tests; no assets, Android device or persistence."""
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

class PreRaceTuneHost(unittest.TestCase):
    def test_menu(self):
        if sys.platform != "darwin" or not shutil.which("clang"):
            self.skipTest("macOS clang and Darwin dead-strip required")
        if not (GENERATED / "cardb.h").is_file():
            self.skipTest("generated headers unavailable")
        with tempfile.TemporaryDirectory(prefix="wmmt-prerace-") as tmp:
            cmd = ["clang", "-std=gnu99", "-U__APPLE__", "-DWMMT_PRE_RACE_TEST", "-DWMMT_BGM_TEST",
                   "-I", str(ANDROID / "test"), "-I", str(GENERATED),
                   f'-DPORT_MENU="{ANDROID / "src/menu.c"}"', "-ffunction-sections", "-fdata-sections",
                   str(ANDROID / "tests/pre_race_tune_menu_host.c"), str(ANDROID / "src/pre_race_tune.c"),
                   "-Wl,-dead_strip", "-Wl,-undefined,dynamic_lookup", "-o", str(Path(tmp) / "test")]
            subprocess.run(cmd, check=True)
            subprocess.run([str(Path(tmp) / "test")], check=True)

if __name__ == "__main__":
    unittest.main()
