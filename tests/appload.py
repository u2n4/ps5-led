"""Import dualled_pro without touching the real settings folder.

dualled_pro reads %APPDATA% and creates its config folder when it is imported,
so a test that imports it points APPDATA at a throwaway folder first. Test
modules that need the app import it through this module.
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_APPDATA = tempfile.mkdtemp(prefix="ps5led-tests-")
atexit.register(shutil.rmtree, _APPDATA, True)
os.environ["APPDATA"] = _APPDATA

import dualled_pro  # noqa: E402
