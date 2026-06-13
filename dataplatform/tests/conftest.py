"""Pytest setup: isolate the data home to a temp dir BEFORE dataplatform imports."""
import atexit
import os
import shutil
import tempfile
from pathlib import Path

# Must run before any `import dataplatform.*` so the settings singleton picks it up.
_TMP = Path(tempfile.mkdtemp(prefix="dataplatform_test_"))
os.environ.setdefault("DATAPLATFORM_HOME", str(_TMP))
os.environ.pop("TIMESCALE_DSN", None)  # force SQLite fallback in tests

# Clean our isolated home safely at process exit (never raise on cleanup).
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))
